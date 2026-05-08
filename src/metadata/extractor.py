# module1/src/metadata/extractor.py
import cv2
from datetime import datetime
from config.settings import settings
from src.utils.time_utils import utcnow

class MetadataExtractor:
    """
    Build metadata from a frame and the capture object.
    Tries to extract available properties (resolution, fps) from cv2.VideoCapture object.
    """

    def __init__(self, camera_id, capture_obj=None):
        self.camera_id = camera_id
        self.capture = capture_obj

    def _get_resolution(self, frame):
        if frame is None:
            return None
        h, w = frame.shape[:2]
        return f"{w}x{h}"

    def _get_fps(self):
        if self.capture is None:
            return None
        try:
            fps = self.capture.get(cv2.CAP_PROP_FPS)
            if fps and fps > 0 and fps < 1000:
                return int(round(fps))
        except Exception:
            pass
        return None

    def _get_codec(self):
        # OpenCV's codec extraction is limited. return None by default; could be extended with ffprobe.
        return None

    def _get_bitrate(self):
        # Not easily available from cv2. leave None (could use ffprobe later)
        return None

    def extract(self, frame, extra=None):
        """
        Returns a metadata dict with:
        - timestamp (UTC)
        - camera_id
        - camera_location (from settings if available)
        - resolution
        - frame_rate
        - codec, bitrate if available
        - extra: user-supplied metadata dict
        """
        ts = utcnow()
        md = {
            "timestamp": ts,
            "camera_id": self.camera_id,
            "camera_location": settings.CAMERA_LOCATIONS.get(self.camera_id),
            "resolution": self._get_resolution(frame),
            "frame_rate": self._get_fps(),
            "codec": self._get_codec(),
            "bitrate": self._get_bitrate(),
            "metadata_json": extra or {}
        }
        return md
