# module1/src/preprocessing/video_preprocessor.py
import cv2
import numpy as np

class VideoPreprocessor:
    """
    Handles preprocessing tasks for standardizing and enhancing video frames.
    """

    def __init__(self, target_resolution=(320, 200), target_fps=30, output_format="mp4"):
        self.target_resolution = target_resolution
        self.target_fps = target_fps
        self.output_format = output_format

    def standardize_format(self, frame):
        """Ensure frame is in BGR uint8 format."""
        if frame is None:
            return None
        if frame.dtype != np.uint8:
            frame = cv2.convertScaleAbs(frame)
        return frame

    def normalize_resolution(self, frame):
        """Resize frame to target resolution."""
        if frame is None:
            return None
        return cv2.resize(frame, self.target_resolution)

    def adjust_frame_rate(self, frames, original_fps):
        """
        Adjusts frame rate by skipping or duplicating frames.
        (For stream simulation, we'll only subsample.)
        """
        if not frames:
            return frames
        if original_fps <= 0:
            original_fps = self.target_fps
        ratio = original_fps / self.target_fps
        if ratio > 1:
            frames = frames[::int(ratio)]
        return frames

    def to_grayscale_and_normalize(self, frame_bgr):
        """Convert to grayscale, apply normalization (histogram equalization), slight denoise.
        Returns a 3-channel BGR image that is visually grayscale for downstream compatibility.
        """
        if frame_bgr is None:
            return None
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # Histogram equalization for contrast normalization
        gray = cv2.equalizeHist(gray)
        # Light Gaussian blur to reduce noise
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        # Replicate into 3 channels for components that expect BGR
        bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        return bgr

    def process_frame(self, frame, grayscale: bool = False):
        """Full preprocessing pipeline for a single frame.
        Steps: standardize dtype -> resize(320x200) -> optional grayscale normalization.
        Returns BGR frame; stays in color unless grayscale=True.
        """
        frame = self.standardize_format(frame)
        frame = self.normalize_resolution(frame)
        if frame is None:
            return None
        if grayscale:
            frame = self.to_grayscale_and_normalize(frame)
        return frame
