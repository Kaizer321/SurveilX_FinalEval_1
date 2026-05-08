
import unittest
import numpy as np
from unittest.mock import MagicMock
import sys
import os
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.detection.violence_detector import ViolenceDetector

class TestMultiCamera(unittest.TestCase):
    def setUp(self):
        # Patch the load methods so __init__ doesn't fail
        self.patcher1 = unittest.mock.patch('src.detection.violence_detector.ViolenceDetector._load_cnn_tcn')
        self.patcher2 = unittest.mock.patch('src.detection.violence_detector.ViolenceDetector._load_pose_model')
        
        self.mock_load_cnn = self.patcher1.start()
        self.mock_load_pose = self.patcher2.start()

        self.detector = ViolenceDetector(
            checkpoint_path=Path("dummy"),
            pose_model_path=Path("dummy"),
            device="cpu"
        )
        # Ensure models are mocks
        self.detector.model = MagicMock()
        self.detector.pose_model = MagicMock()
        
        # We need to mock _preprocess_frame, etc. or just mock predict internals?
        # Actually, let's mock the internal helpers to skip tensor/cv2 complexity
        # and just focus on state logic in `predict` which relies on _get_state
        
        self.detector._preprocess_frame = MagicMock(return_value=(MagicMock(), MagicMock(), 1.0, 0))
        self.detector._process_keypoints = MagicMock(return_value=(np.zeros(1), None, np.zeros(1)))
        
    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        
    def test_isolation(self):
        # We want to show that high output on Cam A doesn't affect Cam B
        
        # Mock model output: Returns a tensor of logits
        # Cam A gets Violence (Idx 3, Fighting)
        # Cam B gets Normal (Idx 0)
        
        def side_effect_forward(*args, **kwargs):
            # Check which 'frame_input' or 'camera_id' context we are in?
            # The model forward doesn't know camera ID.
            # We have to fetch the mocks return value based on time or sequential call?
            # Or we can just manually set the return_value before calling predict for each cam.
            return MagicMock() 

        # Let's set up the test loop
        
        # Mock forward pass output
        # Return format: shape (1, 6)
        
        # Fighting Logits (Index 3 high)
        fighting_logits = np.array([[-5.0, -5.0, -5.0, 10.0, -5.0, -5.0]], dtype=np.float32)
        # Normal Logits (Index 0 high)
        normal_logits = np.array([[10.0, -5.0, -5.0, -5.0, -5.0, -5.0]], dtype=np.float32)
        
        import torch
        
        # Sequence:
        # Cam A=Fighting (Should Alert), B=Normal (Should NOT alert)
        
        for i in range(1, 4):
            # --- Process Camera A ---
            self.detector.model.return_value = torch.as_tensor(fighting_logits)
            res_a = self.detector.predict("cam_a", np.zeros((100,100,3)))
            
            # --- Process Camera B ---
            self.detector.model.return_value = torch.as_tensor(normal_logits)
            res_b = self.detector.predict("cam_b", np.zeros((100,100,3)))
            
            # Check instant alert correctly isolated per camera frame
            self.assertTrue(res_a['is_alert'], "Cam A should alert immediately on Fighting")
            self.assertFalse(res_b['is_alert'], "Cam B should NOT alert on Normal")
            self.assertEqual(res_a['label'], "Fighting")
            self.assertEqual(res_b['label'], "Normal")

        # Verify internal state isolation
        state_a = self.detector._get_state("cam_a")
        state_b = self.detector._get_state("cam_b")
        
        self.assertIn("frame_counter", state_a)
        self.assertIn("frame_counter", state_b)

if __name__ == "__main__":
    unittest.main()
