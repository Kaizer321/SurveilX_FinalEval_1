# ---------------- Authentication (simple in-memory) ----------------
from typing import Optional, Dict, Set, Any
from fastapi import Request, Response, Depends  # early import for type usage below
from fastapi import FastAPI, HTTPException
import secrets

SESSIONS: Dict[str, Dict[str, str]] = {}

app = FastAPI(title="SurveilX Web")

def extract_token(request: Request) -> Optional[str]:
    # 1) Authorization: Bearer <token>
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    # 2) Cookie 'auth'
    token = request.cookies.get("auth")
    if token:
        return token
    # 3) Query param 'token' (useful for EventSource which can't set headers)
    q = request.query_params.get("token")
    if q:
        return q
    return None

def require_any_role(request: Request) -> str:
    token = extract_token(request)
    if not token or token not in SESSIONS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return SESSIONS[token]["role"]

def require_admin(request: Request) -> str:
    role = require_any_role(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return role

@app.post("/auth/login")
async def auth_login(payload: Dict[str, str], response: Response):
    username = (payload.get("username") or "").strip()
    password = (payload.get("password") or "").strip()
    expected_role = (payload.get("role") or "").strip()  # optional, used to force page-specific login
    # Fetch user from DB
    try:
        user = db_manager.get_user_by_username(username)
    except Exception:
        user = None
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Verify password
    try:
        ok = db_manager._pwd.verify(password, user.password_hash)
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Enforce role-specific login page if client sent an expected role
    if expected_role and user.role != expected_role:
        raise HTTPException(status_code=403, detail="Role mismatch for this login page")
    role = user.role
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"username": username, "role": role}
    # Also set HttpOnly cookie for convenience
    response.set_cookie(key="auth", value=token, httponly=True, secure=False, samesite="lax")
    return {"token": token, "role": role}

@app.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = extract_token(request)
    if token and token in SESSIONS:
        SESSIONS.pop(token, None)
    response.delete_cookie("auth")
    return {"ok": True}

@app.get("/auth/logout")
async def auth_logout_get(request: Request):
    token = extract_token(request)
    if token and token in SESSIONS:
        SESSIONS.pop(token, None)
    resp = RedirectResponse(url="/static/login-user.html", status_code=302)
    resp.delete_cookie("auth")
    return resp

@app.get("/auth/me")
async def auth_me(request: Request):
    token = extract_token(request)
    if token and token in SESSIONS:
        return {"username": SESSIONS[token]["username"], "role": SESSIONS[token]["role"]}
    raise HTTPException(status_code=401, detail="Unauthorized")
# module1/app.py
import asyncio
import logging
import os
import time
from typing import Dict, List
from datetime import datetime, timedelta

import cv2
import time
import shutil
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import numpy as np
import io
import time
import pathlib
try:
    import psutil  # optional
except Exception:
    psutil = None

from config.settings import settings
from src.video_capture.camera_manager import CameraManager
from src.video_capture.video_capture import VideoCapture
from src.metadata.db_manager import DatabaseManager
from src.metadata.extractor import MetadataExtractor
from src.vector_store import chroma_store
from src.vector_store.clip_embedder import embed_image_bgr
from src.preprocessing.video_preprocessor import VideoPreprocessor
from src.detection.violence_detector import ViolenceDetector


# Camera infrastructure shared by endpoints
cam_manager = CameraManager(settings.CAMERA_SOURCES)
video_capture = VideoCapture(cam_manager)
# Background embedding pipeline state
db_manager = DatabaseManager()
extractors: Dict[str, MetadataExtractor] = {}
embed_tasks: Dict[str, asyncio.Task] = {}
BACKGROUND_TASKS: Set[asyncio.Task] = set()
# Per-camera embed FPS (frames per second to store/embed). 0 disables storage.
CAM_EMBED_FPS: Dict[str, float] = {}
VIEWERS: Dict[str, int] = {}
preprocessor = VideoPreprocessor(target_resolution=(320, 200), target_fps=10)
# Violence detector (pose + CNN/TCN)
detector = ViolenceDetector(
    checkpoint_path=settings.VIOLENCE_CKPT_PATH,
    pose_model_path=settings.POSE_MODEL_PATH,
)
# Latest detection per camera for the dashboard
DETECTIONS: Dict[str, Dict[str, object]] = {}
# Toggle for drawing keypoints on streamed frames
SHOW_KEYPOINTS: bool = False

# In-memory disabled users registry
DISABLED_USERS: Set[str] = set()

