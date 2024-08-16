import cv2
import threading
from queue import Queue

# Check for CUDA device and set it
class IPStreamHandler:
    def __init__(self, ip_url):
        self.ip_url = ip_url
        self.frame_queue = Queue(maxsize=1)
        self.cap = cv2.VideoCapture(self.ip_url)
        self.stopped = False

    def start(self):
        threading.Thread(target=self.update, args=(), daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            if not self.frame_queue.full():
                ret, frame = self.cap.read()
                if not ret:
                    self.stop()
                else:
                    self.frame_queue.put(frame)

    def read(self):
        return self.frame_queue.get()

    def stop(self):
        self.stopped = True
        self.cap.release()
