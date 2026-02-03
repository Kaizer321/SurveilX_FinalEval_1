
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.video_capture.camera_manager import CameraManager

class TestCameraManager(unittest.TestCase):
    def setUp(self):
        self.sources = {
            "1": "file://video.mp4",
            "2": "device://0",
            "3": "https://youtube.com/watch?v=123"
        }
        self.manager = CameraManager(self.sources)

    def test_identifiers(self):
        self.assertTrue(self.manager._is_file("file://foo.mp4"))
        self.assertTrue(self.manager._is_file("/abs/path/foo.mp4"))
        self.assertTrue(self.manager._is_device("device://0"))
        self.assertTrue(self.manager._is_youtube("https://youtube.com/watch?v=123"))
        
        self.assertFalse(self.manager._is_device("file://0"))
        self.assertFalse(self.manager._is_file("https://google.com"))

    def test_resolve_target(self):
        # File
        res = self.manager.resolve_target("1")
        self.assertEqual(res, "video.mp4")
        
        # Device
        res = self.manager.resolve_target("2")
        self.assertEqual(res, 0)
        
    @patch('src.video_capture.camera_manager.YoutubeDL')
    def test_youtube_resolve(self, mock_ydl_cls):
        # Mock YDL context
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        
        # Mock extraction result
        # Scenario: standard HLS url returned
        mock_ydl.extract_info.return_value = {"url": "http://googlevideo.com/playback.m3u8"}
        
        res = self.manager.resolve_target("3")
        self.assertEqual(res, "http://googlevideo.com/playback.m3u8")
        
        # Verify valid options were passed (no_warnings, quiet)
        _, kwargs = mock_ydl_cls.call_args
        # kwargs might be in the init call, let's check positional arg 0
        args, _ = mock_ydl_cls.call_args
        opts = args[0]
        self.assertTrue(opts.get("quiet"))
        self.assertTrue(opts.get("no_warnings"))

if __name__ == "__main__":
    unittest.main()
