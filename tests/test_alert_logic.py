
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from pathlib import Path
import torch

# Add src to path
# Add src to path correctly
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from detection.violence_detector import ViolenceDetector

class TestAlertLogic(unittest.TestCase):
    def setUp(self):
        # Mock dependencies to avoid loading real models
        self.mock_yolo = MagicMock()
        self.mock_cnn_tcn = MagicMock()
        
        # Patch the load methods
        with patch.object(ViolenceDetector, '_load_cnn_tcn', return_value=self.mock_cnn_tcn), \
             patch.object(ViolenceDetector, '_load_pose_model', return_value=self.mock_yolo):
            
            # Initialize detector with dummy paths
            self.detector = ViolenceDetector(
                checkpoint_path="dummy_ckpt.pth",
                pose_model_path="dummy_pose.pt"
            )

    @patch('detection.violence_detector.ViolenceDetector._preprocess_frame')
    @patch('detection.violence_detector.ViolenceDetector._process_keypoints')
    @patch('detection.violence_detector.ViolenceDetector._draw_keypoints')
    @patch('torch.no_grad')
    @patch('torch.tensor')
    def test_alert_logic(self, mock_tensor, mock_no_grad, mock_draw_keypoints, mock_process_keypoints, mock_preprocess_frame):
        # Setup mocks for helper methods
        mock_preprocess_frame.return_value = (MagicMock(), MagicMock(), 1.0, 0)
        mock_process_keypoints.return_value = (np.zeros(10), None, np.zeros((5, 17, 2)))
        mock_draw_keypoints.return_value = np.zeros((224, 224, 3), dtype=np.uint8)
        
        # Mock model output probabilities
        # We'll simulate the behavior by controlling what self.model returns or 
        # more easily, we can just monkey-patch the internal logic if we want, 
        # but let's try to mock the model call since that's cleanly decoupled.
        
        # Actually, to make it easier to control 'all_probs', let's mock the internal variables
        # inside predict. But 'predict' calculates 'all_probs' inside.
        # A Better way is to Subclass and override the inference part.
        pass

# Helper subclass to bypass inference and inject probabilities
class TestableViolenceDetector(ViolenceDetector):
    def __init__(self):
        # Skip init that loads models
        self.device = "cpu"
        self._state = {}
        self.CLASSES = ["Normal", "Pre-Violence", "Burglary", "Fighting", "Shooting", "Stealing"]
        self.MAX_PEOPLE = 5
        self.feature_size = 100 # dummy
        self.injected_probs = None # Set this in test
        self.pose_model = MagicMock()
        self.model = MagicMock()

    def _preprocess_frame(self, frame_bgr):
        return MagicMock(), MagicMock(), 1.0, 0

    def _process_keypoints(self, res, prev_kp):
        return np.zeros(10), None, np.zeros((5, 17, 2))

    def _draw_keypoints(self, frame_bgr, res, scale, offset_y, show_keypoints):
        return frame_bgr

    def predict(self, camera_id, frame_bgr, **kwargs):
        # We override predict to inject our probs, but we want to test the logic *after* probs.
        # So we'll copy the logic from the real class but replace the inference part.
        
        # COPY OF PREDICT METHOD LOGIC (PARTIAL)
        state = self._get_state(camera_id)
        
        # SKIP INFERENCE
        # Use injected probs
        if self.injected_probs is not None:
            all_probs = self.injected_probs
        else:
            all_probs = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0]) # Valid Normal
            
        pred_idx = np.argmax(all_probs)
        pred_conf = float(all_probs[pred_idx])
        
        # --- LOGIC UNDER TEST STARTS HERE ---
        
        # --- This matches the original code's logic flow ---
        confidence_threshold = kwargs.get('confidence_threshold', 0.75)
        strict_threshold = kwargs.get('strict_threshold', 0.90)
        lock_sequence_length = kwargs.get('lock_sequence_length', 5)
        normal_sequence_length = kwargs.get('normal_sequence_length', 10)
        switch_sequence_length = kwargs.get('switch_sequence_length', 8)
        alert_sequence_length = kwargs.get('alert_sequence_length', 3)

        # Copied logic
        if len(all_probs) > 1:
            pre_violence_conf = all_probs[1]
            if pre_violence_conf > 0.35:
                all_probs[1] = min(1.0, pre_violence_conf * 1.4)

        locked_class_idx = state["locked_class_idx"]
        candidate_class_idx = state["candidate_class_idx"]
        consecutive_count = state["consecutive_count"]

        # ... (Re-implementing the state machine logic here mirrors the code, but if I copy-paste I risk divergence)
        # Instead, I should have refactored the logic into a `_update_state(probs)` method.
        # But I can't refactor for the user right now without asking.
        # So I will use the `TestableViolenceDetector` to call the REAL `predict` but verify results.
        # Wait, if I use the REAL `predict`, I need to mock `model(frame, temporal)` to return logits that softmax to my desired probs.
        return super().predict(camera_id, frame_bgr, **kwargs)

class MockModel_CNN_TCN:
    def __init__(self, desired_probs):
        self.desired_probs = desired_probs
        
    def __call__(self, *args, **kwargs):
        # logic so softmax(logits) ~= desired_probs
        # logits = log(probs)
        # Add small epsilon to avoid log(0)
        logits = np.log(self.desired_probs + 1e-9)
        return torch.tensor(logits).unsqueeze(0)

