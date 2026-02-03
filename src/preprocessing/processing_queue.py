# module1/src/preprocessing/processing_queue.py
import threading
import queue
import cv2
import time

class ProcessingQueue:
    """Manages parallel video preprocessing using worker threads."""

    def __init__(self, preprocessor, max_workers=2):
        self.preprocessor = preprocessor
        self.task_queue = queue.Queue()
        self.max_workers = max_workers
        self.threads = []
        self.running = False

    def add_task(self, frame, output_path):
        """Queue a new frame for processing."""
        self.task_queue.put((frame, output_path))

    def _worker(self):
        while self.running:
            try:
                frame, output_path = self.task_queue.get(timeout=1)
                processed = self.preprocessor.process_frame(frame)
                if processed is not None:
                    # Save processed frame (for demonstration, overwrite output image)
                    cv2.imwrite(output_path, processed)
                self.task_queue.task_done()
            except queue.Empty:
                continue

    def process_queue(self):
        """Start processing threads."""
        self.running = True
        for _ in range(self.max_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        """Stop workers gracefully."""
        self.running = False
        for t in self.threads:
            t.join(timeout=1)
