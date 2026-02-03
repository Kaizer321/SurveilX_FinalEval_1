import sys
import os
from pathlib import Path
from sqlalchemy import text

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.metadata.db_manager import DatabaseManager
from config.settings import settings

if __name__ == "__main__":
    db = DatabaseManager()
    session = db.get_session()
    # Test connection
    session.execute(text("SELECT 1"))
    print("Successfully connected to PostgreSQL database!")