# module1/config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

# Disable Chroma telemetry early (before any chromadb import)
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "false")

class Settings:
    # Base directory
    BASE_DIR = Path(__file__).parent.parent
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # Application Settings
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # Database Configuration
    DB_URL = os.getenv("SURVEILX_DB_URL")
    if not DB_URL:
        raise ValueError("SURVEILX_DB_URL environment variable not set")
    
    # ChromaDB Configuration
    CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(BASE_DIR / "chroma_db")))
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Camera Configuration
    CAMERA_SOURCES = {
        "cam1": "https://www.youtube.com/watch?v=rnXIjl_Rzy4&pp=ygUZbGl2ZSBjY3R2IGNhbWVyYSBmb290YWdlcw%3D%3D",
        "cam2": "https://www.youtube.com/watch?v=tujkoXI8rWM",
    }
    
    CAMERA_LOCATIONS = {
        "cam1": "Floor 1 - Lobby",
        "cam2": "Floor 2 - Lobby",
    }
    
    # Detection/pose models
    MODELS_DIR = BASE_DIR / "models"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    VIOLENCE_CKPT_PATH = Path(os.getenv("VIOLENCE_CKPT_PATH", str(MODELS_DIR / "cnn_tcn_fusion.pth")))
    POSE_MODEL_PATH = Path(os.getenv("POSE_MODEL_PATH", str(MODELS_DIR / "yolov8n-pose.pt")))
    
    # Storage Directories
    DATA_DIR = BASE_DIR / "data"
    OUTPUT_DIR = DATA_DIR / "output"
    PROCESSED_DIR = DATA_DIR / "processed"
    
    # Create necessary directories
    for directory in [OUTPUT_DIR, PROCESSED_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    
    # Application Settings
    FRAME_RATE = int(os.getenv("FRAME_RATE", "1"))  # Frames per second to process
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))  # Number of worker threads
    
    # Model Configuration
    MODEL_NAME = os.getenv("MODEL_NAME", "ViT-B/32")  # Default to CLIP ViT-B/32
    
    # Logging Configuration
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    
    @property
    def database_url(self) -> str:
        """Get the database URL with masked password for logging."""
        if "@" not in self.DB_URL:
            return self.DB_URL
        parts = self.DB_URL.split("@", 1)
        return f"{parts[0].split('//')[0]}//***:***@{parts[1]}"

# Initialize settings
settings = Settings()

# Configure logging
import logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT
)

# Log database connection info (with masked password)
logging.getLogger(__name__).info(f"Database URL: {settings.database_url}")
logging.getLogger(__name__).info(f"ChromaDB directory: {settings.CHROMA_DIR}")