# Simple log broadcaster
class LogBroadcaster(logging.Handler):
    def __init__(self):
        super().__init__()
        self.queues: List[asyncio.Queue] = []

    def add_listener(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.queues.append(q)
        return q

    def remove_listener(self, q: asyncio.Queue):
        try:
            self.queues.remove(q)
        except ValueError:
            pass

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        for q in list(self.queues):
            # put_nowait; ignore full queues
            try:
                q.put_nowait(msg)
            except Exception:
                pass

broadcaster = LogBroadcaster()
formatter = logging.Formatter("[%(levelname)s] %(asctime)s %(name)s: %(message)s")
broadcaster.setFormatter(formatter)
class GuiLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        msg = record.getMessage()
        # Only show our app's 'frame <file> saved' logs in GUI
        if name.startswith("web") and msg.startswith("frame "):
            return True
        return False

        
broadcaster.addFilter(GuiLogFilter())
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Ensure terminal stays mostly quiet (WARNING+) for general logs
_console_warn = logging.StreamHandler()
_console_warn.setLevel(logging.WARNING)
_console_warn.setFormatter(formatter)
root_logger.addHandler(_console_warn)

# Add an INFO console handler only for uvicorn.* so 'running on ...' shows
class _UvicornOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Allow select uvicorn status lines; hide 'Uvicorn running on' and all access logs
        if not record.name.startswith("uvicorn.error"):
            return False
        m = record.getMessage()
        return (
            ("Started server process" in m)
            or ("Application startup complete" in m)
        )

_console_uvicorn_info = logging.StreamHandler()
_console_uvicorn_info.setLevel(logging.INFO)
_console_uvicorn_info.setFormatter(formatter)
_console_uvicorn_info.addFilter(_UvicornOnly())
root_logger.addHandler(_console_uvicorn_info)

# Module logger for web app
logger = logging.getLogger("web")
logger.setLevel(logging.INFO)
# Send to GUI only; keep out of terminal
logger.addHandler(broadcaster)
logger.propagate = False

# Tame noisy third-party loggers# Allow uvicorn logs to propagate so GUI can see them
for ln in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    lg = logging.getLogger(ln)
    lg.propagate = True

for noisy in [
    "asyncio",
    "httpx",
    "sqlalchemy.engine",
]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Mount static web folder
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if not os.path.exists(WEB_DIR):
    os.makedirs(WEB_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
"""
Expose processed frames to the UI for thumbnails or previews
"""
try:
    from config.settings import settings as _st
    if os.path.isdir(_st.PROCESSED_DIR):
        app.mount("/processed", StaticFiles(directory=_st.PROCESSED_DIR), name="processed")
except Exception:
    pass

def _refresh_cameras_from_db():
    """Load cameras from DB, update CameraManager sources, and align running capture/tasks."""
    try:
        cams = db_manager.list_cameras()
    except Exception:
        cams = []
    sources = {str(c.id): c.source_url for c in cams}
    cam_manager.update_sources(sources)
    # update embed fps map
    for c in cams:
        try:
            CAM_EMBED_FPS[str(c.id)] = float(getattr(c, 'embed_fps', 1) or 1)
        except Exception:
            CAM_EMBED_FPS[str(c.id)] = 1.0
    # Prewarm: auto-start captures for all enabled cameras so the dashboard loads fast
    active_ids = set(str(c.id) for c in cams if getattr(c, 'enabled', True))
    for cid in sorted(active_ids):
        try:
            if not video_capture.running.get(cid):
                video_capture.start_capture(cid)
                logger.info(f"Started camera {cid} (prewarm)")
            if cid not in extractors:
                extractors[cid] = MetadataExtractor(cid)
            if cid not in embed_tasks:
                embed_tasks[cid] = asyncio.create_task(capture_worker(cid))
        except Exception:
            logger.warning(f"Failed to start camera {cid}")
        # embeddings remain lazy; do not create embed_tasks here
    # Stop captures for cameras removed from DB
    existing_ids = set(str(c.id) for c in cams)
    for cid, running in list(video_capture.running.items()):
        if running and cid not in existing_ids:
            try:
                video_capture.stop_capture(cid)
            except Exception:
                pass
            if cid in embed_tasks:
                try:
                    embed_tasks[cid].cancel()
                except Exception:
                    pass
                embed_tasks.pop(cid, None)
            extractors.pop(cid, None)

@app.on_event("startup")
async def startup_event():
    # Seed default users if they don't exist
    try:
        db_manager.ensure_default_users()
    except Exception:
        pass
    # Initialize cameras from DB
    _refresh_cameras_from_db()

@app.on_event("shutdown")
async def shutdown_event():
    # Stop all cameras
    for cid in cam_manager.discover_cameras():
        try:
            video_capture.stop_capture(cid)
            logger.info(f"Stopped camera {cid}")
        except Exception:
            pass
    # Cancel workers
    for cid, task in list(embed_tasks.items()):
        try:
            task.cancel()
        except Exception:
            pass
    embed_tasks.clear()

async def capture_worker(camera_id: str):
    """Per-camera worker that processes ~10 FPS, saves every 60th frame,
    writes structured metadata (SQL) and upserts embedding+metadata into Chroma.
    """
    frame_count = 0
    last_tick = 0.0
    last_store_ts = 0.0
    try:
        task = asyncio.current_task()
        if task:
            BACKGROUND_TASKS.add(task)
    except Exception:
        pass

    if camera_id not in extractors:
        extractors[camera_id] = MetadataExtractor(camera_id)
    while True:
        try:
            now = time.time()
            # throttle ~10 Hz
            if (now - last_tick) < 0.10:
                await asyncio.sleep(0.01)
                continue
            frame = video_capture.get_frame(camera_id)
            last_tick = now
            if frame is None:
                await asyncio.sleep(0.01)
                continue
            # Apply preprocessing for persistence and embeddings (grayscale+normalize, 320x200)
            # Apply preprocessing
            processed = preprocessor.process_frame(frame)
            detection = {}
            try:
                # Offload model inference
                loop = asyncio.get_running_loop()
                # Correct call matching signature: predict(camera_id, frame_bgr, ...)
                detection = await loop.run_in_executor(
                    None, 
                    lambda: detector.predict(camera_id, frame_bgr=processed, show_keypoints=SHOW_KEYPOINTS)
                )
            except Exception:
                 detection = {}
            
            # cache latest detection for UI
            try:
                overlay_jpeg = None
                if SHOW_KEYPOINTS:
                    ov = detection.get("overlay_frame")
                    if ov is not None:
                        ok, buf = cv2.imencode(".jpg", ov)
                        if ok:
                            overlay_jpeg = buf.tobytes()
                DETECTIONS[str(camera_id)] = {
                    "label": detection.get("label"),
                    "score": detection.get("score"),
                    "class_probs": detection.get("class_probs"),
                    "ts": datetime.utcnow().isoformat(),
                    "overlay_jpeg": overlay_jpeg,
                    "is_alert": detection.get("is_alert", False),
                    "keypoints": detection.get("keypoints"),
                }
            except Exception:
                pass
            # Time-based sampling using per-camera embed_fps
            fps = float(CAM_EMBED_FPS.get(camera_id, 1.0) or 0)
            do_store = False
            if fps > 0:
                interval = 1.0 / max(0.1, fps)
                if (now - last_store_ts) >= interval:
                    do_store = True
            if do_store:
                ts = datetime.utcnow()
                ts_str = ts.strftime('%Y%m%d_%H%M%S')
                filename = f"{camera_id}_{ts_str}_{frame_count}.jpg"
                out_path = os.path.join(settings.PROCESSED_DIR, filename)
                # Canonical ID used for both PostgreSQL and Chroma
                chroma_id = f"{camera_id}:{ts_str}:{frame_count}"
                try:
                    # Offload file write
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, cv2.imwrite, out_path, frame)
                    logger.info(f"frame {filename} saved")
                except Exception as e:
                    logger.exception(f"Failed to write frame for {camera_id}: {e}")
                    await asyncio.sleep(0)
                # Extract structured metadata
                try:
                    md_extra = {"frame_index": frame_count}
                    if detection:
                        md_extra.update({
                            "violence_label": detection.get("label"),
                            "violence_score": detection.get("score"),
                            "class_probs": detection.get("class_probs"),
                        })
                    md = extractors[camera_id].extract(processed, extra=md_extra)
                    
                    pk_val = None
                    try:
                        pk_val = int(camera_id)
                    except ValueError:
                        pass
                    
                    loc = md.get("camera_location") or settings.CAMERA_LOCATIONS.get(camera_id)
                    
                    # Offload DB inserts
                    def _db_ops():
                        vs = db_manager.insert_video_stream(camera_id=camera_id, camera_pk=pk_val)
                        db_manager.insert_video_metadata(
                            frame_id=chroma_id,
                            timestamp=md["timestamp"],
                            camera_location=loc,
                            resolution=md["resolution"],
                            metadata_json={
                                **(md.get("metadata_json") or {}),
                                "file_path": out_path,
                                "frame_index": frame_count,
                            },
                            violence_label=detection.get("label") if detection else None,
                            violence_score=detection.get("score") if detection else None,
                            detections=detection.get("class_probs") if detection else {},
                            video_stream_id=vs.id,
                            camera_pk=pk_val,
                            embedding={"chroma_id": chroma_id}
                        )
                    await loop.run_in_executor(None, _db_ops)

                except Exception:
                    # Log concise message without traceback/SQL
                    logger.warning(f"DB insert failed for {camera_id}")
                # Compute embedding and upsert to Chroma
                try:
                    chroma_meta = {
                        "camera_id": camera_id,
                        "camera_location": settings.CAMERA_LOCATIONS.get(camera_id, camera_id),
                        "timestamp_iso": ts.isoformat(),
                        "resolution": md.get("resolution") if isinstance(md, dict) else None,
                        "frame_index": frame_count,
                        "file_path": out_path,
                        "violence_label": detection.get("label") if detection else None,
                        "violence_score": detection.get("score") if detection else None,
                        "class_probs": detection.get("class_probs") if detection else None,
                    }
                    embedding = embed_image_bgr(processed)
                    
                    # Offload Chroma upsert
                    await loop.run_in_executor(
                        None, 
                        lambda: chroma_store.upsert_frame(
                            _id=chroma_id,
                            metadata=chroma_meta,
                            document=f"Frame {frame_count} from {camera_id} at {ts_str}",
                            embedding=embedding,
                        )
                    )
                    logger.info(f"[embed] Stored {filename} -> Chroma id={chroma_id}")
                    last_store_ts = now
                except Exception:
                    # Log concise message without traceback
                    logger.warning(f"Chroma upsert failed for {camera_id}")

            frame_count += 1
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            break
        except Exception:
            # Avoid verbose tracebacks
            logger.warning(f"Worker error for {camera_id}")
            await asyncio.sleep(0.05)

    # Cleanup background task tracking
    try:
        task = asyncio.current_task()
        if task and task in BACKGROUND_TASKS:
            BACKGROUND_TASKS.remove(task)
    except Exception:
        pass

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Require authentication; if missing, go to login page
    tok = extract_token(request)
    if not tok or tok not in SESSIONS:
        # redirect to static login page
        return RedirectResponse(url="/static/login-user.html", status_code=302)
    try:
        with open(os.path.join(WEB_DIR, "index.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h3>UI not found</h3>")

@app.get("/cameras")
async def list_cameras():
    try:
        cams = db_manager.list_cameras(only_enabled=True)
        out = [{"id": str(c.id), "name": c.name or str(c.id)} for c in cams]
        # ensure workers running so detections are available
        for c in cams:
            cid = str(c.id)
            if not video_capture.running.get(cid):
                try:
                    video_capture.start_capture(cid)
                except Exception:
                    pass
            if cid not in extractors:
                extractors[cid] = MetadataExtractor(cid)
            if cid not in embed_tasks:
                embed_tasks[cid] = asyncio.create_task(capture_worker(cid))
    except Exception:
        out = []
    return JSONResponse({"cameras": out})

@app.get("/stream/{camera_id}")
async def stream_camera(camera_id: str):
    # Accept numeric ID as string
    try:
        cams = {str(c.id): c for c in db_manager.list_cameras(only_enabled=True)}
    except Exception:
        cams = {}
    if camera_id not in cams:
        raise HTTPException(status_code=404, detail="Unknown camera")

    boundary = "frame"

    # Ensure capture (and embedding worker) lazily start on first viewer
    cid = str(camera_id)
    if not video_capture.running.get(cid):
        try:
            video_capture.start_capture(cid)
            logger.info(f"Started camera {cid} (lazy)")
        except Exception:
            logger.warning(f"Failed to start camera {cid}")
    if cid not in extractors:
        extractors[cid] = MetadataExtractor(cid)
    if cid not in embed_tasks:
        embed_tasks[cid] = asyncio.create_task(capture_worker(cid))

    async def frame_generator():
        VIEWERS[cid] = VIEWERS.get(cid, 0) + 1
        while True:
            frame = video_capture.get_frame(camera_id)
            if frame is None:
                await asyncio.sleep(0.03)
                continue
            # If keypoints overlay is enabled and available, draw on frame
            if SHOW_KEYPOINTS:
                try:
                    det = DETECTIONS.get(cid) or {}
                    kps = det.get("keypoints")
                    if kps:
                        h, w = frame.shape[:2]
                        # Preprocessor uses 320x200
                        scale_x = w / 320.0
                        scale_y = h / 200.0
                        
                        skeleton = [
                            (5, 7), (7, 9), (6, 8), (8, 10),
                            (11, 13), (13, 15), (12, 14), (14, 16),
                            (5, 6), (11, 12)
                        ]

                        for person in kps:
                            xy = person["xy"]
                            conf = person["conf"]
                            
                            # Draw Skeleton
                            for pt1_idx, pt2_idx in skeleton:
                                if pt1_idx < len(xy) and pt2_idx < len(xy):
                                    if conf[pt1_idx] > 0.3 and conf[pt2_idx] > 0.3:
                                        x1, y1 = xy[pt1_idx]
                                        x2, y2 = xy[pt2_idx]
                                        pt1 = (int(x1 * scale_x), int(y1 * scale_y))
                                        pt2 = (int(x2 * scale_x), int(y2 * scale_y))
                                        cv2.line(frame, pt1, pt2, (0, 255, 255), 2)
                            
                            # Draw Points
                            for i, (x, y) in enumerate(xy):
                                 if conf[i] > 0.3:
                                     cx, cy = int(x * scale_x), int(y * scale_y)
                                     cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
                    else:
                        # Fallback to overlay_jpeg (low res) if high res kps unavailable
                        buf = det.get("overlay_jpeg")
                        if buf:
                            np_arr = np.frombuffer(buf, dtype=np.uint8)
                            ov = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                            if ov is not None:
                                frame = ov
                except Exception:
                    pass
            # Overlay timestamp and camera location on the frame
            try:
                overlay = frame.copy()
                h, w = frame.shape[:2]
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                location = settings.CAMERA_LOCATIONS.get(camera_id, camera_id)
                line1 = f"{location}"
                line2 = f"{ts}"
                # Box background
                box_w = min(w, 420)
                box_h = 50
                cv2.rectangle(overlay, (10, 10), (10 + box_w, 10 + box_h), (0, 0, 0), thickness=-1)
                # Blend for translucency
                alpha = 0.4
                frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
                # Text
                cv2.putText(frame, line1, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2, cv2.LINE_AA)
                cv2.putText(frame, line2, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2, cv2.LINE_AA)
            except Exception:
                pass
            ok, buf = cv2.imencode('.jpg', frame)
            if not ok:
                await asyncio.sleep(0.01)
                continue
            jpg_bytes = buf.tobytes()
            yield (
                b"--" + boundary.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpg_bytes)).encode() + b"\r\n\r\n"
                + jpg_bytes + b"\r\n"
            )
            await asyncio.sleep(0.03)

    async def stream_with_teardown():
        try:
            async for chunk in frame_generator():
                yield chunk
        finally:
            # Decrement viewer count and stop capture if no viewers remain
            VIEWERS[cid] = max(0, VIEWERS.get(cid, 1) - 1)
            if VIEWERS.get(cid, 0) == 0:
                try:
                    if video_capture.running.get(cid):
                        video_capture.stop_capture(cid)
                except Exception:
                    pass

    return StreamingResponse(stream_with_teardown(), media_type=f"multipart/x-mixed-replace; boundary={boundary}")

