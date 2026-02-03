# Module 1 – Video Ingest, Processing, Metadata & Web Dashboard

This module captures live video from YouTube sources (as camera proxies), preprocesses frames, persists metadata to a database (configured via `SURVEILX_DB_URL`), and provides a web dashboard to view multiple streams with live logs and vector search stats via ChromaDB.

## Features

- Multi-camera capture via yt-dlp + OpenCV
- Frame preprocessing (standardize, resize, enhance)
- Metadata extraction and storage with SQLAlchemy
- Web dashboard (FastAPI) showing:
  - All camera streams (MJPEG)
  - Grid/Single view toggle, keyboard shortcuts 1–9
  - Focus dropdown, thumbnail strip in single view
  - Drag-and-drop reorder (persisted in localStorage)
  - Live logs with filters (levels, cameras, search), pause/clear/export

## Directory Structure

- `main.py` – CLI pipeline capturing and saving frames + metadata
- `app.py` – FastAPI web app (streams + dashboard + logs)
- `web/` – Static frontend for the dashboard
- `config/settings.py` – Configuration (camera sources/locations, storage, DB URL)
- `src/`
  - `video_capture/`
    - `camera_manager.py` – Resolve YouTube to direct stream URL via `yt_dlp`
    - `video_capture.py` – Threaded capture, per-camera frame buffers
  - `preprocessing/`
    - `video_preprocessor.py` – Resize, format normalize, quality enhancement
    - `processing_queue.py` – Worker threads for saving processed frames
  - `metadata/`
    - `models.py` – SQLAlchemy models
    - `db_manager.py` – Engine, sessions, CRUD helpers
    - `extractor.py` – Build per-frame metadata
- `requirements.txt` – Python dependencies

## Prerequisites

- Python 3.11 (recommended) on Windows
- Internet access (YouTube HLS manifests)
- VC++ Build Tools not required for listed deps (uses `psycopg2-binary`)

## Installation

From the project root folder:

```powershell
pip install -r requirements.txt
```

## Configuration

`config/settings.py` controls sources and destinations. Environment variables are loaded from `.env` (if present) using `python-dotenv`.

- `SURVEILX_DB_URL` (required): PostgreSQL connection string, e.g. `postgresql+psycopg2://user:pass@localhost:5432/dbname`
- `CHROMA_DIR` (optional): directory for ChromaDB persistence (defaults to `./chroma_db`)
- `LOG_LEVEL`, `DEBUG` (optional): logging verbosity
- `FRAME_RATE`, `MAX_WORKERS`, `MODEL_NAME` (optional): processing knobs
- `CAMERA_SOURCES`: map of camera_id → YouTube URL
- `CAMERA_LOCATIONS`: map of camera_id → friendly name
- `OUTPUT_DIR`, `PROCESSED_DIR`: storage locations (auto-created)

Example `.env`:

```dotenv
SURVEILX_DB_URL=postgresql+psycopg2://surveilx:StrongPassword!@localhost:5432/surveilx_db
CHROMA_DIR=./chroma_db
LOG_LEVEL=INFO
DEBUG=false
```

Set environment variables permanently on Windows PowerShell:

```powershell
setx SURVEILX_DB_URL "postgresql+psycopg2://surveilx:StrongPassword!@localhost:5432/surveilx_db"
```

Restart your terminal/IDE after setting environment variables.

## Running

### A) CLI mode (OpenCV windows)

```powershell
python main.py
```
- Starts capture for all configured cameras (now iterated in main loop)
- Displays a window per camera, press `q` to quit
- Every 60th frame: saves processed image to `data/processed/` and inserts metadata

### B) Web Dashboard (FastAPI)

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser at http://localhost:8000/

- Streams per camera as MJPEG
- Grid vs Single view toggle
- Focus dropdown (select a camera to maximize in Single view)
- Keyboard shortcuts 1–9 focus cameras
- Thumbnail strip appears in Single view; click thumbnails to switch focus
- Drag cards to reorder; order persists in localStorage
- Live logs with filters/search/pause/clear/export

