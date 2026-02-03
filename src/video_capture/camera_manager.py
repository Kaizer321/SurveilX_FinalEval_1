# module1/src/video_capture/camera_manager.py
import threading
from yt_dlp import YoutubeDL
import os
import re

class CameraManager:
    """Manages discovery and connection of YouTube-based camera streams."""

    def __init__(self, camera_sources: dict):
        self.camera_sources = dict(camera_sources)
        self.connections = {}
        self.locks = {str(cam_id): threading.Lock() for cam_id in self.camera_sources}

    def discover_cameras(self):
        """List all available cameras."""
        return list(self.camera_sources.keys())

    def _resolve_youtube_url(self, youtube_url):
        """Return a direct video stream URL for OpenCV."""
        # Prefer a progressive MP4 (single file) over HLS to reduce read failures
        ydl_opts = {"quiet": True, "noplaylist": True, "no_warnings": True}
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            # Try to pick best progressive mp4
            fmts = info.get("formats") or []
            best = None
            for f in fmts:
                v = (f.get("vcodec") or "none").lower()
                a = (f.get("acodec") or "none").lower()
                ext = (f.get("ext") or "").lower()
                url = f.get("url") or ""
                if ext == "mp4" and v != "none" and a != "none" and url.startswith("http"):
                    # choose the highest resolution by width/height/bitrate heuristics
                    if best is None:
                        best = f
                    else:
                        b_w = best.get("width") or 0
                        b_h = best.get("height") or 0
                        b_tbr = best.get("tbr") or 0
                        w = f.get("width") or 0
                        h = f.get("height") or 0
                        tbr = f.get("tbr") or 0
                        if (w, h, tbr) > (b_w, b_h, b_tbr):
                            best = f
            if best and best.get("url"):
                return best["url"]
            # Fallback to the generic URL (may be HLS)
            return info.get("url") or youtube_url

    def _is_youtube(self, url: str) -> bool:
        u = (url or '').lower()
        return ('youtube.com' in u) or ('youtu.be' in u)

    def _is_device(self, src: str) -> bool:
        return isinstance(src, str) and src.lower().startswith('device://') and re.match(r'^device://\d+$', src)

    def _is_file(self, src: str) -> bool:
        if not isinstance(src, str):
            return False
        if src.lower().startswith('file://'):
            return True
        # Treat absolute or existing paths as file
        try:
            return os.path.isabs(src) or os.path.exists(src)
        except Exception:
            return False

    def get_source(self, camera_id):
        return self.camera_sources.get(str(camera_id))

    def resolve_target(self, camera_id):
        """Return an OpenCV target based on source type.
        - device://N  -> returns int(N)
        - file path   -> returns path string
        - URL         -> returns direct URL (resolve YouTube)
        """
        camera_id = str(camera_id)
        if camera_id not in self.camera_sources:
            raise ValueError(f"Unknown camera ID: {camera_id}")
        src = self.camera_sources[camera_id]
        if self._is_device(src):
            try:
                return int(src.split('://', 1)[1])
            except Exception:
                return 0
        if self._is_file(src):
            # Normalize file://
            if src.lower().startswith('file://'):
                return src[7:]
            return src
        # URL
        return self._resolve_youtube_url(src) if self._is_youtube(src) else src

    def connect_camera(self, camera_id):
        """Resolve and register stream URL for a camera."""
        camera_id = str(camera_id)
        if camera_id not in self.camera_sources:
            raise ValueError(f"Unknown camera ID: {camera_id}")
        # For compatibility, store a 'url' even if it's a file/device; VideoCapture uses resolve_target
        src = self.camera_sources[camera_id]
        url = self._resolve_youtube_url(src) if self._is_youtube(src) else src
        if camera_id not in self.locks:
            self.locks[camera_id] = threading.Lock()
        with self.locks[camera_id]:
            self.connections[camera_id] = {"url": url, "status": "connected"}
        print(f"[CameraManager] Connected {camera_id} -> {url[:60]}...")
        return url

    def disconnect_camera(self, camera_id):
        """Mark camera as disconnected."""
        camera_id = str(camera_id)
        if camera_id not in self.locks:
            self.locks[camera_id] = threading.Lock()
        with self.locks[camera_id]:
            if camera_id in self.connections:
                self.connections[camera_id]["status"] = "disconnected"
        print(f"[CameraManager] Disconnected {camera_id}")

    def get_camera_status(self, camera_id):
        """Return connection status."""
        camera_id = str(camera_id)
        if camera_id not in self.locks:
            self.locks[camera_id] = threading.Lock()
        with self.locks[camera_id]:
            return self.connections.get(camera_id, {"status": "not connected"})

    # ---- Dynamic source management ----
    def update_sources(self, sources: dict):
        """Replace all sources with provided mapping of {str(id): url}."""
        self.camera_sources = {str(k): v for k, v in (sources or {}).items()}
        for k in list(self.locks.keys()):
            if k not in self.camera_sources:
                # keep lock but it may be cleaned up later
                pass
        for cam_id in self.camera_sources:
            if cam_id not in self.locks:
                self.locks[cam_id] = threading.Lock()

    def set_source(self, camera_id, url: str):
        camera_id = str(camera_id)
        self.camera_sources[camera_id] = url
        if camera_id not in self.locks:
            self.locks[camera_id] = threading.Lock()

    def remove_source(self, camera_id):
        camera_id = str(camera_id)
        self.camera_sources.pop(camera_id, None)