class RealLogicTest(unittest.TestCase):
    def setUp(self):
        # Patch load methods to return mocks
        with patch('detection.violence_detector.ViolenceDetector._load_cnn_tcn') as mock_load_cnn, \
             patch('detection.violence_detector.ViolenceDetector._load_pose_model') as mock_load_pose:
            
            mock_load_cnn.return_value = MagicMock()
            mock_load_pose.return_value = MagicMock()
            
            self.detector = ViolenceDetector(Path("ckpt"), Path("pose"))
            
            # Prepare dummy frame
            self.dummy_frame = np.zeros((224, 224, 3), dtype=np.uint8)

    def test_alert_sequence(self):
        camera_id = "cam1"
        
        # Helper to run a step with specific probs
        def run_step(probs):
            # Mock the model output
            # We need to mock self.detector.model
            
            # Create a mock that returns a tensor which when softmaxed gives `probs`
            # softmax(x)_i = exp(x_i) / sum(exp(x_j))
            # simple x_i = log(p_i) works if we ignore scale
            logits = torch.tensor([np.log(p + 1e-9) for p in probs]).unsqueeze(0)
            
            self.detector.model.return_value = logits
            
            # Also mock pose model to return something valid so _process_keypoints works
            mock_res = MagicMock()
            mock_res.keypoints.xy = torch.zeros((1, 17, 2))
            mock_res.keypoints.conf = torch.ones((1, 17))
            self.detector.pose_model.predict.return_value = [mock_res]
            
            return self.detector.predict(camera_id, self.dummy_frame, strict_threshold=0.9, alert_sequence_length=3)

        print("\n--- Testing Alert Logic ---")
        
        # 1. Normal State
        normal_probs = np.array([0.9, 0.02, 0.02, 0.02, 0.02, 0.02])
        res = run_step(normal_probs)
        print(f"Frame 1 (Normal): Alert={res['is_alert']}")
        self.assertFalse(res['is_alert'])
        
        # 2. Start Violence (Fighting) - Frame 1
        fight_probs = np.array([0.05, 0.05, 0.0, 0.95, 0.0, 0.0])
        # Need multiple frames to lock class?
        # lock_sequence_length is 5 by default.
        # But wait, strict_threshold check compares `final_idx` and `final_conf`.
        # `final_idx` depends on `locked_class_idx` logic.
        
        # Let's walk through the state machine updates in `predict`...
        # If locked_class_idx == 0:
        #   if candidate != 0:
        #      consecutive++
        #      if consecutive >= lock_len: lock!
        
        # So we need `lock_sequence_length` frames to switch from Normal -> Fighting.
        # set lock_sequence_length=1 for easier testing? No, user default is 5.
        # Let's use custom params in predict to speed up: lock_sequence_length=1
        
        params = {"lock_sequence_length": 2, "alert_sequence_length": 2, "strict_threshold": 0.9}
        
        def run(probs):
            logits = torch.tensor([np.log(p + 1e-9) for p in probs]).unsqueeze(0)
            self.detector.model.return_value = logits
            mock_res = MagicMock()
            mock_res.keypoints.xy = torch.zeros((1, 17, 2))
            mock_res.keypoints.conf = torch.ones((1, 17))
            self.detector.pose_model.predict.return_value = [mock_res]
            return self.detector.predict(camera_id, self.dummy_frame, **params)
            
        # Frame 1: Fighting detected (Candidate)
        # consecutive=1 < lock_len(2) -> final is candidate
        res = run(fight_probs) 
        self.assertEqual(res['label'], 'Fighting')
        self.assertFalse(res['is_alert'], "Should not alert yet (count 1 < 2)")
        
        # Frame 2: Fighting detected (Locked)
        # consecutive=2 >= lock_len(2) -> locked=Fighting
        # final=Fighting
        # alert_count -> 2 >= alert_len(2) -> Alert!
        res = run(fight_probs)
        self.assertEqual(res['label'], 'Fighting')
        self.assertTrue(res['is_alert'], "Should alert now")
        print("Frame 2 (Fighting): Alert Triggered")
        
        # Frame 3: Fighting continues
        # Alert was already active. Should NOT alert again.
        res = run(fight_probs)
        self.assertEqual(res['label'], 'Fighting')
        self.assertFalse(res['is_alert'], "Should suppress subsequent alerts")
        print("Frame 3 (Fighting): Alert Suppressed")
        
        # Frame 4: Fighting continues
        res = run(fight_probs)
        self.assertFalse(res['is_alert'])
        
        # Frame 5: Back to Normal (Low confidence Fighting -> suppressed to Normal)
        params["normal_sequence_length"] = 2
        
        # Frame 5: Normal
        # Even though locked_class is Fighting, confidence is low, so it outputs Normal
        # and alert state resets because final output is Normal.
        res = run(normal_probs)
        self.assertEqual(res['label'], 'Normal') 
        self.assertFalse(res['is_alert'])
        
        # Frame 6: Normal
        # consecutive=2 >= normal_len(2) -> locked=Normal
        # final=Normal
        # alert_active should reset?
        # logic: if final_idx != 0 ... else alert_count=0; alert_active=False
        res = run(normal_probs)
        self.assertEqual(res['label'], 'Normal')
        self.assertFalse(res['is_alert'])
        print("Frame 6 (Normal): Alert State Reset")
        
        # Frame 7: Fighting again!
        # Should trigger alert again after lock+alert sequence
        
        # Frame 7 (Candidate)
        res = run(fight_probs)
        self.assertFalse(res['is_alert'])
        
        # Frame 8 (Locked + Alert)
        res = run(fight_probs)
        self.assertTrue(res['is_alert'], "Should alert again for new event")
        print("Frame 8 (New Fighting): Alert Triggered Again")

if __name__ == '__main__':
    unittest.main()
