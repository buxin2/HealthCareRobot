import cv2
import threading
import time
from datetime import datetime
import os

class Camera:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self.frame = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
    def start(self):
        """Start the camera feed"""
        if self.running:
            return
            
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {self.camera_index}")
            
        # Set camera properties
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_frames)
        self.thread.daemon = True
        self.thread.start()
        
    def stop(self):
        """Stop the camera feed"""
        self.running = False
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()
            
    def _capture_frames(self):
        """Continuously capture frames from camera"""
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame.copy()
            time.sleep(1/30)  # ~30 FPS
            
    def get_frame(self):
        """Get the latest frame as JPEG bytes"""
        with self.lock:
            if self.frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.frame)
            return jpeg.tobytes() if ret else None
            
    def take_picture(self, filename=None):
        """Take a picture and save it"""
        with self.lock:
            if self.frame is None:
                return None
                
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"patient_{timestamp}.jpg"
            
        # Create uploads directory if it doesn't exist
        os.makedirs('uploads', exist_ok=True)
        filepath = os.path.join('uploads', filename)
        
        # Save the image
        cv2.imwrite(filepath, self.frame)
        return filename

# Global camera instance
camera = Camera()

def generate_frames():
    """Generator function for streaming video frames"""
    while True:
        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            time.sleep(0.1)