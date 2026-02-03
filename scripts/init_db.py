#!/usr/bin/env python3
"""
Initialize the PostgreSQL database with the required schema.
Run this script once to set up the database tables.
"""
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy_utils import database_exists, create_database
from dotenv import load_dotenv

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.metadata.models import Base
from config.settings import settings

def init_db():
    """Initialize the database and create tables."""
    # Load environment variables from .env file if it exists
    load_dotenv()
    
    # Get the database URL from environment or use the default from settings
    db_url = os.getenv("SURVEILX_DB_URL", settings.DB_URL)
    
    if not db_url.startswith('postgresql'):
        print("Error: Database URL must be a PostgreSQL connection string.")
        print("Please set the SURVEILX_DB_URL environment variable with a valid PostgreSQL connection string.")
        print("Example: postgresql+psycopg2://username:password@localhost:5432/your_database")
        sys.exit(1)
    
    # Create engine
    engine = create_engine(db_url)
    
    # Create database if it doesn't exist
    if not database_exists(engine.url):
        print(f"Creating database: {engine.url.host}/{engine.url.database}")
        create_database(engine.url)
    
    # Create tables
    print("Creating database tables...")
    Base.metadata.create_all(engine)
    print("Database initialized successfully!")

if __name__ == "__main__":
    init_db()
