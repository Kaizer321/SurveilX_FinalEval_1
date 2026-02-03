from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from .models import Base, VideoStream, VideoMetadata, AuthUser, Camera
from datetime import datetime, timedelta
from config.settings import settings
import logging
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_url=None):
        self.db_url = db_url or settings.DB_URL
        if not self.db_url:
            raise ValueError("Database URL not configured. Set SURVEILX_DB_URL in .env")
            
        logger.info(f"Connecting to database: {self._mask_password(self.db_url)}")
        
        self.engine = create_engine(
            self.db_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Enable connection health checks
            pool_recycle=3600,   # Recycle connections after 1 hour
        )
        
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        # Use pbkdf2_sha256 to avoid bcrypt backend and 72-char limitations
        self._pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
        self._create_tables()
        
    def _mask_password(self, db_url: str) -> str:
        """Mask password in database URL for logging"""
        if "@" in db_url:
            parts = db_url.split("@", 1)
            return f"{parts[0].split('//')[0]}//***:***@{parts[1]}"
        return db_url
        
    def _create_tables(self):
        """Create all tables if they don't exist"""
        try:
            Base.metadata.create_all(self.engine)
            logger.info("Database tables created/verified")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}")
            raise

    def get_session(self):
        """Get a new database session"""
        return self.Session()

    # ---------------- Users (AuthUser table) ----------------
    def get_user_by_username(self, username: str):
        session = self.get_session()
        try:
            return session.query(AuthUser).filter(AuthUser.username == username).first()
        finally:
            session.close()

    def create_user(self, username: str, password: str, role: str = "user"):
        session = self.get_session()
        try:
            existing = session.query(AuthUser).filter(AuthUser.username == username).first()
            if existing:
                return existing
            u = AuthUser(
                username=username,
                # pbkdf2_sha256 supports long passwords; still sanitize None
                password_hash=self._pwd.hash(password or ""),
                role=role,
            )
            session.add(u)
            session.commit()
            session.refresh(u)
            return u
        finally:
            session.close()

    def ensure_default_users(self):
        """Seed default users for demo or first run."""
        try:
            self.create_user("admin", "admin123", role="admin")
            self.create_user("user", "user123", role="user")
        except Exception as e:
            logger.warning(f"ensure_default_users error: {e}")

    def insert_video_stream(self, camera_id, status: str = "captured", camera_pk: int | None = None):
        session = self.get_session()
        try:
            vs = VideoStream(
                camera_id=camera_id,
                camera_pk=camera_pk,
                status=status,
            )
            session.add(vs)
            session.commit()
            session.refresh(vs)
            return vs
        finally:
            session.close()

    def insert_video_metadata(self, timestamp,
                              frame_id,
                              camera_location=None,
                              resolution=None,
                              violence_label=None,
                              violence_score=None,
                              detections=None,
                              embedding=None,
                              embedding_model=None,
                              metadata_json=None,
                              video_stream_id=None,
                              camera_pk=None):
        session = self.get_session()
        try:
            vm = VideoMetadata(
                video_stream_id=video_stream_id,
                frame_id=frame_id,
                timestamp=timestamp,
                camera_location=camera_location,
                resolution=resolution,
                violence_label=violence_label,
                violence_score=violence_score,
                detections=detections or {},
                embedding=embedding,
                embedding_model=embedding_model,
                metadata_json=metadata_json or {},
                camera_pk=camera_pk,
            )
            session.add(vm)
            session.commit()
            session.refresh(vm)
            return vm
        finally:
            session.close()

    def query_metadata(self, **filters):
        session = self.get_session()
        try:
            q = session.query(VideoMetadata)
            for k, v in filters.items():
                if hasattr(VideoMetadata, k):
                    q = q.filter(getattr(VideoMetadata, k) == v)
            return q.all()
        finally:
            session.close()

    def count_events_since(self, since_ts: datetime, exclude_label: str = None) -> int:
        session = self.get_session()
        try:
            q = session.query(VideoMetadata).filter(VideoMetadata.timestamp >= since_ts)
            if exclude_label:
                q = q.filter(VideoMetadata.violence_label != exclude_label)
            return q.count()
        finally:
            session.close()

    def get_events_stats(self, hours: int = 24):
        """Returns aggregated stats for charts:
           - by_time: count per hour (key=HH:00)
           - by_type: count per label
        """
        session = self.get_session()
        try:
            since = datetime.utcnow() - timedelta(hours=hours)
            # Filter matches "Normal" exclusion to show only significant events
            rows = session.query(VideoMetadata.timestamp, VideoMetadata.violence_label)\
                          .filter(VideoMetadata.timestamp >= since)\
                          .filter(VideoMetadata.violence_label != 'Normal')\
                          .all()
            
            by_time = {}
            by_type = {}
            
            # Sort by timestamp to enable gap detection
            rows.sort(key=lambda x: x[0])

            by_time = {}
            by_type = {}
            
            last_event_ts = None
            last_event_label = None
            GAP_THRESHOLD = timedelta(seconds=10)

            for ts, label in rows:
                lbl = label or "Unknown"
                if lbl == "Normal": 
                    continue

                # Check if this frame belongs to the previous event (same label, close in time)
                is_new_event = True
                if last_event_ts is not None and last_event_label == lbl:
                    if (ts - last_event_ts) < GAP_THRESHOLD:
                        is_new_event = False
                
                # Update tracking for next iteration
                last_event_ts = ts
                last_event_label = lbl

                if is_new_event:
                    # Time bucket (hour)
                    h = ts.strftime("%H:00")
                    by_time[h] = by_time.get(h, 0) + 1
                    
                    # Type bucket
                    by_type[lbl] = by_type.get(lbl, 0) + 1

            return {"by_time": by_time, "by_type": by_type}
        finally:
            session.close()

    def count_critical_events_since(self, since_ts: datetime) -> int:
        session = self.get_session()
        try:
            # Defined critical labels
            CRITICAL = ['Fighting', 'Shooting', 'Burglary', 'Fire', 'Explosion', 'Accident']
            return session.query(VideoMetadata).filter(VideoMetadata.timestamp >= since_ts)\
                          .filter(VideoMetadata.violence_label.in_(CRITICAL))\
                          .count()
        finally:
            session.close()

    # ---------------- Cameras ----------------
    def list_cameras(self, only_enabled: bool = False):
        session = self.get_session()
        try:
            q = session.query(Camera)
            if only_enabled:
                q = q.filter(Camera.enabled == True)
            return q.all()
        finally:
            session.close()

    def create_camera(self, name: str, source_url: str, zone: str | None = None, enabled: bool = True, embed_fps: int | float | None = None) -> Camera:
        session = self.get_session()
        try:
            fields = dict(name=name, source_url=source_url, zone=zone, enabled=enabled)
            if embed_fps is not None:
                try:
                    fields["embed_fps"] = int(embed_fps) if float(embed_fps).is_integer() else float(embed_fps)
                except Exception:
                    pass
            cam = Camera(**fields)
            session.add(cam)
            session.commit()
            session.refresh(cam)
            return cam
        finally:
            session.close()

    def update_camera(self, camera_id: int, **fields) -> Camera | None:
        session = self.get_session()
        try:
            cam = session.query(Camera).get(camera_id)
            if not cam:
                return None
            for k, v in fields.items():
                if hasattr(cam, k) and v is not None:
                    setattr(cam, k, v)
            session.commit()
            session.refresh(cam)
            return cam
        finally:
            session.close()

    def delete_camera(self, camera_id: int) -> bool:
        session = self.get_session()
        try:
            cam = session.query(Camera).get(camera_id)
            if not cam:
                return False
            session.delete(cam)
            session.commit()
            return True
        finally:
            session.close()
