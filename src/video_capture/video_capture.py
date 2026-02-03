# module1/src/video_capture/video_capture.py
import cv2
import threading
import queue
import time

class VideoCapture:
    """Handles concurrent capture from multiple YouTube-based cameras."""

    def __init__(self, camera_manager, buffer_size=2):
        self.camera_manager = camera_manager
        self.buffer_size = buffer_size
        self.frame_buffers = {}
        self.capture_threads = {}
        self.running = {}

    def _capture_loop(self, camera_id, _initial_unused):
        frame_queue = queue.Queue(maxsize=self.buffer_size)
        self.frame_buffers[camera_id] = frame_queue
        self.running[camera_id] = True
        # Always resolve target via camera_manager to support device/file/url
        target = self.camera_manager.resolve_target(camera_id)
        print(f"[VideoCapture] Started capture for {camera_id}")

        # consecutive failure backoff
        fail_count = 0
        while self.running.get(camera_id, False):
            # Decide backend based on original source type
            src = self.camera_manager.get_source(camera_id) or ""
            cap = None
            try:
                if isinstance(target, int):
                    # Device: try preferred Windows backends first, then auto
                    for be in [getattr(cv2, 'CAP_DSHOW', None), getattr(cv2, 'CAP_MSMF', None), 0]:
                        if be is None:
                            continue
                        cap = cv2.VideoCapture(target, be) if be else cv2.VideoCapture(target)
                        if cap.isOpened():
                            break
                elif isinstance(target, str) and (src.lower().startswith('http') or src.lower().startswith('rtsp') or src.lower().startswith('https')):
                    # URL: use FFMPEG
                    cap = cv2.VideoCapture(target, cv2.CAP_FFMPEG)
                else:
                    # File or fallback
                    cap = cv2.VideoCapture(target)
            except Exception:
                cap = None
            if not cap or not cap.isOpened():
                wait = min(5.0, 1.0 + fail_count * 0.5)
                print(f"[VideoCapture] Failed to open stream for {camera_id}, retrying in {wait:.1f}s")
                time.sleep(wait)
                fail_count += 1
                # Re-resolve target (important for YouTube where hosts rotate)
                try:
                    target = self.camera_manager.resolve_target(camera_id)
                except Exception:
                    pass
                continue

            # Read frames until failure or stop requested
            is_local_file = self.camera_manager._is_file(src)
            while self.running.get(camera_id, False):
                ret, frame = cap.read()
                if not ret:
                    if is_local_file:
                        # seamless loop for local files
                        try:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        except Exception:
                            pass
                    
                    # On real failure or stream EOF, break to reopen
                    print(f"[VideoCapture] Read failed for {camera_id}, reopening...")
                    break
                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except Exception:
                        pass
                try:
                    frame_queue.put_nowait(frame)
                except Exception:
                    pass
                time.sleep(0.03)  # approx 30 fps

            cap.release()
            # Refresh URL before next attempt (handles host changes)
            try:
                target = self.camera_manager.resolve_target(camera_id)
            except Exception:
                time.sleep(1.0)
                continue
            # reset backoff after a successful open-read loop iteration
            fail_count = 0

        print(f"[VideoCapture] Capture stopped for {camera_id}")

    def start_capture(self, camera_id):
        """Begin threaded video capture."""
        # Ensure connection metadata tracked (optional)
        try:
            self.camera_manager.connect_camera(camera_id)
        except Exception:
            pass
        thread = threading.Thread(target=self._capture_loop,
                                  args=(camera_id, None),
                                  daemon=True)
        self.capture_threads[camera_id] = thread
        thread.start()

    def stop_capture(self, camera_id):
        """Stop capture and disconnect camera."""
        self.running[camera_id] = False
        self.camera_manager.disconnect_camera(camera_id)

    def get_frame(self, camera_id):
        """Fetch the latest frame from buffer (non-blocking)."""
        buf = self.frame_buffers.get(camera_id)
        if buf and not buf.empty():
            return buf.get()
        return None

    def get_camera_status(self, camera_id):
        return self.camera_manager.get_camera_status(camera_id)
