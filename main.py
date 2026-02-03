# module1/main.py
from config.settings import settings
from src.video_capture.camera_manager import CameraManager
from src.video_capture.video_capture import VideoCapture
from src.preprocessing.video_preprocessor import VideoPreprocessor
from src.preprocessing.processing_queue import ProcessingQueue
from src.vector_store import chroma_store
from src.vector_store.clip_embedder import embed_image_bgr
from src.metadata.db_manager import DatabaseManager
from src.metadata.extractor import MetadataExtractor
from src.detection.violence_detector import ViolenceDetector
import time, cv2, os
from datetime import datetime

def main():
    cam_manager = CameraManager(settings.CAMERA_SOURCES)
    video_capture = VideoCapture(cam_manager)
    preprocessor = VideoPreprocessor(target_resolution=(320, 200), target_fps=10)
    detector = ViolenceDetector(
        checkpoint_path=settings.VIOLENCE_CKPT_PATH,
        pose_model_path=settings.POSE_MODEL_PATH,
    )
    proc_queue = ProcessingQueue(preprocessor, max_workers=2)
    proc_queue.process_queue()

    # Initialize structured DB (SQLite by default via DB_URL)
    db = DatabaseManager()

    camera_ids = cam_manager.discover_cameras()
    for cid in camera_ids:
        video_capture.start_capture(cid)

    extractors = {cid: MetadataExtractor(cid) for cid in camera_ids}
    frame_counts = {cid: 0 for cid in camera_ids}
    # throttle to ~10 FPS per camera
    last_tick = {cid: 0.0 for cid in camera_ids}

    print("Press 'q' to stop...")
    while True:
        now = time.time()
        for cid in camera_ids:
            # process each camera at ~10 Hz
            if (now - last_tick[cid]) < 0.10:
                continue
            frame = video_capture.get_frame(cid)
            if frame is not None:
                processed = preprocessor.process_frame(frame)
                if processed is not None:
                    detection = {}
                    try:
                        detection = detector.predict(cid, processed, show_keypoints=False)
                    except Exception as de:
                        print(f"[MAIN] Detection failed for {cid}: {de}")
                        detection = {}

                    display_frame = detection.get("overlay_frame") or processed
                    label = detection.get("label")
                    score = detection.get("score")
                    if label is not None and score is not None:
                        color = (0, 0, 255) if label != "Normal" else (0, 255, 0)
                        cv2.putText(
                            display_frame,
                            f"{label} ({score:.2f})",
                            (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            color,
                            2,
                        )

                    cv2.imshow(f"Processed - {cid}", display_frame)

                    # For demo: every 60th frame, save processed file and metadata per camera
                    if frame_counts[cid] % 60 == 0:
                        ts_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                        filename = f"{cid}_{ts_str}_{frame_counts[cid]}.jpg"
                        out_path = os.path.join(settings.PROCESSED_DIR, filename)
                        cv2.imwrite(out_path, frame)

                        md_extra = {"frame_index": frame_counts[cid]}
                        if detection:
                            md_extra.update(
                                {
                                    "violence_label": label,
                                    "violence_score": score,
                                    "class_probs": detection.get("class_probs"),
                                }
                            )
                        md = extractors[cid].extract(processed, extra=md_extra)

                        # Write structured metadata to SQLite (or configured DB)
                        try:
                            pk_val = int(cid) if isinstance(cid, int) or cid.isdigit() else None
                        except:
                            pk_val = None

                        try:
                            vs = db.insert_video_stream(camera_id=cid, camera_pk=pk_val)
                            vm = db.insert_video_metadata(
                                frame_id=f"{cid}:{ts_str}:{frame_counts[cid]}",
                                timestamp=md["timestamp"],
                                camera_location=md.get("camera_location"),
                                resolution=md["resolution"],
                                metadata_json={
                                    **(md.get("metadata_json") or {}),
                                    "file_path": out_path,
                                    "frame_index": frame_counts[cid],
                                },
                                violence_label=label,
                                violence_score=score,
                                detections=(detection.get("class_probs") if detection else {}),
                                video_stream_id=vs.id,
                                camera_pk=pk_val,
                                embedding={"chroma_id": f"{cid}:{ts_str}:{frame_counts[cid]}"}
                            )
                            print(f"[MAIN] Saved {filename} and metadata id {vm.id}")
                        except Exception as dbe:
                            print(f"[MAIN] DB insert failed: {dbe}")

                        # Write to ChromaDB as well (id + metadata + embedding)
                        try:
                            chroma_id = f"{cid}:{ts_str}:{frame_counts[cid]}"
                            chroma_meta = {
                                "camera_id": cid,
                                "camera_location": md.get("camera_location"),
                                "timestamp_iso": md["timestamp"].isoformat() if hasattr(md["timestamp"], 'isoformat') else str(md["timestamp"]),
                                "resolution": md.get("resolution"),
                                "frame_index": frame_counts[cid],
                                "file_path": out_path,
                                "violence_label": label,
                                "violence_score": score,
                                "class_probs": detection.get("class_probs") if detection else None,
                            }
                            # Compute CLIP embedding for the processed frame
                            embedding = embed_image_bgr(processed)
                            chroma_store.upsert_frame(
                                _id=chroma_id,
                                metadata=chroma_meta,
                                document=f"Frame {frame_counts[cid]} from {cid} at {ts_str}",
                                embedding=embedding,
                            )
                            print(f"[MAIN] Saved {filename}")
                        except Exception as ce:
                            print(f"[MAIN] Chroma upsert failed: {ce}")

                    frame_counts[cid] += 1
            # update last tick regardless, to avoid busy-polling beyond 10 Hz
            last_tick[cid] = now

        # light sleep to reduce CPU load while maintaining responsiveness
        time.sleep(0.005)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    for cid in camera_ids:
        video_capture.stop_capture(cid)
    proc_queue.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