@app.get("/logs")
async def stream_logs(role: str = Depends(require_admin)):
    q = broadcaster.add_listener()

    async def event_stream():
        try:
            while True:
                msg = await q.get()
                data = f"data: {msg}\n\n"
                yield data.encode()
        except asyncio.CancelledError:
            pass
        finally:
            broadcaster.remove_listener(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# -------- Admin: Users management --------
@app.get("/admin/users")
async def admin_list_users(role: str = Depends(require_admin)):
    sess = db_manager.get_session()
    try:
        from src.metadata.models import AuthUser
        users = sess.query(AuthUser).all()
        out = []
        for u in users:
            out.append({
                "username": u.username,
                "role": u.role,
                "disabled": u.username in DISABLED_USERS,
                "created_at": getattr(u, "created_at", None)
            })
        return {"users": out}
    finally:
        sess.close()

@app.post("/admin/users")
async def admin_create_user(payload: dict[str, str], role: str = Depends(require_admin)):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    urole = (payload.get("role") or "user").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")
    try:
        u = db_manager.create_user(username, password, role=urole)
        return {"ok": True, "user": {"username": u.username, "role": u.role}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/users/reset_password")
async def admin_reset_password(payload: Dict[str, str], role: str = Depends(require_admin)):
    username = (payload.get("username") or "").strip()
    new_password = payload.get("new_password") or ""
    if not username or not new_password:
        raise HTTPException(status_code=400, detail="username and new_password required")
    sess = db_manager.get_session()
    try:
        from src.metadata.models import AuthUser
        u = sess.query(AuthUser).filter(AuthUser.username == username).first()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        u.password_hash = db_manager._pwd.hash(new_password)
        sess.commit()
        return {"ok": True}
    finally:
        sess.close()

@app.post("/admin/users/disable")
async def admin_disable_user(payload: Dict[str, str], role: str = Depends(require_admin)):
    username = (payload.get("username") or "").strip()
    disabled = bool(payload.get("disabled", True))
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    if disabled:
        DISABLED_USERS.add(username)
        # force logout any sessions
        for tok, info in list(SESSIONS.items()):
            if info.get("username") == username:
                SESSIONS.pop(tok, None)
    else:
        DISABLED_USERS.discard(username)
    return {"ok": True, "disabled": username in DISABLED_USERS}

@app.post("/admin/users/force_logout")
async def admin_force_logout(payload: Dict[str, str], role: str = Depends(require_admin)):
    username = (payload.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    count = 0
    for tok, info in list(SESSIONS.items()):
        if info.get("username") == username:
            SESSIONS.pop(tok, None)
            count += 1
    return {"ok": True, "sessions_ended": count}

# -------- Admin: Analytics summary --------
@app.get("/admin/analytics/summary")
async def admin_analytics_summary(role: str = Depends(require_admin)):
    from src.metadata.models import VideoMetadata, VideoStream
    sess = db_manager.get_session()
    try:
        total_streams = sess.query(VideoStream).count()
        since = datetime.utcnow().timestamp() - 24*3600
        # count last 24h by timestamp if available
        recent = sess.query(VideoMetadata).count()
        # use DB cameras if available
        try:
            total_cameras = len(db_manager.list_cameras())
        except Exception:
            total_cameras = len(settings.CAMERA_SOURCES)
        return {
            "total_cameras": total_cameras,
            "streams": total_streams,
            "events_24h": recent,
            "active_users": max(1, len({v.get("username") for v in SESSIONS.values()})),
            "storage_usage": None,
            "critical_alerts": 0,
        }
    finally:
        sess.close()

# -------- Admin: System health --------
@app.get("/admin/health")
async def admin_health(role: str = Depends(require_admin)):
    if psutil is None:
        return {"cpu": None, "ram": None, "disk": None, "net": None}
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()._asdict()
        disk = psutil.disk_usage("/")._asdict()
        net = psutil.net_io_counters()._asdict()
        return {"cpu": cpu, "ram": mem, "disk": disk, "net": net}
    except Exception:
        return {"cpu": None, "ram": None, "disk": None, "net": None}

# -------- Admin: Cameras CRUD --------
@app.get("/admin/cameras")
async def admin_list_cameras(role: str = Depends(require_admin)):
    cams = db_manager.list_cameras()
    return {"cameras": [
        {"id": c.id, "name": c.name, "source_url": c.source_url, "zone": c.zone, "enabled": c.enabled}
        for c in cams
    ]}

@app.post("/admin/cameras")
async def admin_create_camera(payload: Dict, role: str = Depends(require_admin)):
    name = (payload.get("name") or "").strip()
    source_url = (payload.get("source_url") or "").strip()
    zone = (payload.get("zone") or "").strip() or None
    enabled = bool(payload.get("enabled", True))
    embed_fps = payload.get("embed_fps")
    if not name or not source_url:
        raise HTTPException(status_code=400, detail="name and source_url required")
    cam = db_manager.create_camera(name=name, source_url=source_url, zone=zone, enabled=enabled, embed_fps=embed_fps)
    # reflect source and embed_fps in runtime maps; start capture if enabled (embeddings lazy)
    try:
        cam_manager.set_source(cam.id, cam.source_url)
        try:
            CAM_EMBED_FPS[str(cam.id)] = float(getattr(cam, 'embed_fps', 1) or 1)
        except Exception:
            CAM_EMBED_FPS[str(cam.id)] = 1.0
        if cam.enabled and not video_capture.running.get(str(cam.id)):
            try:
                video_capture.start_capture(str(cam.id))
                logger.info(f"Started camera {cam.id} (create)")
            except Exception:
                logger.warning(f"Failed to start camera {cam.id}")
    except Exception:
        pass
    return {"ok": True, "camera": {"id": cam.id, "name": cam.name, "source_url": cam.source_url, "zone": cam.zone, "enabled": cam.enabled}}

@app.patch("/admin/cameras/{camera_id}")
async def admin_update_camera(camera_id: int, payload: Dict, role: str = Depends(require_admin)):
    cid = str(camera_id)
    # Track old source to detect changes
    old_source = cam_manager.get_source(cid)

    cam = db_manager.update_camera(camera_id,
                                   name=payload.get("name"),
                                   source_url=payload.get("source_url"),
                                   zone=payload.get("zone"),
                                   enabled=payload.get("enabled"),
                                   embed_fps=payload.get("embed_fps"))
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    
    # Update in-memory managers
    try:
        cam_manager.set_source(cid, cam.source_url)
        try:
            CAM_EMBED_FPS[cid] = float(getattr(cam, 'embed_fps', 1) or 1)
        except Exception:
            CAM_EMBED_FPS[cid] = 1.0

        # Runtime state reflection
        is_running = video_capture.running.get(cid)
        source_changed = (old_source != cam.source_url)

        if cam.enabled:
            # If not running, start it
            if not is_running:
                video_capture.start_capture(cid)
                logger.info(f"Started camera {cid} (update/enable)")
            # If running but source changed, restart it
            elif source_changed:
                video_capture.stop_capture(cid)
                video_capture.start_capture(cid)
                logger.info(f"Restarted camera {cid} (source changed)")

        else:
            # If disabled and currently running, stop it
            if is_running:
                video_capture.stop_capture(cid)
                logger.info(f"Stopped camera {cid} (update/disable)")
            # Cleanup background tasks if fully disabled
            if cid in embed_tasks:
                try:
                    embed_tasks[cid].cancel()
                except Exception:
                    pass
                embed_tasks.pop(cid, None)
                extractors.pop(cid, None)
                
    except Exception as e:
        logger.warning(f"Runtime update failed for camera {cid}: {e}")
    
    return {"ok": True}

@app.delete("/admin/cameras/{camera_id}")
async def admin_delete_camera(camera_id: int, role: str = Depends(require_admin)):
    ok = db_manager.delete_camera(camera_id)
    if not ok:
        raise HTTPException(status_code=404, detail="camera not found")
    # reflect in runtime
    try:
        cid = str(camera_id)
        if video_capture.running.get(cid):
            video_capture.stop_capture(cid)
        if cid in embed_tasks:
            try:
                embed_tasks[cid].cancel()
            except Exception:
                pass
            embed_tasks.pop(cid, None)
            extractors.pop(cid, None)
        cam_manager.remove_source(camera_id)
    except Exception:
        pass
    return {"ok": True}

@app.post("/admin/cameras/{camera_id}/test")
async def admin_test_camera(camera_id: int, role: str = Depends(require_admin)):
    # Lightweight placeholder test
    return {"ok": True}

@app.get("/api/detections")
async def api_detections(role: str = Depends(require_any_role)):
    """Return latest detection per camera for dashboard."""
    return {"detections": {k: {kk: vv for kk, vv in v.items() if kk != "overlay_jpeg"} for k, v in DETECTIONS.items()},
            "show_keypoints": SHOW_KEYPOINTS}

@app.post("/api/detections/keypoints")
async def api_toggle_keypoints(payload: Dict[str, Any], role: str = Depends(require_any_role)):
    """Toggle drawing keypoints on streamed frames."""
    global SHOW_KEYPOINTS
    enabled = bool(payload.get("enabled", False))
    SHOW_KEYPOINTS = enabled
    return {"show_keypoints": SHOW_KEYPOINTS}

# ---- Admin: Upload local video file for camera (store on server and return path) ----
@app.post("/admin/upload_video")
async def admin_upload_video(file: UploadFile = File(...), role: str = Depends(require_admin)):
    # Choose uploads directory relative to working dir
    uploads_dir = pathlib.Path("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize filename
    name = pathlib.Path(file.filename or "video.mp4").name
    dest = uploads_dir / name
    # If exists, make unique
    i = 1
    base = dest.stem
    suffix = dest.suffix
    while dest.exists():
        dest = uploads_dir / f"{base}_{i}{suffix}"
        i += 1
    data = await file.read()
    dest.write_bytes(data)
    # Return absolute path so backend can open file
    return {"path": str(dest.resolve())}

# ---- Admin: Probe available capture devices (indices) ----
@app.get("/admin/devices")
async def admin_list_devices(role: str = Depends(require_admin)):
    import cv2
    found = []
    seen = set()
    # On Windows try DirectShow and MSMF explicitly; then default
    backends = []
    try:
        backends.extend([cv2.CAP_DSHOW, cv2.CAP_MSMF])
    except Exception:
        pass
    backends.append(0)  # auto
    # Probe a wider range conservatively
    for i in range(0, 12):
        for be in backends:
            try:
                cap = cv2.VideoCapture(i, be) if be else cv2.VideoCapture(i)
                ok = cap.isOpened()
                # also try to read one frame to confirm it works
                if ok:
                    ret, _ = cap.read()
                    ok = ret or ok
                if ok and i not in seen:
                    seen.add(i)
                    found.append({"index": i, "name": f"Camera {i}"})
            except Exception:
                pass
            finally:
                try:
                    cap.release()
                except Exception:
                    pass
    return {"devices": found}

# -------- Admin: Delete user --------
@app.post("/admin/users/delete")
async def admin_delete_user(payload: Dict[str, str], role: str = Depends(require_admin)):
    username = (payload.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    sess = db_manager.get_session()
    try:
        from src.metadata.models import AuthUser
        u = sess.query(AuthUser).filter(AuthUser.username == username).first()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        sess.delete(u)
        sess.commit()
        # clean sessions too
        for tok, info in list(SESSIONS.items()):
            if info.get("username") == username:
                SESSIONS.pop(tok, None)
        return {"ok": True}
    finally:
        sess.close()

# -------- Events feed (any authenticated) --------
@app.get("/events/feed")
async def events_feed(limit: int = 20, role: str = Depends(require_any_role)):
    from src.metadata.models import VideoMetadata
    sess = db_manager.get_session()
    try:
        q = sess.query(VideoMetadata).order_by(VideoMetadata.id.desc()).limit(max(1, min(limit, 200)))
        out = []
        for vm in q:
            out.append({
                "id": vm.id,
                "frame_id": vm.frame_id,
                "timestamp": str(vm.timestamp),
                "camera_location": vm.camera_location,
                "resolution": vm.resolution,
                "violence_label": vm.violence_label,
                "violence_score": vm.violence_score,
            })
        return {"events": out}
    finally:
        sess.close()

# -------- Map cameras (any authenticated) --------
@app.get("/map/cameras")
async def map_cameras(role: str = Depends(require_any_role)):
    cams = []
    try:
        for c in db_manager.list_cameras(only_enabled=True):
            cams.append({"id": c.id, "name": c.name, "zone": c.zone})
    except Exception:
        # fallback to static
        cams = [
            {"id": cid, "name": settings.CAMERA_LOCATIONS.get(cid, cid), "zone": settings.CAMERA_LOCATIONS.get(cid, cid)}
            for cid in cam_manager.discover_cameras()
        ]
    return {"cameras": cams}

# -------- Embedding/Chroma stats endpoints --------
try:
    from src.vector_store.chroma_store import get_collection  # lazily import; optional dependency

    @app.get("/api/embeddings/stats")
    async def embeddings_stats(request: Request, role: str = Depends(require_any_role)):
        # Be resilient: if anything fails, return zeros instead of 500
        try:
            col = get_collection()
        except Exception as e:
            logger.warning(f"Chroma unavailable: {e}")
            return JSONResponse({"count": 0, "latest": {"ids": [], "metadatas": [], "documents": []}})

        count = 0
        try:
            count = col.count()
        except Exception as e:
            logger.warning(f"Chroma count failed: {e}")

        try:
            # Use a conservative include set compatible with 0.5.x
            latest = col.get(limit=5, include=["metadatas", "documents"])  # ids included in result keys
            return JSONResponse({
                "count": count,
                "latest": {
                    "ids": latest.get("ids", []),
                    "metadatas": latest.get("metadatas", []),
                    "documents": latest.get("documents", []),
                }
            })
        except Exception as e:
            logger.warning(f"Chroma get failed: {e}")
            return JSONResponse({"count": count, "latest": {"ids": [], "metadatas": [], "documents": []}})

    @app.get("/api/embeddings/similar")
    async def embeddings_similar(base_id: str, k: int = 8, role: str = Depends(require_any_role)):
        try:
            col = get_collection()
        except Exception as e:
            logger.warning(f"Chroma unavailable: {e}")
            return JSONResponse({"ids": [], "metadatas": [], "documents": [], "distances": []})

        # Fetch the base item's embedding
        try:
            base = col.get(ids=[base_id], include=["embeddings", "metadatas", "documents"])
            embs = base.get("embeddings")
            if not embs:
                return JSONResponse({"ids": [], "metadatas": [], "documents": [], "distances": []})
            emb = embs[0]
        except Exception as e:
            logger.warning(f"Chroma get base failed: {e}")
            return JSONResponse({"ids": [], "metadatas": [], "documents": [], "distances": []})

        # Query similar
        try:
            q = col.query(query_embeddings=[emb], n_results=max(1, min(k, 50)), include=["metadatas", "documents", "distances"])
            return JSONResponse({
                "ids": q.get("ids", [[]])[0] if isinstance(q.get("ids"), list) else q.get("ids", []),
                "metadatas": q.get("metadatas", [[]])[0] if isinstance(q.get("metadatas"), list) else q.get("metadatas", []),
                "documents": q.get("documents", [[]])[0] if isinstance(q.get("documents"), list) else q.get("documents", []),
                "distances": q.get("distances", [[]])[0] if isinstance(q.get("distances"), list) else q.get("distances", []),
            })
        except Exception as e:
            logger.warning(f"Chroma query failed: {e}")
            return JSONResponse({"ids": [], "metadatas": [], "documents": [], "distances": []})

    @app.post("/api/embeddings/search_image")
    async def embeddings_search_image(file: UploadFile = File(...), k: int = 12, role: str = Depends(require_any_role)):
        try:
            col = get_collection()
        except Exception as e:
            logger.warning(f"Chroma unavailable: {e}")
            return JSONResponse({"ids": [], "metadatas": [], "documents": [], "distances": []})

        try:
            raw = await file.read()
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            arr_rgb = np.array(img)
            arr_bgr = arr_rgb[:, :, ::-1]
            emb = embed_image_bgr(arr_bgr)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

        try:
            q = col.query(query_embeddings=[emb], n_results=max(1, min(k, 50)), include=["metadatas", "documents", "distances"])
            return JSONResponse({
                "ids": q.get("ids", [[]])[0] if isinstance(q.get("ids"), list) else q.get("ids", []),
                "metadatas": q.get("metadatas", [[]])[0] if isinstance(q.get("metadatas"), list) else q.get("metadatas", []),
                "documents": q.get("documents", [[]])[0] if isinstance(q.get("documents"), list) else q.get("documents", []),
                "distances": q.get("distances", [[]])[0] if isinstance(q.get("distances"), list) else q.get("distances", []),
            })
        except Exception as e:
            logger.warning(f"Chroma query failed: {e}")
            return JSONResponse({"ids": [], "metadatas": [], "documents": [], "distances": []})
except Exception:
    # Chroma not available; provide a stub endpoint
    @app.get("/api/embeddings/stats")
    async def embeddings_stats_stub():
        return JSONResponse({"count": 0, "latest": {"ids": [], "metadatas": [], "documents": []}})

# ---- System Stats Endpoints ----
@app.get("/api/stats/overview")
async def stats_overview(role: str = Depends(require_admin)):
    # Total cameras
    cams = db_manager.list_cameras()
    total_cameras = len(cams)
    
    # Active streams (in memory)
    active_streams = len(BACKGROUND_TASKS)
    
    # Events in last 24h
    since = datetime.utcnow() - timedelta(hours=24)
    events_24h = db_manager.count_events_since(since, exclude_label="Normal")
    
    # Active users (sessions)
    active_users = len(SESSIONS)
    
    # Storage usage (of the drive where PROCESSED_DIR resides)
    total, used, free = shutil.disk_usage(settings.PROCESSED_DIR)
    # convert to GB
    storage_gb = f"{used // (2**30)} / {total // (2**30)} GB"
    
    # Critical alerts (count detections with is_alert=True currently active)
    # We use DB count for last 24h to show meaningful history
    critical_alerts = db_manager.count_critical_events_since(since)
    
    # Detailed stats for charts
    chart_data = db_manager.get_events_stats(hours=24)
    
    return {
        "total_cameras": total_cameras,
        "active_streams": active_streams,
        "events_24h": events_24h,
        "active_users": active_users,
        "storage_usage": storage_gb,
        "critical_alerts": critical_alerts,
        "charts": chart_data
    }

@app.get("/api/stats/health")
async def stats_health(role: str = Depends(require_admin)):
    cpu = 0.0
    ram = 0.0
    disk = 0.0
    
    if psutil:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(str(settings.BASE_DIR)).percent
    else:
        # fallback for disk only
        total, used, free = shutil.disk_usage(settings.BASE_DIR)
        if total > 0:
            disk = round((used / total) * 100, 1)
            
    return {
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "network": "Online"
    }
