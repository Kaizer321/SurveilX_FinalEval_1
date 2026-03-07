from __future__ import annotations

import collections
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models, transforms
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class TemporalConvNet(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 256, num_layers: int = 3):
        super().__init__()
        layers: List[nn.Module] = []
        for i in range(num_layers):
            in_ch = input_size if i == 0 else hidden_size
            layers.extend(
                [
                    nn.Conv1d(in_ch, hidden_size, kernel_size=3, padding=1),
                    nn.ReLU(),
                    nn.BatchNorm1d(hidden_size),
                ]
            )
        self.tcn = nn.Sequential(*layers)
        self.pool = nn.AdaptiveAvgPool1d(1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x is expected to be (B, C, T) — temporal dimension already provided
        x = self.tcn(x)
        x = self.pool(x).squeeze(2)
        return x


class CNN_TCN_Fusion(nn.Module):
    def __init__(self, temporal_input_size: int, num_classes: int = 6):
        super().__init__()
        self.cnn = models.mobilenet_v3_large(
            weights=models.MobileNet_V3_Large_Weights.DEFAULT
        )
        self.cnn.classifier = nn.Identity()
        cnn_out_size = 960
        self.tcn = TemporalConvNet(temporal_input_size)
        self.fc = nn.Sequential(
            nn.Linear(cnn_out_size + 256, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes),
        )

    def forward(self, frame: torch.Tensor, temporal: torch.Tensor) -> torch.Tensor:
        cnn_feat = self.cnn(frame)
        tcn_feat = self.tcn(temporal)
        fusion = torch.cat([cnn_feat, tcn_feat], dim=1)
        out = self.fc(fusion)
        return out


class ViolenceDetector:
    """
    Pose-assisted violence/action detector with temporal smoothing.
    Maintains per-camera state so multiple streams do not interfere.
    """
    CLASSES = ["Normal", "Pre-Violence", "Burglary", "Fighting", "Shooting", "Stealing"]
    MAX_PEOPLE = 5
    FEATURE_PER_PERSON = 10 + 4 + 17 * 2
    TEMPORAL_BUFFER_SIZE = 16
    EMA_ALPHA = 0.6

    def __init__(
        self,
        checkpoint_path: Path,
        pose_model_path: Path,
        device: Optional[str] = None,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.checkpoint_path = Path(checkpoint_path)
        self.pose_model_path = Path(pose_model_path)
        self.feature_size = self.FEATURE_PER_PERSON * self.MAX_PEOPLE
        self._state: Dict[str, Dict[str, Any]] = {}
        self._to_tensor = transforms.ToTensor()
        self._normalize = transforms.Normalize(
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        )

        self.model = self._load_cnn_tcn()
        # Optimize for fixed input sizes
        try:
            if torch.cuda.is_available():
                torch.backends.cudnn.benchmark = True
        except ImportError:
            pass

        self.pose_model = self._load_pose_model()

    # ---------------- Model loading ----------------
    def _load_cnn_tcn(self) -> CNN_TCN_Fusion:
        temporal_input_size = 240 + 5 * 17 * 2
        model = CNN_TCN_Fusion(temporal_input_size).to(self.device)
        if not self.checkpoint_path.exists():
            raise FileNotFoundError(f"Detector checkpoint not found: {self.checkpoint_path}")
        checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
        # Handle both checkpoint formats: direct state_dict or wrapped in dictionary
        state_dict = checkpoint["model_state"] if isinstance(checkpoint, dict) and "model_state" in checkpoint else checkpoint
        try:
            model.load_state_dict(state_dict)
        except RuntimeError:
            logger.warning(
                "Checkpoint shape mismatch — loading with strict=False. "
                "Retraining is recommended to benefit from the updated architecture."
            )
            model.load_state_dict(state_dict, strict=False)
        model.eval()
        return model

    def _load_pose_model(self) -> YOLO:
        if not self.pose_model_path.exists():
            raise FileNotFoundError(f"YOLO pose model not found: {self.pose_model_path}")
        pose = YOLO(str(self.pose_model_path))
        pose.to(self.device)
        return pose

    # ---------------- Helpers ----------------
    def _get_state(self, camera_id: str) -> Dict[str, Any]:
        cam_id = str(camera_id)
        if cam_id not in self._state:
            self._state[cam_id] = {
                "prev_kp": None,
                "locked_class_idx": 0,
                "candidate_class_idx": 0,
                "consecutive_count": 0,
                "alert_consecutive_count": 0,
                "alert_active": False,
                "temporal_buffer": collections.deque(maxlen=self.TEMPORAL_BUFFER_SIZE),
                "smooth_kp": None,
            }
        return self._state[cam_id]

    def _process_keypoints(
        self, res: Any, prev_kp: Optional[np.ndarray]
    ) -> Tuple[np.ndarray, Optional[List[np.ndarray]], np.ndarray]:
        if res.keypoints is None or len(res.keypoints.xy) == 0:
            empty_feat = np.zeros(self.feature_size, dtype=np.float32)
            empty_kp = np.zeros((self.MAX_PEOPLE, 17, 2), dtype=np.float32)
            return empty_feat, None, empty_kp

        persons = []
        for xy, conf in zip(res.keypoints.xy, res.keypoints.conf):
            xy_np = xy.cpu().numpy()
            conf_np = conf.cpu().numpy()
            if xy_np.shape != (17, 2):
                continue
            persons.append((conf_np.mean(), xy_np, conf_np))

        if len(persons) == 0:
            return np.zeros(self.feature_size, dtype=np.float32), None, np.zeros(
                (self.MAX_PEOPLE, 17, 2)
            )

        persons.sort(key=lambda x: x[0], reverse=True)
        selected = persons[: self.MAX_PEOPLE]

        person_features = []
        normalized_kp_out = []
        new_prev_kp = []

        def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
            ba = a - b
            bc = c - b
            denom = (np.linalg.norm(ba) * np.linalg.norm(bc)) + 1e-6
            cosang = np.dot(ba, bc) / denom
            return float(np.arccos(np.clip(cosang, -1, 1)))

        for i, (_, xy_np, _) in enumerate(selected):
            torso = np.linalg.norm(xy_np[5] - xy_np[11]) + 1e-6
            kp_norm = (xy_np - xy_np.mean(axis=0)) / torso
            normalized_kp_out.append(kp_norm)

            pairs = [
                (5, 7),
                (7, 9),
                (6, 8),
                (8, 10),
                (11, 13),
                (13, 15),
                (12, 14),
                (14, 16),
                (5, 6),
                (11, 12),
            ]
            dists = [np.linalg.norm(kp_norm[a] - kp_norm[b]) for a, b in pairs]
            ang = [
                _angle(kp_norm[5], kp_norm[7], kp_norm[9]),
                _angle(kp_norm[6], kp_norm[8], kp_norm[10]),
                _angle(kp_norm[11], kp_norm[13], kp_norm[15]),
                _angle(kp_norm[12], kp_norm[14], kp_norm[16]),
            ]

            vel = np.zeros_like(kp_norm)
            if prev_kp is not None and i < len(prev_kp):
                vel = kp_norm - prev_kp[i]

            new_prev_kp.append(kp_norm.copy())
            person_feat = np.concatenate([dists, ang, vel.flatten()])
            person_features.append(person_feat)

        while len(person_features) < self.MAX_PEOPLE:
            person_features.append(np.zeros_like(person_features[0]))
            normalized_kp_out.append(np.zeros((17, 2)))
            new_prev_kp.append(np.zeros((17, 2)))

        feature_vec = np.concatenate(person_features, dtype=np.float32)
        return feature_vec, new_prev_kp, np.array(normalized_kp_out, dtype=np.float32)

    def _preprocess_frame(
        self, frame_bgr: np.ndarray
    ) -> Tuple[torch.Tensor, np.ndarray, float, int]:
        h, w, _ = frame_bgr.shape
        scale = 224 / w
        new_w = 224
        new_h = int(h * scale)
        frame_resized = cv2.resize(frame_bgr, (new_w, new_h))
        top = (224 - new_h) // 2
        bottom = 224 - new_h - top
        frame_padded = cv2.copyMakeBorder(
            frame_resized, top, bottom, 0, 0, cv2.BORDER_CONSTANT, value=[0, 0, 0]
        )
        frame_rgb = cv2.cvtColor(frame_padded, cv2.COLOR_BGR2RGB)
        tensor = self._normalize(self._to_tensor(frame_rgb)).unsqueeze(0).to(self.device)
        return tensor, frame_padded, scale, top

    def _draw_keypoints(
        self,
        frame_bgr: np.ndarray,
        res: Any,
        scale: float,
        offset_y: int,
        show_keypoints: bool,
    ) -> np.ndarray:
        if not show_keypoints or res.keypoints is None or len(res.keypoints.xy) == 0:
            return frame_bgr

        skeleton = [
            (5, 7),
            (7, 9),
            (6, 8),
            (8, 10),
            (11, 13),
            (13, 15),
            (12, 14),
            (14, 16),
            (5, 6),
            (11, 12),
        ]
        frame_copy = frame_bgr.copy()
        for kp_xy, kp_conf in zip(res.keypoints.xy, res.keypoints.conf):
            kp_xy_np = kp_xy.cpu().numpy()
            kp_conf_np = kp_conf.cpu().numpy()
            if kp_xy_np.shape != (17, 2):
                continue
            kp_xy_transformed = kp_xy_np.copy()
            kp_xy_transformed[:, 0] = kp_xy_transformed[:, 0] / scale
            kp_xy_transformed[:, 1] = (kp_xy_transformed[:, 1] - offset_y) / scale

            for pt1_idx, pt2_idx in skeleton:
                if pt1_idx < len(kp_xy_transformed) and pt2_idx < len(kp_xy_transformed):
                    if kp_conf_np[pt1_idx] > 0.3 and kp_conf_np[pt2_idx] > 0.3:
                        pt1 = tuple(map(int, kp_xy_transformed[pt1_idx]))
                        pt2 = tuple(map(int, kp_xy_transformed[pt2_idx]))
                        cv2.line(frame_copy, pt1, pt2, (0, 255, 255), 2)

            for i, (x, y) in enumerate(kp_xy_transformed):
                if kp_conf_np[i] > 0.3:
                    cv2.circle(frame_copy, (int(x), int(y)), 4, (0, 0, 255), -1)
        return frame_copy

    # ---------------- Public API ----------------
    def predict(
        self,
        camera_id: str,
        frame_bgr: np.ndarray,
        *,
        target_fps: int = 15,
        show_keypoints: bool = False,
        confidence_threshold: float = 0.5,
        strict_threshold: float = 0.75,
        lock_sequence_length: int = 3,
        normal_sequence_length: int = 8,
        switch_sequence_length: int = 5,
        alert_sequence_length: int = 3,
    ) -> Dict[str, Any]:
        """
        Run detection on a single frame while keeping per-camera temporal state.
        Returns label, score, class probabilities, and optional overlay frame.
        """
        state = self._get_state(camera_id)
        frame_tensor, frame_for_yolo, scale, top_pad = self._preprocess_frame(frame_bgr)

        with torch.no_grad():
            res_list = self.pose_model.predict(
                frame_for_yolo, verbose=False, device=self.device
            )
            res = res_list[0]
            feat, prev_kp, kp_norm = self._process_keypoints(res, state["prev_kp"])
            state["prev_kp"] = prev_kp

            # Apply EMA smoothing to reduce keypoint noise
            alpha = self.EMA_ALPHA
            if state["smooth_kp"] is not None:
                smooth_kp = alpha * kp_norm + (1 - alpha) * state["smooth_kp"]
            else:
                smooth_kp = kp_norm.copy()
            state["smooth_kp"] = smooth_kp

            # Build temporal input and accumulate into sliding window buffer
            temporal_input = np.concatenate([feat, smooth_kp.flatten()])
            state["temporal_buffer"].append(temporal_input)
            buffer = np.array(list(state["temporal_buffer"]))  # (T, C)
            if len(buffer) < self.TEMPORAL_BUFFER_SIZE:
                pad = np.zeros((self.TEMPORAL_BUFFER_SIZE - len(buffer), buffer.shape[1]), dtype=np.float32)
                buffer = np.vstack([pad, buffer])
            temporal_tensor = torch.tensor(
                buffer.T, dtype=torch.float32, device=self.device
            ).unsqueeze(0)
            # Shape: (1, C, T)

            outputs = self.model(frame_tensor, temporal_tensor)
            probs = F.softmax(outputs, dim=1)
            max_prob, pred_idx_tensor = torch.max(probs, 1)
            pred_conf = float(max_prob.item())
            pred_idx = int(pred_idx_tensor.item())
            all_probs = probs[0].detach().cpu().numpy()

        locked_class_idx = state["locked_class_idx"]
        candidate_class_idx = state["candidate_class_idx"]
        consecutive_count = state["consecutive_count"]

        non_normal_exceeds = False
        best_non_normal_idx = 0
        best_non_normal_conf = 0.0
        
        # Check non-normal classes with updated probs
        for i in range(1, len(self.CLASSES)):
            if all_probs[i] >= confidence_threshold and all_probs[i] > best_non_normal_conf:
                non_normal_exceeds = True
                best_non_normal_conf = float(all_probs[i])
                best_non_normal_idx = i

        if non_normal_exceeds:
            current_candidate_idx = best_non_normal_idx
            current_candidate_conf = best_non_normal_conf
        else:
            current_candidate_idx = 0
            current_candidate_conf = float(all_probs[0])

        if locked_class_idx == 0:
            if current_candidate_idx != 0:
                if current_candidate_idx == candidate_class_idx:
                    consecutive_count += 1
                    if consecutive_count >= lock_sequence_length:
                        locked_class_idx = current_candidate_idx
                        candidate_class_idx = current_candidate_idx
                        consecutive_count = 0
                else:
                    candidate_class_idx = current_candidate_idx
                    consecutive_count = 1
                final_idx = current_candidate_idx
                final_conf = current_candidate_conf
            else:
                if candidate_class_idx != 0 and consecutive_count > 0:
                    if consecutive_count < lock_sequence_length:
                        final_idx = candidate_class_idx
                        final_conf = float(all_probs[candidate_class_idx])
                        consecutive_count = 0
                    else:
                        candidate_class_idx = 0
                        consecutive_count = 0
                        final_idx = 0
                        final_conf = float(all_probs[0])
                else:
                    candidate_class_idx = 0
                    consecutive_count = 0
                    final_idx = 0
                    final_conf = float(all_probs[0])
        else:
            if current_candidate_idx == 0:
                if candidate_class_idx == 0:
                    consecutive_count += 1
                    if consecutive_count >= normal_sequence_length:
                        locked_class_idx = 0
                        candidate_class_idx = 0
                        consecutive_count = 0
                else:
                    candidate_class_idx = 0
                    consecutive_count = 1
            elif current_candidate_idx == locked_class_idx:
                candidate_class_idx = locked_class_idx
                consecutive_count = 0
            else:
                if current_candidate_idx == candidate_class_idx:
                    consecutive_count += 1
                    if consecutive_count >= switch_sequence_length:
                        locked_class_idx = current_candidate_idx
                        candidate_class_idx = current_candidate_idx
                        consecutive_count = 0
                else:
                    candidate_class_idx = current_candidate_idx
                    consecutive_count = 1
            final_idx = locked_class_idx
            final_conf = float(all_probs[locked_class_idx])

        state["locked_class_idx"] = locked_class_idx
        state["candidate_class_idx"] = candidate_class_idx
        state["consecutive_count"] = consecutive_count

        overlay = self._draw_keypoints(
            frame_bgr, res, scale=scale, offset_y=top_pad, show_keypoints=show_keypoints
        )

        # Extract raw keypoints for external upscaling (relative to frame_bgr)
        raw_keypoints = []
        if res.keypoints is not None:
            for kp_xy, kp_conf in zip(res.keypoints.xy, res.keypoints.conf):
                kp_xy_np = kp_xy.cpu().numpy()
                kp_conf_np = kp_conf.cpu().numpy()
                if kp_xy_np.shape != (17, 2):
                    continue
                
                # Apply same reverse transformation as _draw_keypoints
                transformed = kp_xy_np.copy()
                transformed[:, 0] = transformed[:, 0] / scale
                transformed[:, 1] = (transformed[:, 1] - top_pad) / scale
                
                # Structure: List of {xy: [[x,y],..], conf: [c,..]}
                raw_keypoints.append({
                    "xy": transformed.tolist(),
                    "conf": kp_conf_np.tolist()
                })

        # Post-process: If the final confidence is below the threshold, 
        # force report as "Normal" to avoid confusing the user with "Fighting (0.02)"
        # This keeps the internal state (locked_class) intact for temporal consistency,
        # but suppresses the UI display until confidence recovers.
        if final_idx != 0 and final_conf < confidence_threshold:
            final_idx = 0
            final_conf = float(all_probs[0])

        # Check strict alert with consecutive frames
        alert_count = state.get("alert_consecutive_count", 0)
        alert_active = state.get("alert_active", False)
        
        # We only count frames where the FINAL locked decision is alert-worthy
        # AND the confidence is high enough.
        if final_idx != 0 and final_conf >= strict_threshold:
            alert_count += 1
        else:
            alert_count = 0
            alert_active = False # Reset alert state if we drop back to normal/low confidence
            
        state["alert_consecutive_count"] = alert_count
        
        is_alert = False
        if alert_count >= alert_sequence_length:
            if not alert_active:
                is_alert = True
                alert_active = True
        
        state["alert_active"] = alert_active
        
        return {
            "label": self.CLASSES[final_idx],
            "score": final_conf,
            "class_index": final_idx,
            "class_probs": {name: float(prob) for name, prob in zip(self.CLASSES, all_probs)},
            "probs": {name: float(prob) for name, prob in zip(self.CLASSES, all_probs)}, # Alias for better API
            "raw_probs": all_probs,
            "overlay_frame": overlay,
            "predicted_index": pred_idx,
            "predicted_conf": pred_conf,
            "is_alert": is_alert,
            "keypoints": raw_keypoints
        }

