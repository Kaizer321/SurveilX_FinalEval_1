# src/vector_store/chroma_store.py
import os
import logging
from typing import List, Dict, Optional, Any
from pathlib import Path

# Disable telemetry BEFORE importing chromadb
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "false")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions

from config.settings import settings

# Configure logging
logger = logging.getLogger(__name__)

# Quiet chroma telemetry loggers (suppress posthog errors)
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

# Ensure CHROMA_DIR exists and is a string path
CHROMA_DIR = str(Path(settings.CHROMA_DIR).absolute())
os.makedirs(CHROMA_DIR, exist_ok=True)

# Configure ChromaDB with SQLite
client = chromadb.PersistentClient(
    path=CHROMA_DIR,
    settings=ChromaSettings(anonymized_telemetry=False)
)

# Collection name
COLLECTION_NAME = "video_frames"

def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Sanitize metadata to ensure it's JSON-serializable."""
    if not metadata:
        return {}
    return {
        k: str(v) if not isinstance(v, (str, int, float, bool)) else v
        for k, v in metadata.items()
        if v is not None
    }

def get_collection():
    """Get or create the Chroma collection."""
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_functions.DefaultEmbeddingFunction()
    )

def upsert_frame(
    frame_id: Optional[str] = None,
    metadata: Dict[str, Any] = None,
    document: Optional[str] = None,
    embedding: Optional[List[float]] = None,
    _id: Optional[str] = None,
) -> None:
    """Upsert a frame into the collection.
    
    Args:
        frame_id: Unique identifier for the frame
        metadata: Dictionary of metadata to store with the frame
        document: Optional text content of the frame
        embedding: Optional vector embedding of the frame
        _id: Backward-compatible alias for frame_id
    """
    collection = get_collection()
    # Backward compatibility: support callers that pass _id
    id_value = frame_id or _id
    if not id_value:
        raise ValueError("upsert_frame requires either frame_id or _id")
    data = {
        "ids": [id_value],
        "metadatas": [_sanitize_metadata(metadata)]
    }
    
    if document is not None:
        data["documents"] = [document]
    if embedding is not None:
        data["embeddings"] = [embedding]
    
    try:
        collection.upsert(**data)
        logger.debug(f"Upserted frame: {frame_id}")
    except Exception as e:
        logger.error(f"Error upserting frame {frame_id}: {str(e)}")
        raise

def query_by_metadata(
    where: Dict[str, Any],
    n_results: int = 5,
    include: Optional[List[str]] = None
) -> Dict[str, List[Any]]:
    """Query frames by metadata.
    
    Args:
        where: Dictionary of metadata filters
        n_results: Maximum number of results to return
        include: List of fields to include in results (None for all)
        
    Returns:
        Dictionary containing query results
    """
    collection = get_collection()
    try:
        return collection.query(
            where=where,
            n_results=n_results,
            include=include or ["documents", "metadatas", "embeddings"]
        )
    except Exception as e:
        logger.error(f"Error querying frames: {str(e)}")
        raise

def delete_by_ids(ids: List[str]) -> None:
    """Delete frames by their IDs.
    
    Args:
        ids: List of frame IDs to delete
    """
    if not ids:
        return
        
    collection = get_collection()
    try:
        collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} frames")
    except Exception as e:
        logger.error(f"Error deleting frames: {str(e)}")
        raise

def get_all_metadata() -> List[Dict[str, Any]]:
    """Get metadata for all frames in the collection."""
    collection = get_collection()
    try:
        results = collection.get(include=["metadatas"])
        return results.get("metadatas", [])
    except Exception as e:
        logger.error(f"Error fetching all metadata: {str(e)}")
        raise