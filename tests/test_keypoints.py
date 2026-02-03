
import unittest
import cv2
import numpy as np
import torch
from unittest.mock import MagicMock
from pathlib import Path
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.detection.violence_detector import ViolenceDetector

class MockKeypoints:
    def __init__(self, xy, conf):
        self.xy = xy
        self.conf = conf

class MockResult:
    def __init__(self, keypoints):
        self.keypoints = keypoints

class TestKeypoints(unittest.TestCase):
    def setUp(self):
        # We don't need real models for drawing tests
        # Patch the load methods so __init__ doesn't fail
        self.patcher1 = unittest.mock.patch('src.detection.violence_detector.ViolenceDetector._load_cnn_tcn')
        self.patcher2 = unittest.mock.patch('src.detection.violence_detector.ViolenceDetector._load_pose_model')
        
        self.mock_load_cnn = self.patcher1.start()
        self.mock_load_pose = self.patcher2.start()
        
        self.detector = ViolenceDetector(
            checkpoint_path=Path("dummy_ckpt"),
            pose_model_path=Path("dummy_pose"),
            device="cpu"
        )
    
    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()

    def test_draw_keypoints_visual(self):
        """
        Verify that _draw_keypoints actually modifies the image 
        at the expected coordinates.
        """
        # Create a black 640x480 image
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Mock keypoints: One person, typical pose structure (nose, eyes, etc.)
        # Shape: (17, 2)
        # Let's put a point at (100, 100) and (200, 200) with high confidence
        xy = torch.zeros((17, 2))
        xy[0] = torch.tensor([100, 100]) # Nose
        xy[1] = torch.tensor([105, 95])  # Left Eye
        xy[2] = torch.tensor([95, 95])   # Right Eye
        # ... just enough to check drawing
        
        conf = torch.ones(17) # High confidence
        
        keypoints = MockKeypoints(xy=[xy], conf=[conf])
        res = MockResult(keypoints)
        
        scale = 1.0
        offset_y = 0
        
        # Execute
        out_frame = self.detector._draw_keypoints(
            frame, res, scale, offset_y, show_keypoints=True
        )
        
        # Verify
        # 1. Image should not be all black anymore
        self.assertGreater(np.sum(out_frame), 0, "Output frame should have content")
        
        # 2. Check specific pixels (red circles for keypoints: BGR (0, 0, 255))
        # Point at 100,100 should be red
        # Note: cv2.circle might not hit exactly 100,100 if radius > 0, but center should be close
        # We check a small region around it
        region = out_frame[98:102, 98:102]
        self.assertTrue(np.any(region[:, :, 2] > 0), "Red channel should be active near keypoint")
        
        # 3. Save for inspection
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        cv2.imwrite(str(output_dir / "keypoint_test.jpg"), out_frame)
        print(f"\n[TestKeypoints] Visual result saved to {output_dir / 'keypoint_test.jpg'}")

    def test_draw_keypoints_real_image(self):
        """
        Load 'tests/test.jpg', run REAL YOLOv8 pose inference, and overlay keypoints.
        Verifies drawing logic works with actual model output.
        """
        from ultralytics import YOLO # Import here to avoid overhead for other tests if possible
        
        img_path = Path(__file__).parent / "test.jpg"
        if not img_path.exists():
            self.skipTest("tests/test.jpg not found")
            
        model_path = Path(__file__).parent.parent / "models" / "yolov8n-pose.pt"
        if not model_path.exists():
             self.skipTest("models/yolov8n-pose.pt not found")

        frame = cv2.imread(str(img_path))
        self.assertIsNotNone(frame, "Failed to load test.jpg")
        
        # Load Real Model
        print(f"\n[TestKeypoints] Loading real pose model from {model_path}...")
        pose_model = YOLO(str(model_path))
        
        # Run Inference
        print("[TestKeypoints] Running inference...")
        results = pose_model.predict(frame, verbose=False)
        res = results[0] # Get first result
        
        # Scale 1.0 because we are using the original frame coordinates from YOLO
        scale = 1.0
        offset_y = 0
        
        # Draw
        out_frame = self.detector._draw_keypoints(
            frame, res, scale, offset_y, show_keypoints=True
        )
        
        # Verify
        self.assertIsNotNone(out_frame)
        self.assertEqual(out_frame.shape, frame.shape)
        
        # Save output
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        out_path = output_dir / "keypoint_test_real.jpg"
        cv2.imwrite(str(out_path), out_frame)
        print(f"[TestKeypoints] Real image result saved to {out_path}")

if __name__ == "__main__":
    unittest.main()
