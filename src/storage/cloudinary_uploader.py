# src/storage/cloudinary_uploader.py
"""
Cloudinary integration for SurveilX frame storage.

Usage:
    from src.storage.cloudinary_uploader import upload_frame, get_frame_url

    # Upload a saved local JPEG and get back a persistent CDN URL
    url = upload_frame(local_path="data/processed/cam1_20260507_220000_42.jpg",
                       public_id="surveilx/cam1_20260507_220000_42")
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configure Cloudinary from env ─────────────────────────────────────────────
_CLOUD_NAME  = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
_API_KEY     = os.getenv("CLOUDINARY_API_KEY",    "").strip()
_API_SECRET  = os.getenv("CLOUDINARY_API_SECRET", "").strip()

_enabled = bool(_CLOUD_NAME and _API_KEY and _API_SECRET)

if _enabled:
    import cloudinary
    import cloudinary.uploader
    cloudinary.config(
        cloud_name=_CLOUD_NAME,
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        secure=True,
    )
    logger.info(f"Cloudinary configured: cloud={_CLOUD_NAME}")
else:
    logger.warning("Cloudinary not configured — frames will be local only. "
                   "Set CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET in .env")


def upload_frame(local_path: str, public_id: Optional[str] = None) -> Optional[str]:
    """Upload a local JPEG frame to Cloudinary.

    Args:
        local_path: Absolute or relative path to the saved .jpg file.
        public_id:  Cloudinary asset identifier (defaults to filename stem).

    Returns:
        The HTTPS CDN URL of the uploaded image, or None on failure.
    """
    if not _enabled:
        return None

    if not os.path.isfile(local_path):
        logger.warning(f"Cloudinary upload skipped — file not found: {local_path}")
        return None

    if public_id is None:
        stem = os.path.splitext(os.path.basename(local_path))[0]
        public_id = f"surveilx/{stem}"

    try:
        import cloudinary.uploader as _up
        result = _up.upload(
            local_path,
            public_id=public_id,
            folder="",           # public_id already contains the folder prefix
            overwrite=True,
            resource_type="image",
            format="jpg",
            quality="auto",      # Cloudinary auto-optimises quality
        )
        url: str = result.get("secure_url", "")
        logger.debug(f"Cloudinary uploaded {os.path.basename(local_path)} → {url}")
        return url
    except Exception as e:
        logger.warning(f"Cloudinary upload failed for {local_path}: {e}")
        return None


def upload_frame_bytes(
    image_bytes: bytes,
    public_id: Optional[str] = None,
) -> Optional[str]:
    """Upload a JPEG frame directly from memory to Cloudinary (no local file needed).

    Args:
        image_bytes: Raw JPEG bytes.
        public_id:   Cloudinary asset identifier.

    Returns:
        The HTTPS CDN URL, or None on failure.
    """
    if not _enabled or not image_bytes:
        return None
    try:
        import io as _io
        import cloudinary.uploader as _up
        result = _up.upload(
            _io.BytesIO(image_bytes),
            public_id=public_id or "surveilx/frame",
            overwrite=True,
            resource_type="image",
            format="jpg",
            quality="auto",
        )
        return result.get("secure_url", "")
    except Exception as e:
        logger.warning(f"Cloudinary in-memory upload failed: {e}")
        return None


def upload_video_bytes(
    video_bytes: bytes,
    public_id: Optional[str] = None,
) -> Optional[str]:
    """Upload an MP4 clip directly from memory to Cloudinary.

    Returns:
        The HTTPS CDN URL, or None on failure.
    """
    if not _enabled or not video_bytes:
        return None
    try:
        import io as _io
        import cloudinary.uploader as _up
        result = _up.upload(
            _io.BytesIO(video_bytes),
            public_id=public_id or "surveilx/clip",
            overwrite=True,
            resource_type="video",
            format="mp4",
        )
        return result.get("secure_url", "")
    except Exception as e:
        logger.warning(f"Cloudinary video upload failed: {e}")
        return None

def is_enabled() -> bool:
    """Return True if Cloudinary is configured and ready."""
    return _enabled

def delete_asset(public_id: str) -> bool:
    """Delete an asset from Cloudinary.
    
    Args:
        public_id: Cloudinary asset identifier.
        
    Returns:
        True if successfully deleted or not found, False on error.
    """
    if not _enabled or not public_id:
        return False
    try:
        import cloudinary.uploader as _up
        # Try both image and video resource types if we don't know which it is
        try:
            res = _up.destroy(public_id, resource_type="image")
            if res.get("result") == "ok": return True
        except Exception:
            pass
            
        try:
            res = _up.destroy(public_id, resource_type="video")
            if res.get("result") == "ok": return True
        except Exception:
            pass
            
        return False
    except Exception as e:
        logger.warning(f"Cloudinary delete failed for {public_id}: {e}")
        return False
