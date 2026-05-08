
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

    def test_alert_logic(self):
        # We test that `is_alert` correctly responds to confidence thresholds instantaneously.
        camera_id = "cam1"
        dummy_frame = np.zeros((224, 224, 3), dtype=np.uint8)
        
        def run_step(probs):
            logits = torch.tensor([np.log(p + 1e-9) for p in probs]).unsqueeze(0)
            self.detector.model.return_value = logits
            return self.detector.predict(camera_id, dummy_frame, confidence_threshold=0.75)

        # 1. Normal State
        normal_probs = np.array([0.9, 0.02, 0.02, 0.02, 0.02, 0.02])
        res = run_step(normal_probs)
        self.assertFalse(res['is_alert'], "Should not alert on Normal")
        self.assertEqual(res['label'], 'Normal')
        
        # 2. Fighting (High Confidence)
        fight_probs = np.array([0.05, 0.05, 0.0, 0.90, 0.0, 0.0])
        res = run_step(fight_probs) 
        self.assertTrue(res['is_alert'], "Should alert instantly on >0.75 Fighting")
        self.assertEqual(res['label'], 'Fighting')

        # 3. Fighting (Low Confidence)
        low_fight_probs = np.array([0.20, 0.10, 0.0, 0.70, 0.0, 0.0])
        res = run_step(low_fight_probs)
        # Should be labeled fighting but NOT an alert since 0.70 < 0.75
        self.assertFalse(res['is_alert'], "Should not alert on <0.75 Fighting")
        self.assertEqual(res['label'], 'Fighting')
        
if __name__ == '__main__':
    unittest.main()
