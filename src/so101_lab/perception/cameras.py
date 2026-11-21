import threading
import time
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class Frame:
    image: np.ndarray
    sampled_at: float

    def jpeg(self):
        ok, buf = cv2.imencode(".jpg", self.image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise ValueError("JPEG encoding failed")
        return buf.tobytes()


class Cameras:
    def __init__(self):
        self.frames = {}
        self.workers = {}
        self.roles = {}
        self.lock = threading.RLock()

    def discover(self, count=5):
        result = []
        for i in range(min(count, 10)):
            if str(i) in self.workers:
                result.append({"id": str(i), "available": True})
                continue
            cap = cv2.VideoCapture(i)
            try:
                if cap.isOpened() and cap.read()[0]:
                    result.append({"id": str(i), "available": True})
            finally:
                cap.release()
        return result

    def open(self, camera_id, role="overhead"):
        if role not in ("overhead", "wrist", "side", "observation"):
            raise ValueError("Unknown camera role")
        if camera_id in self.workers:
            self.roles[camera_id] = role
            return
        if not camera_id.isdigit() or not 0 <= int(camera_id) < 20:
            raise ValueError("Choose a local camera index, not a network URL")
        cap = cv2.VideoCapture(int(camera_id))
        if not cap.isOpened():
            cap.release()
            raise ValueError("Cannot open camera; check OS camera permission")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        done = threading.Event()

        def capture():
            try:
                while not done.is_set():
                    started = time.monotonic()
                    ok, frame = cap.read()
                    if not ok:
                        with self.lock:
                            self.frames.pop(camera_id, None)
                        return
                    with self.lock:
                        self.frames[camera_id] = Frame(frame, started)
                    done.wait(0.03)
            finally:
                cap.release()

        thread = threading.Thread(target=capture, daemon=True)
        self.workers[camera_id] = (done, thread)
        self.roles[camera_id] = role
        thread.start()

    def get(self, camera_id, max_age=0.75):
        with self.lock:
            frame = self.frames.get(camera_id)
        if frame is None or not 0 <= time.monotonic() - frame.sampled_at <= max_age:
            raise ValueError("Camera frame missing or stale")
        return frame

    def fresh(self, camera_id, max_age=0.75):
        try:
            self.get(camera_id, max_age)
            return True
        except ValueError:
            return False

    def status(self):
        return [{"id": k, "role": v, "fresh": self.fresh(k)} for k, v in self.roles.items()]

    def close(self):
        for done, _ in self.workers.values():
            done.set()
        for _, thread in self.workers.values():
            thread.join(timeout=1)
        self.workers.clear()
        self.frames.clear()
