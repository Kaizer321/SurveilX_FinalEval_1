from src.metadata.db_manager import DatabaseManager
from datetime import datetime, timedelta

def check_events():
    db = DatabaseManager()
    session = db.get_session()
    try:
        from src.metadata.models import VideoMetadata
        count = session.query(VideoMetadata).count()
        print(f"Total metadata rows: {count}")
        
        since = datetime.now() - timedelta(hours=24)
        count_recent = session.query(VideoMetadata).filter(VideoMetadata.timestamp >= since).count()
        print(f"Recent (24h) rows: {count_recent}")
        
        if count_recent > 0:
            labels = session.query(VideoMetadata.violence_label).distinct().all()
            print(f"Labels found: {[l[0] for l in labels]}")
            
            # Test aggregation
            events = db.get_aggregated_events(limit=5)
            print(f"Aggregated events count: {len(events)}")
            for e in events:
                print(e)
        else:
            print("No recent data to aggregate.")
    finally:
        session.close()

if __name__ == "__main__":
    check_events()
