import logging
import os

filepath = r"d:\FYP\SurveilX_FinalEval_1\src\vector_store\chroma_store.py"
content = """

def delete_frames(frame_ids: list[str]) -> bool:
    \"\"\"Delete a list of frames from Chroma collection.\"\"\"
    if not frame_ids:
        return True
    try:
        col = get_collection()
        col.delete(ids=frame_ids)
        logger.info(f"Deleted {len(frame_ids)} frames from Chroma")
        return True
    except Exception as e:
        logger.error(f"Chroma delete failed: {e}")
        return False
"""
with open(filepath, "a", encoding="utf-8") as f:
    f.write(content)
print("Added delete_frames successfully!")