Note: Do not run `main.py` and the web app at the same time (both control capture).

## Database

### PostgreSQL

1) Create DB and user (psql):
```powershell
psql -U postgres -c "CREATE ROLE surveilx WITH LOGIN PASSWORD 'StrongPassword!';"
psql -U postgres -c "CREATE DATABASE surveilx_db OWNER surveilx;"
```
2) Set environment variable (see Configuration) and restart terminal.
3) The app will auto-create tables via SQLAlchemy on first run.

### Schema (SQLAlchemy models)

- `video_streams`
  - `id`, `camera_id`, `created_at`, `status`
  - Relationship: `VideoStream.metadata_entries` → `video_metadata`
- `video_metadata`
  - `id`, `video_stream_id (FK)`, `frame_id` (unique), `timestamp`, `camera_location`, `resolution`,
  - Optional/future-friendly fields: `violence_label`, `violence_score`, `detections` (JSON), `embedding` (JSON list), `embedding_model`, `metadata_json`
  - Relationship: `VideoMetadata.video_stream`

## Vector Store (ChromaDB)

- Persistent client stored under `CHROMA_DIR` (default `./chroma_db`).
- Collection: `video_frames` with cosine space.
- Each saved frame (every 60th) can be upserted with metadata and CLIP embedding.
- API endpoints (if Chroma is available):
  - `GET /api/embeddings/stats` → `{ count, latest: { ids, metadatas, documents } }`
  - `GET /api/embeddings/similar?base_id=...&k=8` → nearest neighbors
  - `POST /api/embeddings/search_image?k=12` with an image file → similar frames

## Processing & Metadata

- Preprocessing (default): resize to 320×200, convert to grayscale, histogram equalization, light blur
- Metadata includes:
  - Timestamp (UTC), camera_id, camera_location
  - Resolution (from processed frame), FPS (best-effort via capture)
  - Codec/bitrate (placeholders; extend with ffprobe if needed)
  - `metadata_json`: arbitrary extra (e.g., `{"frame_index": 120}`)

## Web UI – Details

- Streams: `/stream/{camera_id}` (multipart/x-mixed-replace MJPEG)
- Cameras list: `/cameras` returns `[{ id, name }]`
- Logs (SSE): `/logs` – consumed by the dashboard
- UI behaviors:
  - Grid view shows all cameras; Single view focuses selected camera
  - Dropdown + keyboard shortcuts to switch focus
  - Thumbnail strip in Single view for quick switching
  - Drag-and-drop to reorder cards; stored in localStorage
  - Logs panel filters by level/camera/search; tail size; autoscroll; pause/clear/export

## Troubleshooting

- Startup error referencing `SURVEILX_DB_URL`:
  - Add it to `.env` or set it in your environment (see Configuration)
- "Failed to load cameras" in UI:
  - Check server is running and `/cameras` returns 200 JSON in browser
  - Hard refresh (Ctrl+F5) to clear cached JS
- No video / black frame:
  - Some YouTube streams throttle/rotate URLs; reloading may help
  - Ensure outbound HTTPS allowed by firewall/proxy
- OpenCV cannot open stream:
  - Update `yt-dlp`; adjust format selection in `CameraManager._resolve_youtube_url`
- Database errors:
  - Ensure `SURVEILX_DB_URL` is correct and DB is reachable
  - For Postgres, confirm user/database and privileges
- Windows display errors:
  - OpenCV windows require a desktop session; use the web dashboard instead

## Extending

- Replace YouTube with RTSP/RTMP sources (create appropriate resolver)
- Add object detection and store detections in `metadata_json`
- Use ffprobe for codec/bitrate/fps ground truth
- Move logs to structured JSON and enrich with `camera_id` fields server-side

## License

Academic/educational use. Add your preferred license terms here.

