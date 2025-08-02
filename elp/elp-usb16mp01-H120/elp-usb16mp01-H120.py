# elp-usb16mp01-H120
"""
https://www.elpcctv.com/16-megapixel-120-degree-no-distortion-hd-usb-micro-camera-module-wide-angle-p-361.html
Resolution & Frame Rate
4656 x 3496 MJPEG 10fps/ YUY2 1fps   4208 x 3120 MJPEG 10fps/ YUY2 1fps
4160 x 3120 MJPEG@10fps YUY2@1fps   4000 x 3000MJPEG@10fps YUY2@1fps
3840 x 2160 MJPEG@10fps YUY2@1fps   3264 x 2448MJPEG@10fps YUY2@1fps
2592 x 1944 MJPEG@10fps YUY2@1fps   2320 x 1744MJPEG@30fps YUY2@1fps
2048 x 1536 MJPEG@30fps YUY2@1fps   1920 x 1080MJPEG@30fps YUY2@5fps
1600 x 1200 MJPEG@30fps YUY2@5fps   1280 x 960MJPEG@30fps YUY2@10fps
1280 x 720 MJPEG@30fps YUY2@10fps   1024 x 768MJPEG@30fps YUY2@10fps
800 x 600 MJPEG@30fps YUY2@15fps     640 x 480MJPEG@30fps YUY2@30fps
"""
import cv2
import numpy as np
import threading
import time
import os
from datetime import datetime, timedelta, timezone
import queue
import argparse
from collections import deque
import glob
import subprocess
import sys
import json # For metadata JSON files
import shutil # For disk usage
import atexit # For graceful shutdown
from functools import wraps

# Flask imports for web server
from flask import Flask, Response, render_template, request, redirect, url_for, session, send_file, jsonify

# --- Configuration Constants ---
ADJUSTMENT_INTERVAL = 1.0  # Seconds between image adjustments
BRIGHTNESS_TARGET_LOW = 80 # Target average pixel value for "not too dark"
BRIGHTNESS_TARGET_HIGH = 120 # Target average pixel value for "not too bright"
ADJUSTMENT_STEP_EXPOSURE = 50 # Base amount to change exposure by
ADJUSTMENT_STEP_BRIGHTNESS = 4 # Base amount to change brightness by
ADJUSTMENT_STEP_CONTRAST = 2 # Base amount to change contrast by
ADJUSTMENT_STEP_GAIN = 10 # Base amount to change gain by

BRIGHTNESS_DEVIATION_SCALE = 0.5 # Adjust this value: higher means more aggressive scaling

# --- Video Recording Constants ---
VIDEO_SAVE_PATH = '~/video_streams' 
CLIP_DURATION_MINUTES = 1 # Duration of each video clip before a new one is started
DIRECTORY_THRESHOLD_GB = 50 # GB of disk usage at which old files are deleted
DISK_CHECK_INTERVAL_SECONDS = 60 # How often to check disk space

# --- Authentication Constants ---
# Set WEB_PASSWORD environment variable to protect access
WEB_PASSWORD = os.environ.get('WEB_PASSWORD', None)

# Define common camera setting ranges
SETTING_RANGES = {
    'auto_exposure': {'manual': 1, 'aperture_priority': 3},
    'exposure_time_absolute': {'min': 1, 'max': 5000},
    'brightness': {'min': -64, 'max': 64},
    'contrast': {'min': 0, 'max': 64},
    'saturation': {'min': 0, 'max': 128},
    'hue': {'min': -40, 'max': 40},
    'gamma': {'min': 72, 'max': 500},
    'gain': {'min': 0, 'max': 100},
    'power_line_frequency': {'disabled': 0, '50hz': 1, '60hz': 2},
    'white_balance_automatic': {'off': 0, 'on': 1},
    'white_balance_temperature': {'min': 2800, 'max': 6500},
    'sharpness': {'min': 0, 'max': 6},
    'backlight_compensation': {'min': 0, 'max': 2},
    'pan_absolute': {'min': -36000, 'max': 36000},
    'tilt_absolute': {'min': -36000, 'max': 36000},
    'zoom_absolute': {'min': 0, 'max': 9},
}

DEFAULT_CAMERA_SETTINGS = {
    'brightness': 0,
    'contrast': 32,
    'gain': 0,
}


class CameraInspector:
    def __init__(self, camera_device, camera_name, max_resolution=(1920, 1080), real_device_path=None):
        self.camera_device = camera_device
        self.camera_name = camera_name
        self.max_resolution = max_resolution
        self.real_device_path = real_device_path
        self.cap = None
        self.frame_queue = queue.Queue(maxsize=30)
        self.fps_counter = deque(maxlen=30)
        self.running = False
        self.capture_thread = None
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.dropped_frames = 0
        self.recorder = None # Will be set by MultiCameraInspector
        
    def initialize_camera(self):
        print(f"Initializing {self.camera_name} ({self.camera_device})...")
        
        device_identifier = None
        if isinstance(self.camera_device, str) and self.camera_device.startswith('/dev/'):
            if self.real_device_path and 'video' in self.real_device_path:
                try:
                    device_identifier = int(self.real_device_path.split('video')[1])
                except ValueError:
                    print(f"Error: Could not parse numeric ID from real device path '{self.real_device_path}'.")
                    return False
            else:
                print(f"Warning: No valid real_device_path found or it's not a /dev/videoX link for {self.camera_name}. Attempting to open by full path (less reliable).")
                device_identifier = self.camera_device
        else:
            device_identifier = self.camera_device

        if device_identifier is None:
            print(f"Error: Could not determine camera device identifier for {self.camera_name}.")
            return False

        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
        
        for backend in backends:
            print(f"Attempting to open {self.camera_name} with backend: {backend} (ID: {device_identifier})...")
            self.cap = cv2.VideoCapture(device_identifier, backend)
            
            if self.cap.isOpened():
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    print(f"{self.camera_name} opened successfully and read test frame with backend: {backend}.")
                    break
                else:
                    print(f"{self.camera_name} opened with backend {backend}, but failed to read test frame. Retrying with next backend...")
                    self.cap.release()
                    self.cap = None
            else:
                print(f"{self.camera_name} failed to open with backend: {backend}. Retrying with next backend...")
                if self.cap:
                    self.cap.release()
                self.cap = None
                    
        if not self.cap or not self.cap.isOpened():
            print(f"CRITICAL ERROR: Failed to open {self.camera_name} ({self.camera_device}) with any backend.")
            return False
        
        try:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            print(f"{self.camera_name}: Attempted to set FOURCC to MJPG.")
        except Exception as e:
            print(f"Warning: Could not set FOURCC for {self.camera_name}: {e}")

        width, height = self.max_resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 30) # Request 30 FPS, actual might differ
        
        if self.real_device_path and os.path.exists(self.real_device_path):
            try:
                if self.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['aperture_priority']):
                    print(f"{self.camera_name}: Auto-exposure disabled (set to manual).")
                else:
                    print(f"{self.camera_name}: Did not set auto_exposure to manual via v4l2-ctl.")

                if self.set_camera_setting('white_balance_automatic', SETTING_RANGES['white_balance_automatic']['on']):
                    print(f"{self.camera_name}: Auto-white balance disabled.")
                else:
                    print(f"{self.camera_name}: Did not set white_balance_automatic to off via v4l2-ctl.")
                time.sleep(0.1)
            except Exception as e:
                print(f"Error attempting initial v4l2-ctl settings for {self.camera_name}: {e}")
        else:
            print(f"Warning: Real device path '{self.real_device_path}' not available or does not exist for {self.camera_name}. Cannot set v4l2-ctl properties.")

        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        print(f"{self.camera_name} - Actual Resolution: {actual_width}x{actual_height}, Actual FPS: {actual_fps}")
        
        return True
    
    def set_default_camera_settings(self):
        if not self.real_device_path or not os.path.exists(self.real_device_path):
            print(f"[{self.camera_name}] Cannot set default settings: real device path not available.")
            return

        print(f"[{self.camera_name}] Applying default camera settings...")

        self.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['aperture_priority'])
        self.set_camera_setting('white_balance_automatic', SETTING_RANGES['white_balance_automatic']['on'])
        time.sleep(0.1)

        for setting, default_value in DEFAULT_CAMERA_SETTINGS.items():
            if setting in SETTING_RANGES:
                min_val = SETTING_RANGES[setting].get('min', default_value)
                max_val = SETTING_RANGES[setting].get('max', default_value)
                clamped_value = max(min_val, min(default_value, max_val))
                
                if self.set_camera_setting(setting, clamped_value):
                    print(f"[{self.camera_name}] Set default {setting} to {clamped_value}.")
                else:
                    print(f"[{self.camera_name}] Failed to set default {setting} to {clamped_value}.")
            else:
                print(f"[{self.camera_name}] Warning: Default setting '{setting}' not in SETTING_RANGES, skipping.")
        time.sleep(0.2)


    def set_camera_setting(self, setting_name, value):
        if not self.real_device_path or not os.path.exists(self.real_device_path):
            return False

        try:
            if setting_name == 'exposure_time_absolute':
                if self.get_camera_setting('auto_exposure') != SETTING_RANGES['auto_exposure']['manual']:
                    self.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['manual'])
                    time.sleep(0.05)
            elif setting_name == 'white_balance_temperature':
                if self.get_camera_setting('white_balance_automatic') != SETTING_RANGES['white_balance_automatic']['off']:
                    self.set_camera_setting('white_balance_automatic', SETTING_RANGES['white_balance_automatic']['off'])
                    time.sleep(0.05)

            command = ["v4l2-ctl", "-d", self.real_device_path, f"--set-ctrl={setting_name}={value}"]
            result = subprocess.run(command, capture_output=True, text=True)

            if result.returncode == 0:
                return True
            else:
                print(f"Failed to set {setting_name} to {value} for {self.camera_name}. Error: {result.stderr.strip()}")
                if "Invalid argument" in result.stderr or "failed" in result.stderr:
                    print(f"  Check 'v4l2-ctl -d {self.real_device_path} -L' for valid ranges and available controls.")
                return False
        except FileNotFoundError:
            print("Error: v4l2-ctl not found. Please ensure it is installed (sudo apt install v4l-utils).")
            return False
        except Exception as e:
            print(f"An error occurred while setting {setting_name} for {self.camera_name}: {e}")
            return False

    def get_camera_setting(self, setting_name):
        if not self.real_device_path or not os.path.exists(self.real_device_path):
            return None

        try:
            command = ["v4l2-ctl", "-d", self.real_device_path, f"--get-ctrl={setting_name}"]
            result = subprocess.run(command, capture_output=True, text=True)

            if result.returncode == 0:
                output_line = result.stdout.strip()
                if ':' in output_line:
                    value_str = output_line.split(':', 1)[1].strip()
                    try:
                        return int(value_str)
                    except ValueError:
                        return value_str
                else:
                    return None
            else:
                return None
        except FileNotFoundError:
            print("Error: v4l2-ctl not found. Please ensure it is installed (sudo apt install v4l-utils).")
            return None
        except Exception as e:
            print(f"An error occurred while getting {setting_name} for {self.camera_name}: {e}")
            return None

    def capture_frames(self):
        while self.running:
            try:
                ret, frame = self.cap.read()
                current_time = time.time()
                
                if ret and frame is not None:
                    self.frame_count += 1
                    self.fps_counter.append(current_time)
                    
                    try:
                        # Pass frame to recorder if available
                        if self.recorder:
                            self.recorder.write_frame(self.camera_name, frame, current_time, self.get_fps())
                        
                        # Also put in local queue for web stream
                        self.frame_queue.put_nowait((frame, current_time))
                    except queue.Full:
                        self.dropped_frames += 1
                        # print(f"[{self.camera_name}] Local queue full, dropping frame for web stream.") # Too verbose
                        
                else:
                    # Handle camera disconnection or read error
                    print(f"[{self.camera_name}] Failed to read frame (ret={ret}, frame is None). Attempting to re-initialize...")
                    self.stop() # Stop current capture
                    time.sleep(1) # Give a moment before retrying
                    if self.running: # Only try to re-initialize if the main loop is still running
                        if not self.initialize_camera():
                            print(f"[{self.camera_name}] Re-initialization failed. Stopping camera thread.")
                            self.running = False # Exit thread loop
                        else:
                            print(f"[{self.camera_name}] Camera re-initialized successfully.")
            except Exception as e:
                print(f"[{self.camera_name}] Error during frame capture: {e}")
                time.sleep(0.1) # Prevent busy loop on error
    
    def get_fps(self):
        if len(self.fps_counter) < 2:
            return 0.0
        
        time_span = self.fps_counter[-1] - self.fps_counter[0]
        if time_span > 0:
            return (len(self.fps_counter) - 1) / time_span
        return 0.0
    
    def get_frame_info(self):
        try:
            frame, timestamp = self.frame_queue.get_nowait()
            return {
                'frame': frame,
                'timestamp': timestamp,
                'fps': self.get_fps(),
                'frame_count': self.frame_count,
                'dropped_frames': self.dropped_frames,
                'queue_size': self.frame_queue.qsize()
            }
        except queue.Empty:
            return None

    def get_latest_frame(self):
        frame = None
        timestamp = None
        # Consume all frames in queue to get the latest one
        while True:
            try:
                f, t = self.frame_queue.get_nowait()
                frame, timestamp = f, t
                self.frame_queue.task_done()
            except queue.Empty:
                break
        if frame is not None:
            return {'frame': frame, 'timestamp': timestamp}
        return None

    def generate_mjpeg_frames(self):
        while self.running:
            frame_info = self.get_frame_info()
            if frame_info and frame_info['frame'] is not None:
                ret, jpeg = cv2.imencode('.jpg', frame_info['frame'], [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if not ret:
                    time.sleep(0.005)
                    continue
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            else:
                time.sleep(0.01) # Small delay if no frame is available

    def start(self):
        if not self.initialize_camera():
            return False
        
        self.set_default_camera_settings()
            
        self.running = True
        self.capture_thread = threading.Thread(target=self.capture_frames)
        self.capture_thread.daemon = True # Allows main program to exit even if this thread is running
        self.capture_thread.start()
        print(f"{self.camera_name} capture thread started.")
        return True
    
    def stop(self):
        self.running = False
        if self.cap:
            # First, check if the capture thread is still active and join it
            # This ensures the capture_frames loop exits cleanly before releasing the cap
            if self.capture_thread and self.capture_thread.is_alive():
                print(f"Stopping {self.camera_name} capture thread...")
                self.capture_thread.join(timeout=2.0) # Give thread time to finish
                if self.capture_thread.is_alive():
                    print(f"Warning: {self.camera_name} capture thread did not terminate cleanly. Force releasing camera.")
            
            # Now, release the camera resource
            self.cap.release()
            print(f"{self.camera_name} camera released.")
        else:
            print(f"{self.camera_name} camera was not open or already released.")


def detect_cameras():
    cameras = {}
    
    camera_mappings = {
        'camera_lr': 'Lower Right',
        'camera_ur': 'Upper Right', 
        'camera_ul': 'Upper Left',
        'camera_ll': 'Lower Left'
    }
    
    print("Detecting cameras...")
    
    for device_name, display_name in camera_mappings.items():
        device_path = f"/dev/{device_name}"
        if os.path.exists(device_path):
            real_device = os.path.realpath(device_path)
            if "video" in real_device:
                print(f"✓ Found {display_name}: {device_path} -> {real_device}")
                cameras[device_name] = {
                    'path': device_path,
                    'name': display_name,
                    'real_device': real_device
                }
            else:
                print(f"✗ Found symlink {device_path} but it does not point to a /dev/videoX device ({real_device}). Skipping.")
        else:
            print(f"✗ {display_name} not found at {device_path}")
    
    video_devices = sorted(glob.glob("/dev/video*"))
    for device in video_devices:
        already_mapped = False
        for cam_info in cameras.values():
            if cam_info['real_device'] == device:
                already_mapped = True
                break
        
        if already_mapped:
            continue

        vendor_id = None
        product_id = None
        try:
            # Check if udevadm is available and functional
            subprocess.run(['udevadm', '--help'], check=True, capture_output=True) 

            udevadm_output = subprocess.check_output(['udevadm', 'info', '--name', device, '--attribute-walk'], text=True)
            for line in udevadm_output.splitlines():
                if 'ATTRS{idVendor}' in line:
                    vendor_id = line.split('==')[1].strip().strip('"')
                if 'ATTRS{idProduct}' in line:
                    product_id = line.split('==')[1].strip().strip('"')
                if vendor_id and product_id:
                    break

            # ELP Camera USB IDs
            if vendor_id == "32e4" and product_id == "0298": 
                device_num = int(device.split('video')[1])
                generic_name = f"ELP Camera {device_num}"
                print(f"✓ Found unmapped ELP device: {device} (Assigned name: {generic_name})")
                cameras[f"video{device_num}"] = {
                    'path': device,
                    'name': generic_name,
                    'real_device': device
                }
        except subprocess.CalledProcessError as e:
            print(f"Warning: udevadm command failed ({e.returncode}). Cannot identify USB devices. Error: {e.stderr.strip()}")
        except FileNotFoundError:
            print("Warning: udevadm not found. Cannot identify USB devices.")
        except Exception as e:
            print(f"An error occurred during camera detection with udevadm for {device}: {e}")

    if not cameras:
        print("No cameras detected at all. Please check connections, udev rules, and permissions.")
        
    return cameras

def calculate_brightness_level(frame):
    if frame is None or frame.size == 0:
        return 0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return np.mean(gray)

def adjust_image_settings(camera: CameraInspector, current_brightness: float):
    cam_name = camera.camera_name
    real_device = camera.real_device_path

    if not real_device or not os.path.exists(real_device):
        return
    """FOR TESTING
    if camera.get_camera_setting('auto_exposure') != SETTING_RANGES['auto_exposure']['manual']:
        camera.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['manual'])
        time.sleep(0.05)
    """
    if camera.get_camera_setting('auto_exposure') != SETTING_RANGES['auto_exposure']['aperture_priority']:
        camera.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['aperture_priority'])
        time.sleep(0.05)
    
    adjusted_any_setting = False
    """FOR TESTING
    current_exposure = camera.get_camera_setting('exposure_time_absolute')
    exposure_min = SETTING_RANGES.get('exposure_time_absolute', {}).get('min', 1)
    exposure_max = SETTING_RANGES.get('exposure_time_absolute', {}).get('max', 5000)
    """
    current_brightness_val = camera.get_camera_setting('brightness')
    brightness_min = SETTING_RANGES.get('brightness', {}).get('min', -64)
    brightness_max = SETTING_RANGES.get('brightness', {}).get('max', 64)

    current_contrast = camera.get_camera_setting('contrast')
    contrast_min = SETTING_RANGES.get('contrast', {}).get('min', 0)
    contrast_max = SETTING_RANGES.get('contrast', {}).get('max', 64)
            
    current_gain = camera.get_camera_setting('gain')
    gain_min = SETTING_RANGES.get('gain', {}).get('min', 0)
    gain_max = SETTING_RANGES.get('gain', {}).get('max', 100)

    if current_brightness < BRIGHTNESS_TARGET_LOW:
        deviation = BRIGHTNESS_TARGET_LOW - current_brightness
        # FOR TESTING dynamic_step_exposure = max(ADJUSTMENT_STEP_EXPOSURE, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_EXPOSURE / 50)))
        dynamic_step_brightness = max(ADJUSTMENT_STEP_BRIGHTNESS, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_BRIGHTNESS)))
        dynamic_step_contrast = max(ADJUSTMENT_STEP_CONTRAST, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_CONTRAST)))
        dynamic_step_gain = max(ADJUSTMENT_STEP_GAIN, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_GAIN)))
        """
        if current_exposure is not None and current_exposure < exposure_max:
            new_exposure = min(current_exposure + dynamic_step_exposure, exposure_max)
            if camera.set_camera_setting('exposure_time_absolute', new_exposure):
                # print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc exposure ({dynamic_step_exposure}): {current_exposure}->{new_exposure}.")
                adjusted_any_setting = True
        """
        if current_brightness_val is not None and current_brightness_val < brightness_max:
            new_val = min(current_brightness_val + dynamic_step_brightness, brightness_max)
            if camera.set_camera_setting('brightness', new_val):
                # print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc brightness ({dynamic_step_brightness}): {current_brightness_val}->{new_val}.")
                adjusted_any_setting = True

        if current_contrast is not None and current_contrast < contrast_max:
            new_val = min(current_contrast + dynamic_step_contrast, contrast_max)
            if camera.set_camera_setting('contrast', new_val):
                # print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc contrast ({dynamic_step_contrast}): {current_contrast}->{new_val}.")
                adjusted_any_setting = True
            
        if current_gain is not None and current_gain < gain_max:
            new_val = min(current_gain + dynamic_step_gain, gain_max)
            if camera.set_camera_setting('gain', new_val):
                # print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc gain ({dynamic_step_gain}): {current_gain}->{new_val}.")
                adjusted_any_setting = True

    elif current_brightness > BRIGHTNESS_TARGET_HIGH:
        deviation = current_brightness - BRIGHTNESS_TARGET_HIGH
        # FOR TESTING dynamic_step_exposure = max(ADJUSTMENT_STEP_EXPOSURE, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_EXPOSURE / 50)))
        dynamic_step_brightness = max(ADJUSTMENT_STEP_BRIGHTNESS, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_BRIGHTNESS / 10)))
        dynamic_step_contrast = max(ADJUSTMENT_STEP_CONTRAST, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_CONTRAST / 10)))
        dynamic_step_gain = max(ADJUSTMENT_STEP_GAIN, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_GAIN / 5)))
        """FOR TESTING
        if current_exposure is not None and current_exposure > exposure_min:
            new_exposure = max(current_exposure - dynamic_step_exposure, exposure_min)
            if camera.set_camera_setting('exposure_time_absolute', new_exposure):
                # print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec exposure ({dynamic_step_exposure}): {current_exposure}->{new_exposure}.")
                adjusted_any_setting = True
        """
        if current_brightness_val is not None and current_brightness_val > brightness_min:
            new_val = max(current_brightness_val - dynamic_step_brightness, brightness_min)
            if camera.set_camera_setting('brightness', new_val):
                # print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec brightness ({dynamic_step_brightness}): {current_brightness_val}->{new_val}.")
                adjusted_any_setting = True

        if current_contrast is not None and current_contrast > contrast_min:
            new_val = max(current_contrast - dynamic_step_contrast, contrast_min)
            if camera.set_camera_setting('contrast', new_val):
                # print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec contrast ({dynamic_step_contrast}): {current_contrast}->{new_val}.")
                adjusted_any_setting = True
            
        if current_gain is not None and current_gain > gain_min:
            new_val = max(current_gain - dynamic_step_gain, gain_min)
            if camera.set_camera_setting('gain', new_val):
                # print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec gain ({dynamic_step_gain}): {current_gain}->{new_val}.")
                adjusted_any_setting = True
    
    # if not adjusted_any_setting:
        # print(f"[{cam_name}] Brightness within target range or no further adjustment possible.")


class VideoPlayback:
    """Handles video file playback for the web interface"""
    def __init__(self, save_path):
        self.save_path = save_path
        self.current_video = None
        self.video_cap = None
        self.playback_thread = None
        self.playing = False
        self.frame_queue = queue.Queue(maxsize=60)
        self.playback_fps = 30.0
        self.total_frames = 0
        self.current_frame_num = 0
        self.loop_video = True  # Add option to loop videos
        
    def get_video_files(self):
        """Get all available video files organized by camera"""
        videos = {}
        if not os.path.exists(self.save_path):
            return videos
            
        for camera_dir in os.listdir(self.save_path):
            camera_path = os.path.join(self.save_path, camera_dir)
            if os.path.isdir(camera_path):
                video_files = []
                for video_file in sorted(glob.glob(os.path.join(camera_path, "*.avi"))):
                    # Get metadata if available
                    metadata_file = video_file.replace('.avi', '.json')
                    metadata = {}
                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, 'r') as f:
                                metadata = json.load(f)
                        except:
                            pass
                    
                    # Extract timestamp from filename for sorting
                    filename = os.path.basename(video_file)
                    try:
                        # Parse timestamp from filename pattern: camera_YYYYMMDD_HHMMSS_mmm.avi
                        parts = filename.replace('.avi', '').split('_')
                        if len(parts) >= 3:
                            date_str = parts[-2]
                            time_str = parts[-1][:6]  # Take first 6 chars for HHMMSS
                            timestamp = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                        else:
                            timestamp = datetime.fromtimestamp(os.path.getmtime(video_file))
                    except:
                        timestamp = datetime.fromtimestamp(os.path.getmtime(video_file))
                    
                    video_info = {
                        'path': video_file,
                        'filename': filename,
                        'timestamp': timestamp,
                        'size_mb': round(os.path.getsize(video_file) / (1024*1024), 2),
                        'metadata': metadata
                    }
                    video_files.append(video_info)
                
                if video_files:
                    # Sort by timestamp, newest first
                    video_files.sort(key=lambda x: x['timestamp'], reverse=True)
                    videos[camera_dir] = video_files
                    
        return videos
    
    def load_video(self, video_path):
        """Load a video file for playback"""
        try:
            # Stop current playback if running
            if self.playing:
                self.stop_playback()
            
            if self.video_cap:
                self.video_cap.release()
            
            self.video_cap = cv2.VideoCapture(video_path)
            if not self.video_cap.isOpened():
                print(f"Failed to open video file: {video_path}")
                return False
            
            self.current_video = video_path
            self.total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.playback_fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.current_frame_num = 0
            
            # Clear any existing frames in queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    break
            
            print(f"Loaded video: {os.path.basename(video_path)} ({self.total_frames} frames, {self.playback_fps} FPS)")
            return True
            
        except Exception as e:
            print(f"Error loading video {video_path}: {e}")
            return False
    
    def start_playback(self):
        """Start video playback"""
        if not self.video_cap or not self.video_cap.isOpened():
            print("No video loaded or video file could not be opened")
            return False
        
        if self.playing:
            print("Playback already running")
            return True
        
        self.playing = True
        self.playback_thread = threading.Thread(target=self._playback_loop)
        self.playback_thread.daemon = True
        self.playback_thread.start()
        print("Video playback started")
        return True
    
    def stop_playback(self):
        """Stop video playback"""
        if not self.playing:
            return
            
        print("Stopping video playback")
        self.playing = False
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=2.0)
        
        # Clear the frame queue
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
    
    def _playback_loop(self):
        """Internal playback loop"""
        if not self.video_cap or not self.video_cap.isOpened():
            print("Video capture not available in playback loop")
            self.playing = False
            return
            
        frame_delay = 1.0 / max(self.playback_fps, 1.0)  # Prevent division by zero
        
        print(f"Starting playback loop with FPS: {self.playback_fps}, frame delay: {frame_delay}")
        
        while self.playing and self.video_cap and self.video_cap.isOpened():
            ret, frame = self.video_cap.read()
            
            if not ret:
                if self.loop_video and self.total_frames > 0:
                    # End of video, loop back to beginning
                    print("End of video reached, looping back to start")
                    self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.current_frame_num = 0
                    continue
                else:
                    # End of video, stop playback
                    print("End of video reached, stopping playback")
                    self.playing = False
                    break
            
            if frame is None:
                print("Warning: Got None frame from video")
                continue
                
            self.current_frame_num = int(self.video_cap.get(cv2.CAP_PROP_POS_FRAMES))
            
            try:
                # Non-blocking put - if queue is full, skip this frame
                self.frame_queue.put_nowait(frame)
            except queue.Full:
                # Skip frame if queue is full to prevent blocking
                pass
            
            time.sleep(frame_delay)
        
        print("Playback loop ended")
    
    def generate_mjpeg_frames(self):
        """Generate MJPEG frames for web streaming"""
        last_frame = None
        placeholder_frame = None
        
        while True:  # Always generate frames for the web stream
            try:
                if self.playing:
                    # Try to get a frame from the queue
                    frame = None
                    try:
                        # Only get one frame at a time to avoid draining the queue too fast
                        frame = self.frame_queue.get(timeout=0.05)  # 50ms timeout
                        last_frame = frame  # Store the last valid frame
                    except queue.Empty:
                        # No new frame available, use the last frame if we have one
                        frame = last_frame
                    
                    if frame is not None:
                        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                        if ret:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                            continue
                
                # No video playing or no frames available - show placeholder
                if placeholder_frame is None:
                    placeholder_frame = self._create_placeholder_frame()
                
                ret, jpeg = cv2.imencode('.jpg', placeholder_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                
                time.sleep(0.033)  # ~30fps for placeholder
                
            except Exception as e:
                print(f"Error in MJPEG frame generation: {e}")
                time.sleep(0.1)
    
    def _create_placeholder_frame(self):
        """Create a placeholder frame when no video is playing"""
        # Create a dark frame with text
        height, width = 480, 640
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame.fill(30)  # Dark gray background
        
        # Add text
        if self.current_video and not self.playing:
            text = f"Video Loaded: {os.path.basename(self.current_video)}"
            subtext = "Click 'Play' to start playback"
        else:
            text = "No Video Selected"
            subtext = "Select a video from the list to begin playback"
        
        # Main text
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.8
        thickness = 2
        color = (255, 255, 255)
        
        # Get text size and center it
        (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, thickness)
        text_x = (width - text_width) // 2
        text_y = (height - text_height) // 2
        
        cv2.putText(frame, text, (text_x, text_y), font, font_scale, color, thickness)
        
        # Subtext
        font_scale_sub = 0.5
        thickness_sub = 1
        (subtext_width, subtext_height), _ = cv2.getTextSize(subtext, font, font_scale_sub, thickness_sub)
        subtext_x = (width - subtext_width) // 2
        subtext_y = text_y + text_height + 30
        
        cv2.putText(frame, subtext, (subtext_x, subtext_y), font, font_scale_sub, (200, 200, 200), thickness_sub)
        
        return frame
    
    def get_playback_info(self):
        """Get current playback information"""
        return {
            'current_video': os.path.basename(self.current_video) if self.current_video else None,
            'playing': self.playing,
            'current_frame': self.current_frame_num,
            'total_frames': self.total_frames,
            'fps': self.playback_fps,
            'progress_percent': (self.current_frame_num / self.total_frames * 100) if self.total_frames > 0 else 0
        }

class VideoRecorder:
    def __init__(self, save_path, clip_duration_minutes, directory_threshold_gb, disk_check_interval_seconds, resolution, camera_inspectors_map):
        self.save_path = save_path
        self.clip_duration = timedelta(minutes=clip_duration_minutes)
        self.max_directory_size_gb = directory_threshold_gb
        self.disk_check_interval = disk_check_interval_seconds
        self.resolution = resolution
        self.camera_inspectors = camera_inspectors_map

        self.writers = {}
        self.clip_start_times = {}
        self.frame_queues = {}
        self.recorder_threads = {}
        self.running = False
        self.disk_monitor_thread = None
        self.writer_locks = {}

        self.clip_switching_in_progress = {}

        # The initial save_path directory is created, camera-specific subdirectories will be created later.
        os.makedirs(self.save_path, exist_ok=True)
        print(f"Video clips will be saved to: {self.save_path}")
        print(f"Clip duration: {clip_duration_minutes} minutes.")
        print(f"Disk full threshold: {directory_threshold_gb} GB.")

    def _get_current_camera_settings(self, camera_name):
        for cam_id, cam_obj in self.camera_inspectors.items():
            if cam_obj.camera_name == camera_name:
                return {k: cam_obj.get_camera_setting(k) for k in ['exposure_time_absolute', 'brightness', 'contrast', 'gain', 'white_balance_temperature']}
        return {}

    def _open_or_continue_writer(self, camera_name):
        # This function should only be called when the writer_lock is already held
        # for this specific camera.
        timestamp_start = datetime.now()

        # Create camera-specific subdirectory
        camera_save_dir = os.path.join(self.save_path, camera_name)
        os.makedirs(camera_save_dir, exist_ok=True) # Ensure the camera's directory exists

        filename_base = timestamp_start.strftime(f"{camera_name}_%Y%m%d_%H%M%S_%f")[:-3]
        video_filepath = os.path.join(camera_save_dir, f"{filename_base}.avi") # Save in camera's directory
        metadata_filepath = os.path.join(camera_save_dir, f"{filename_base}.json") # Save metadata there too

        current_settings = self._get_current_camera_settings(camera_name)

        current_fps = 30.0
        for cam_id, cam_obj in self.camera_inspectors.items():
            if cam_obj.camera_name == camera_name:
                current_fps = cam_obj.get_fps()
                if current_fps < 1.0:
                    current_fps = 30.0
                break

        width, height = map(int, self.resolution)
        try:
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter(video_filepath, fourcc, current_fps, (width, height))

            if not out.isOpened():
                raise IOError(f"Could not open video writer for {camera_name} at {video_filepath}")

            self.writers[camera_name] = out
            self.clip_start_times[camera_name] = timestamp_start
            print(f"[{camera_name}] Started new video clip: {video_filepath} (FPS: {current_fps:.2f})")

            self.write_metadata(
                metadata_filepath,
                camera_name,
                timestamp_start,
                None,
                self.clip_duration.total_seconds() / 60,
                current_fps,
                f"{width}x{height}",
                'XVID',
                current_settings
            )
            return video_filepath
        except Exception as e:
            print(f"ERROR: Failed to open writer for {camera_name}: {e}")
            return None

    def _close_and_open_new_clip(self, camera_name):
        """
        Handles the actual closing of the current clip and opening of a new one.
        This function is designed to be called when the specific writer_lock is held.
        """
        with self.writer_locks[camera_name]:
            print(f"[{camera_name}] Executing clip switch: Closing current and opening new.")
            # 1. Close current writer and update metadata
            if camera_name in self.writers and self.writers[camera_name] is not None:
                try:
                    current_writer = self.writers[camera_name]
                    current_start_time = self.clip_start_times.get(camera_name)

                    # Update metadata for the just-closed clip
                    if current_start_time:
                        camera_save_dir = os.path.join(self.save_path, camera_name) # Ensure correct path for metadata
                        filename_base = current_start_time.strftime(f"{camera_name}_%Y%m%d_%H%M%S_%f")[:-3]
                        metadata_filepath = os.path.join(camera_save_dir, f"{filename_base}.json")
                        try:
                            with open(metadata_filepath, 'r') as f:
                                metadata = json.load(f)
                        except (FileNotFoundError, json.JSONDecodeError):
                            metadata = {}

                        end_time = datetime.now()
                        duration = (end_time - current_start_time).total_seconds() / 60
                        metadata.update({
                            "timestamp_end": end_time.isoformat(timespec='milliseconds') + 'Z',
                            "duration_minutes": round(duration, 2)
                        })
                        try:
                            with open(metadata_filepath, 'w') as f:
                                json.dump(metadata, f, indent=4)
                        except Exception as e:
                            print(f"ERROR: Could not update metadata for {metadata_filepath}: {e}")

                    current_writer.release()
                    print(f"[{camera_name}] Video writer released (during switch).")
                except Exception as e:
                    print(f"ERROR releasing writer for {camera_name} (during switch): {e}")
                del self.writers[camera_name]
                if camera_name in self.clip_start_times:
                    del self.clip_start_times[camera_name]

            # 2. Open new writer
            success = self._open_or_continue_writer(camera_name)
            if success is None:
                print(f"[{camera_name}] CRITICAL: Failed to reinitialize writer after clip switch. Recording might stop.")
            else:
                print(f"[{camera_name}] Clip switch completed successfully.")


    def _write_frame_thread_func(self, camera_name):
        if camera_name not in self.writer_locks:
            self.writer_locks[camera_name] = threading.Lock()
        
        self.clip_switching_in_progress[camera_name] = False

        with self.writer_locks[camera_name]:
            self._open_or_continue_writer(camera_name)

        while self.running:
            try:
                frame_data = self.frame_queues[camera_name].get(timeout=0.1)
                frame, frame_time, current_fps = frame_data # frame_time is the original capture timestamp

                # --- Draw UTC timestamp on the frame ---
                # Ensure the frame is writable if it's not (e.g., if it's a read-only NumPy array view)
                if not frame.flags['WRITEABLE']:
                    frame = frame.copy() # Make a writable copy if needed

                utc_now = datetime.now(timezone.utc)
                timestamp_str = utc_now.strftime("%Y-%m-%d %H:%M:%S.%f UTC")[:-3] # Milliseconds up to 3 digits

                # Define text properties (adjust as needed for visibility)
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.7
                font_thickness = 2
                text_color = (0, 255, 0) # Green BGR
                text_color_bg = (0, 0, 0) # Black BGR for background rectangle

                # Get text size
                (text_width, text_height), baseline = cv2.getTextSize(timestamp_str, font, font_scale, font_thickness)
                
                # Position text: bottom-left corner with some padding
                text_offset_x = 10
                text_offset_y = frame.shape[0] - 10 # 10 pixels from bottom
                
                # Draw a filled rectangle as a background for better visibility
                # Add some padding around the text
                padding = 5
                rect_start_x = text_offset_x - padding
                rect_start_y = text_offset_y - text_height - baseline - padding
                rect_end_x = text_offset_x + text_width + padding
                rect_end_y = text_offset_y + padding
                
                cv2.rectangle(frame, (rect_start_x, rect_start_y), (rect_end_x, rect_end_y), text_color_bg, -1)
                
                # Put the text on the frame
                cv2.putText(frame, timestamp_str, (text_offset_x, text_offset_y - baseline),
                            font, font_scale, text_color, font_thickness, cv2.LINE_AA)
                # --- End timestamp drawing ---

                start_time = self.clip_start_times.get(camera_name)
                writer = self.writers.get(camera_name)

                if start_time and (datetime.now() - start_time) > self.clip_duration and not self.clip_switching_in_progress[camera_name]:
                    print(f"[{camera_name}] Clip duration exceeded ({self.clip_duration.total_seconds()/60:.1f} min). Initiating clip switch.")
                    self.clip_switching_in_progress[camera_name] = True
                    switch_thread = threading.Thread(target=self._close_and_open_new_clip, args=(camera_name,))
                    switch_thread.daemon = True
                    switch_thread.start()

                if writer and writer.isOpened() and not self.clip_switching_in_progress[camera_name]:
                    try:
                        writer.write(frame)
                    except Exception as write_err:
                        print(f"[{camera_name}] ERROR writing frame: {write_err}. Marking for switch.")
                        self.clip_switching_in_progress[camera_name] = True
                        switch_thread = threading.Thread(target=self._close_and_open_new_clip, args=(camera_name,))
                        switch_thread.daemon = True
                        switch_thread.start()
                elif self.clip_switching_in_progress[camera_name]:
                    pass # Dropping frame because a switch is in progress
                else:
                    print(f"[{camera_name}] ERROR: Writer is not open outside of switch. Dropping frame. Attempting re-open.")
                    self.clip_switching_in_progress[camera_name] = True
                    switch_thread = threading.Thread(target=self._close_and_open_new_clip, args=(camera_name,))
                    switch_thread.daemon = True
                    switch_thread.start()

                self.frame_queues[camera_name].task_done()
            except queue.Empty:
                if self.clip_switching_in_progress.get(camera_name, False):
                    if self.writers.get(camera_name) and self.writers[camera_name].isOpened():
                        print(f"[{camera_name}] Clip switch appears complete while queue was empty.")
                        self.clip_switching_in_progress[camera_name] = False
                continue
            except Exception as e:
                print(f"ERROR in {camera_name} writer thread: {e}")
                time.sleep(0.1)

    def write_frame(self, camera_name, frame, timestamp, current_fps):
        if not self.running:
            return

        if camera_name not in self.frame_queues:
            if camera_name not in self.writer_locks:
                self.writer_locks[camera_name] = threading.Lock()
                self.clip_switching_in_progress[camera_name] = False

            self.frame_queues[camera_name] = queue.Queue(maxsize=120)
            t = threading.Thread(target=self._write_frame_thread_func, args=(camera_name,))
            t.daemon = True
            t.start()
            self.recorder_threads[camera_name] = t
            print(f"[{camera_name}] Recorder thread started for video writing.")

        try:
            # We pass the original `timestamp` (capture time) along with the frame.
            # The UTC timestamp for drawing will be generated *just before* writing the frame.
            self.frame_queues[camera_name].put_nowait((frame, timestamp, current_fps))
        except queue.Full:
            print(f"WARNING: Recorder queue full for {camera_name}. Dropping frame. (Writer stuck or too slow?)")

    def close_writer(self, camera_name):
        with self.writer_locks[camera_name]:
            if camera_name in self.writers and self.writers[camera_name] is not None:
                try:
                    current_writer = self.writers[camera_name]
                    current_start_time = self.clip_start_times.get(camera_name)

                    if current_start_time:
                        camera_save_dir = os.path.join(self.save_path, camera_name) # Ensure correct path for metadata
                        filename_base = current_start_time.strftime(f"{camera_name}_%Y%m%d_%H%M%S_%f")[:-3]
                        metadata_filepath = os.path.join(camera_save_dir, f"{filename_base}.json")
                        try:
                            with open(metadata_filepath, 'r') as f:
                                metadata = json.load(f)
                        except (FileNotFoundError, json.JSONDecodeError):
                            metadata = {}

                        end_time = datetime.now()
                        duration = (end_time - current_start_time).total_seconds() / 60
                        metadata.update({
                            "timestamp_end": end_time.isoformat(timespec='milliseconds') + 'Z',
                            "duration_minutes": round(duration, 2)
                        })
                        try:
                            with open(metadata_filepath, 'w') as f:
                                json.dump(metadata, f, indent=4)
                        except Exception as e:
                            print(f"ERROR: Could not update metadata on stop for {metadata_filepath}: {e}")

                    current_writer.release()
                    print(f"[{camera_name}] Video writer released.")
                except Exception as e:
                    print(f"ERROR releasing writer for {camera_name}: {e}")
                del self.writers[camera_name]

            if camera_name in self.clip_start_times:
                del self.clip_start_times[camera_name]

            if camera_name in self.frame_queues:
                while not self.frame_queues[camera_name].empty():
                    try:
                        self.frame_queues[camera_name].get_nowait()
                        self.frame_queues[camera_name].task_done()
                    except queue.Empty:
                        break

    def write_metadata(self, filepath, camera_name, start_time, end_time, duration_minutes, avg_fps, resolution, codec, camera_settings):
        metadata = {
            "camera_name": camera_name,
            "timestamp_start": start_time.isoformat(timespec='milliseconds') + 'Z',
            "timestamp_end": end_time.isoformat(timespec='milliseconds') + 'Z' if end_time else None,
            "duration_minutes": duration_minutes,
            "average_fps": round(avg_fps, 2),
            "resolution": resolution,
            "codec": codec,
            "camera_settings_at_start": camera_settings
        }
        try:
            with open(filepath, 'w') as f:
                json.dump(metadata, f, indent=4)
        except Exception as e:
            print(f"ERROR: Could not write metadata to {filepath}: {e}")

    def _get_directory_size_bytes(self, path):
        total_size = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
        return total_size

    def _monitor_disk_space(self):
        while self.running:
            try:
                # The directory size check still applies to the base save_path
                dir_size_bytes = self._get_directory_size_bytes(self.save_path)
                dir_size_gb = dir_size_bytes / (1024**3)

                if dir_size_gb >= self.max_directory_size_gb:
                    print(f"DIRECTORY ALERT: {self.save_path} is using {dir_size_gb:.2f} GB (threshold: {self.max_directory_size_gb} GB). Initiating cleanup.")
                    self._clean_oldest_files(target_bytes=self.max_directory_size_gb * (1024**3 * 0.90))
            except Exception as e:
                print(f"ERROR monitoring directory size for {self.save_path}: {e}")

            time.sleep(self.disk_check_interval)

    def _clean_oldest_files(self, target_bytes):
        # This function needs to consider files within camera subdirectories
        # Use os.path.join(self.save_path, '**', '*.avi') to search recursively
        all_video_files = sorted(glob.glob(os.path.join(self.save_path, '**', '*.avi'), recursive=True))
        files_to_delete = []

        for video_file in all_video_files:
            try:
                # Extract filename base from the full path
                filename_base = os.path.basename(video_file).rsplit('.', 1)[0]
                parts = filename_base.split('_')
                if len(parts) >= 3:
                    dt_string = f"{parts[-2]}_{parts[-1][:6]}"
                    dt_object = datetime.strptime(dt_string, "%Y%m%d_%H%M%S")
                    
                    # Construct metadata file path correctly based on the video_file's directory
                    video_dir = os.path.dirname(video_file)
                    metadata_file = os.path.join(video_dir, f"{filename_base}.json")
                    files_to_delete.append((dt_object, video_file, metadata_file))
                else:
                    print(f"Warning: Filename does not match expected format for timestamp parsing: {video_file}. Skipping.")
            except ValueError as ve:
                print(f"Warning: Could not parse timestamp from filename {video_file} due to format error: {ve}. Skipping.")
            except Exception as e:
                print(f"Warning: An unexpected error occurred while processing {video_file}: {e}. Skipping.")

        files_to_delete.sort(key=lambda x: x[0])

        current_size = self._get_directory_size_bytes(self.save_path)
        for _, video_path, metadata_path in files_to_delete:
            if current_size <= target_bytes:
                break
            try:
                if os.path.exists(video_path):
                    file_size = os.path.getsize(video_path)
                    os.remove(video_path)
                    current_size -= file_size
                    print(f"Deleted video: {os.path.basename(video_path)}")

                if os.path.exists(metadata_path):
                    if os.path.exists(metadata_path):
                        metadata_size = os.path.getsize(metadata_path)
                        os.remove(metadata_path)
                        current_size -= metadata_size
                        print(f"Deleted metadata: {os.path.basename(metadata_path)}")
            except OSError as oe:
                print(f"ERROR deleting file (permissions/locked?): {oe} for {video_path} or {metadata_path}")
            except Exception as e:
                print(f"ERROR deleting {video_path} or its metadata: {e}")

    def start(self, camera_inspectors):
        self.running = True
        self.camera_inspectors = camera_inspectors
        for cam_id, cam_obj in self.camera_inspectors.items():
            cam_name = cam_obj.camera_name
            self.writer_locks[cam_name] = threading.Lock()
            self.clip_switching_in_progress[cam_name] = False

        self.disk_monitor_thread = threading.Thread(target=self._monitor_disk_space)
        self.disk_monitor_thread.daemon = True
        self.disk_monitor_thread.start()
        print("Disk space monitor thread started.")

    def stop(self):
        self.running = False
        print("Stopping video recorder...")

        for cam_name, thread in self.recorder_threads.items():
            if thread and thread.is_alive():
                print(f"Stopping recorder thread for {cam_name}...")
                thread.join(timeout=5.0)
                if thread.is_alive():
                    print(f"Warning: Recorder thread for {cam_name} did not terminate cleanly. Queue size: {self.frame_queues[cam_name].qsize() if cam_name in self.frame_queues else 0}")

        for cam_name in list(self.writers.keys()):
            self.close_writer(cam_name)

        if self.disk_monitor_thread and self.disk_monitor_thread.is_alive():
            print("Stopping disk monitor thread...")
            self.disk_monitor_thread.join(timeout=2.0)
            if self.disk_monitor_thread.is_alive():
                print("Warning: Disk monitor thread did not terminate cleanly.")

        print("Video recorder stopped.")


class MultiCameraInspector:
    def __init__(self, camera_selection=None, max_resolution=(1920, 1080)):
        self.camera_selection = camera_selection
        self.max_resolution = max_resolution
        self.cameras = {} # This will hold CameraInspector instances
        self.running = False
        self.setting_prompt_active = False
        self.adjustment_thread = None
        self.video_recorder = None 
        self.video_playback = None
        # Register graceful exit handler
        atexit.register(self.stop_all_cameras)

    def initialize_cameras(self):
        available_cameras = detect_cameras()
        
        if not available_cameras:
            print("No cameras detected!")
            return False
        
        cameras_to_init = {}
        if self.camera_selection:
            for cam_id in self.camera_selection:
                if cam_id in available_cameras:
                    cameras_to_init[cam_id] = available_cameras[cam_id]
                elif cam_id.startswith('video') and cam_id in [k for k in available_cameras.keys() if k.startswith('video')]:
                    cameras_to_init[cam_id] = available_cameras[cam_id]
                else:
                    print(f"Warning: Requested camera '{cam_id}' not found or not in detected list. Skipping.")
        else:
            cameras_to_init = available_cameras
        
        print(f"\nInitializing {len(cameras_to_init)} cameras...")
        
        if not cameras_to_init:
            print("No cameras selected for initialization based on --cameras argument or detection.")
            return False

        # Create CameraInspector instances first, then link to recorder
        for cam_id, cam_info in cameras_to_init.items():
            try:
                camera = CameraInspector(
                    camera_device=cam_info['path'],
                    camera_name=cam_info['name'],
                    max_resolution=self.max_resolution,
                    real_device_path=cam_info['real_device']
                )
                if camera.start():
                    self.cameras[cam_id] = camera
                    print(f"✓ {cam_info['name']} initialized successfully (Capture thread started)")
                else:
                    print(f"✗ Failed to initialize {cam_info['name']}")
            except Exception as e:
                print(f"✗ Error initializing {cam_info['name']}: {e}")

        if not self.cameras:
            print("No cameras successfully initialized. Exiting.")
            return False

        # Initialize VideoRecorder AFTER cameras are initialized, as it needs their objects
        self.video_recorder = VideoRecorder(
            save_path=VIDEO_SAVE_PATH,
            clip_duration_minutes=CLIP_DURATION_MINUTES,
            directory_threshold_gb=DIRECTORY_THRESHOLD_GB,
            disk_check_interval_seconds=DISK_CHECK_INTERVAL_SECONDS,
            resolution=self.max_resolution,
            camera_inspectors_map=self.cameras # Pass the dict of initialized CameraInspectors
        )
        # Link the recorder back to each camera (recorder will handle starting its own writer threads)
        for cam_id, camera_obj in self.cameras.items():
            camera_obj.recorder = self.video_recorder
        
        # Initialize video playback
        self.video_playback = VideoPlayback(VIDEO_SAVE_PATH)
            
        return len(self.cameras) > 0
    
    def monitor_and_adjust_settings(self):
        while self.running:
            for cam_id, camera in list(self.cameras.items()):
                # Ensure camera is still running before attempting to get frame
                if not camera.running:
                    print(f"[{camera.camera_name}] Camera is not running, skipping adjustment.")
                    continue

                frame_info = camera.get_latest_frame() # Use get_latest_frame to clear queue for display
                if frame_info and frame_info['frame'] is not None:
                    brightness = calculate_brightness_level(frame_info['frame'])
                    adjust_image_settings(camera, brightness)
            time.sleep(ADJUSTMENT_INTERVAL)

    def run_inspection(self):
        # We don't call stop_all_cameras here on exit, atexit handles it.
        # This makes the main loop cleaner.
        
        self.running = True

        if not self.initialize_cameras():
            print("No cameras available to run inspection. Exiting.")
            return # Exit main thread, at exit will handle cleanup

        # Start the adjustment thread
        if self.cameras:
            self.adjustment_thread = threading.Thread(target=self.monitor_and_adjust_settings)
            self.adjustment_thread.daemon = True
            self.adjustment_thread.start()
            print(f"Started automatic image adjustment thread, interval: {ADJUSTMENT_INTERVAL} seconds.")
        
        # Start the video recorder
        self.video_recorder.start(self.cameras) # Now pass the full self.cameras map

        print("\n--- Command Line Controls (while web server runs) ---")
        print("  'q' - Quit")
        print("  'p' - Print current stats")
        print("  'c' - Change camera settings (exposure, gain, etc.)")
        print("  Access camera feeds at http://<your_jetson_ip>:5000")
        if WEB_PASSWORD:
            print("  Password protection enabled via WEB_PASSWORD environment variable")
        else:
            print("  WARNING: No password protection! Set WEB_PASSWORD environment variable to secure access")

        app = Flask(__name__, template_folder='templates')
        app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-change-this')

        # Authentication decorator
        def login_required(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if WEB_PASSWORD is None:
                    return f(*args, **kwargs)  # No password required if not set
                if 'authenticated' not in session or not session['authenticated']:
                    return redirect(url_for('login'))
                return f(*args, **kwargs)
            return decorated_function

        @app.route('/login', methods=['GET', 'POST'])
        def login():
            if WEB_PASSWORD is None:
                return redirect(url_for('index'))  # Skip login if no password set
            
            if request.method == 'POST':
                password = request.form.get('password')
                if password == WEB_PASSWORD:
                    session['authenticated'] = True
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', error="Invalid password")
            return render_template('login.html')

        @app.route('/logout')
        def logout():
            session.pop('authenticated', None)
            return redirect(url_for('login'))

        @app.route('/')
        @login_required
        def index():
            return render_template('index.html', cameras=self.cameras)

        @app.route('/playback')
        @login_required
        def playback():
            videos = self.video_playback.get_video_files()
            return render_template('playback.html', videos=videos)

        @app.route('/video_feed/<camera_id>')
        @login_required
        def video_feed(camera_id):
            camera = self.cameras.get(camera_id)
            if not camera or not camera.running: # Check if camera is running
                return "Camera not found or not active", 404
            return Response(camera.generate_mjpeg_frames(),
                            mimetype='multipart/x-mixed-replace; boundary=frame')

        @app.route('/playback_feed')
        @login_required
        def playback_feed():
            return Response(self.video_playback.generate_mjpeg_frames(),
                            mimetype='multipart/x-mixed-replace; boundary=frame')

        @app.route('/api/videos')
        @login_required
        def api_videos():
            videos = self.video_playback.get_video_files()
            return jsonify(videos)

        @app.route('/api/play_video', methods=['POST'])
        @login_required
        def api_play_video():
            data = request.get_json()
            video_path = data.get('video_path')
            
            if not video_path or not os.path.exists(video_path):
                return jsonify({'success': False, 'error': 'Video file not found'})
            
            # Security check: ensure video path is within our save directory
            if not os.path.abspath(video_path).startswith(os.path.abspath(self.video_playback.save_path)):
                return jsonify({'success': False, 'error': 'Invalid video path'})
            
            print(f"Attempting to load and play video: {video_path}")
            
            # Stop any current playback first
            self.video_playback.stop_playback()
            time.sleep(0.1)  # Brief pause to ensure cleanup
            
            # Load the video
            if not self.video_playback.load_video(video_path):
                return jsonify({'success': False, 'error': 'Failed to load video file'})
            
            # Start playback
            if not self.video_playback.start_playback():
                return jsonify({'success': False, 'error': 'Failed to start video playback'})
            
            print(f"Successfully started playback of {os.path.basename(video_path)}")
            return jsonify({'success': True})
            
        @app.route('/api/stop_playback', methods=['POST'])
        @login_required
        def api_stop_playback():
            self.video_playback.stop_playback()
            return jsonify({'success': True})

        @app.route('/api/playback_info')
        @login_required
        def api_playback_info():
            return jsonify(self.video_playback.get_playback_info())

        @app.route('/download_video/<path:video_path>')
        @login_required
        def download_video(video_path):
            # Security check: ensure video path is within our save directory
            full_path = os.path.join(self.video_playback.save_path, video_path)
            if not os.path.exists(full_path) or not os.path.abspath(full_path).startswith(os.path.abspath(self.video_playback.save_path)):
                return "Video file not found", 404
            
            return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))
        
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR) # Suppress Flask server access logs

        flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False))
        flask_thread.daemon = True
        flask_thread.start()
        print("Flask server started on http://0.0.0.0:5000")

        # Main loop for user input
        while self.running:
            try:
                user_input = input("Enter command ('q', 'p', 'c' for settings): ").strip().lower()
                if user_input == 'q':
                    self.running = False # This will trigger atexit handler
                elif user_input == 'p':
                    print("\n--- Camera Statistics ---")
                    if not self.cameras:
                        print("No cameras active.")
                    for cam_id, camera in self.cameras.items():
                        print(f"\n[{camera.camera_name} ({cam_id})]:")
                        print(f"  FPS: {camera.get_fps():.2f}")
                        print(f"  Total Frames: {camera.frame_count}")
                        print(f"  Dropped Frames: {camera.dropped_frames}")
                        print(f"  Queue Size (Web Stream): {camera.frame_queue.qsize()}")
                        
                        # Also report recorder queue size
                        if camera.camera_name in self.video_recorder.frame_queues:
                            print(f"  Queue Size (Recorder): {self.video_recorder.frame_queues[camera.camera_name].qsize()}")

                        if camera.real_device_path and os.path.exists(camera.real_device_path):
                            print("  Current v4l2-ctl Settings:")
                            for setting_name in ['exposure_time_absolute', 'brightness', 'contrast', 'gain', 'white_balance_temperature', 'auto_exposure', 'white_balance_automatic']:
                                value = camera.get_camera_setting(setting_name)
                                print(f"    {setting_name}: {value}")
                        else:
                            print("  v4l2-ctl settings not available (real device path missing).")

                    # Also print disk usage
                    total, used, free = shutil.disk_usage(VIDEO_SAVE_PATH)
                    used_percent = (used / total) * 100
                    print(f"\nDisk usage for {VIDEO_SAVE_PATH}: {used_percent:.2f}% ({free / (1024**3):.2f} GB free).")
                    print("-------------------------\n")
                elif user_input == 'c':
                    self.setting_prompt_active = True
                    print("\n--- Change Camera Settings ---")
                    if not self.cameras:
                        print("No cameras active to change settings for.")
                        self.setting_prompt_active = False
                        continue

                    print("Available cameras:")
                    for idx, (cam_id, camera) in enumerate(self.cameras.items()):
                        print(f"{idx+1}. {camera.camera_name} ({cam_id})")
                    
                    cam_choice = input("Select camera by number (or 'q' to cancel): ").strip()
                    if cam_choice.lower() == 'q':
                        self.setting_prompt_active = False
                        continue
                    
                    try:
                        cam_index = int(cam_choice) - 1
                        selected_cam_id = list(self.cameras.keys())[cam_index]
                        selected_camera = self.cameras[selected_cam_id]
                    except (ValueError, IndexError):
                        print("Invalid camera selection.")
                        self.setting_prompt_active = False
                        continue

                    print(f"\nChanging settings for {selected_camera.camera_name} ({selected_cam_id}).")
                    print("Available settings and their ranges (from SETTING_RANGES):")
                    for setting_name, s_range in SETTING_RANGES.items():
                        current_val = selected_camera.get_camera_setting(setting_name)
                        if 'min' in s_range and 'max' in s_range:
                            print(f"  {setting_name} (Current: {current_val}, Range: {s_range['min']}-{s_range['max']})")
                        elif 'manual' in s_range:
                             print(f"  {setting_name} (Current: {current_val}, Options: manual={s_range['manual']}, aperture_priority={s_range['aperture_priority']})")
                        elif 'off' in s_range:
                             print(f"  {setting_name} (Current: {current_val}, Options: off={s_range['off']}, on={s_range['on']})")
                        else:
                            print(f"  {setting_name} (Current: {current_val}, Range: Not defined)")

                    setting_name = input("Enter setting name to change (e.g., 'exposure_time_absolute', 'gain', or 'q' to cancel): ").strip().lower()
                    if setting_name.lower() == 'q':
                        self.setting_prompt_active = False
                        continue

                    if setting_name not in SETTING_RANGES:
                        print(f"'{setting_name}' is not a recognized setting or its range is not defined. Please check spelling.")
                        self.setting_prompt_active = False
                        continue
                    
                    if 'manual' in SETTING_RANGES[setting_name] or 'off' in SETTING_RANGES[setting_name]:
                        print(f"Valid options for {setting_name}: {SETTING_RANGES[setting_name]}")
                        value_input = input(f"Enter new value for {setting_name} (e.g., '{SETTING_RANGES[setting_name].get('manual', SETTING_RANGES[setting_name].get('off'))}'): ").strip()
                    else:
                        value_input = input(f"Enter new value for {setting_name} (Current: {selected_camera.get_camera_setting(setting_name)}, Range: {SETTING_RANGES[setting_name].get('min')}-{SETTING_RANGES[setting_name].get('max')}): ").strip()
                    
                    try:
                        new_value = int(value_input)
                    except ValueError:
                        new_value = value_input

                    if selected_camera.set_camera_setting(setting_name, new_value):
                        print(f"Successfully set {setting_name} to {new_value} for {selected_camera.camera_name}.")
                    else:
                        print(f"Failed to set {setting_name} for {selected_camera.camera_name}.")
                    
                    self.setting_prompt_active = False
                else:
                    print("Invalid command. Press 'q' to quit, 'p' to print stats, 'c' to change settings.")
                
                if not self.setting_prompt_active:
                    time.sleep(0.1) # Small delay to prevent busy-waiting loop on input
            
            except EOFError: # Catch Ctrl+D
                print("\nEOF detected (Ctrl+D). Shutting down...")
                self.running = False
            except KeyboardInterrupt:
                print("\nCtrl+C detected. Shutting down...")
                self.running = False
            except Exception as e:
                print(f"An unexpected error occurred in main loop: {e}")
                self.running = False # Exit to allow atexit to clean up

    def stop_all_cameras(self):
        # This function is registered with atexit, so it will be called automatically
        # when the script exits (normal exit, Ctrl+C, unhandled exception).
        if not self.running:
            print("Shutdown already in progress or completed.")
            return

        print("\nInitiating graceful shutdown...")
        self.running = False # Signal all threads to stop

        # Stop video playback
        if self.video_playback:
            self.video_playback.stop_playback()

        # Stop the video recorder BEFORE cameras to ensure all frames are processed and writers are released.
        if self.video_recorder:
            self.video_recorder.stop()
        else:
            print("Video recorder not initialized or already stopped.")

        # Stop all CameraInspector instances and their capture threads
        for cam_id, camera in list(self.cameras.items()): # Iterate on a copy as items might be removed
            try:
                camera.stop()
            except Exception as e:
                print(f"Error stopping camera {cam_id}: {e}")
            del self.cameras[cam_id] # Remove from list once stopped

        if self.adjustment_thread and self.adjustment_thread.is_alive():
            print("Stopping adjustment thread...")
            self.adjustment_thread.join(timeout=2.0)
            if self.adjustment_thread.is_alive():
                print("Warning: Adjustment thread did not terminate cleanly.")
        
        print("All components gracefully stopped and resources released.")


def main():
    parser = argparse.ArgumentParser(description="Multi-Camera Inspector for Jetson Nano with Flask web interface.")
    parser.add_argument('--cameras', nargs='+', help="Specific camera IDs/names to use (e.g., camera_lr video0). If omitted, all detected cameras will be used.")
    parser.add_argument('--width', type=int, default=1920, help="Set the width resolution for cameras.")
    parser.add_argument('--height', type=int, default=1080, help="Set the height resolution for cameras.")
    
    args = parser.parse_args()

    max_resolution = (args.width, args.height)

    inspector = MultiCameraInspector(
        camera_selection=args.cameras,
        max_resolution=max_resolution
    )
    
    # Run inspection will initialize, start threads, and manage the main loop
    inspector.run_inspection()

if __name__ == "__main__":
    # Create HTML templates
    html_index_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Multi-Camera Inspector</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .header {
                background-color: #333;
                color: white;
                padding: 15px;
                margin: -20px -20px 20px -20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .nav-links a {
                color: white;
                text-decoration: none;
                margin-left: 20px;
                padding: 8px 16px;
                background-color: #555;
                border-radius: 4px;
            }
            .nav-links a:hover {
                background-color: #777;
            }
            .camera-container {
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                justify-content: center;
            }
            .camera-card {
                border: 1px solid #ccc;
                padding: 15px;
                box-shadow: 2px 2px 8px rgba(0,0,0,0.1);
                border-radius: 8px;
                background-color: white;
                text-align: center;
                min-width: 320px;
            }
            .camera-card h2 {
                margin-top: 0;
                color: #333;
                border-bottom: 2px solid #007bff;
                padding-bottom: 10px;
            }
            .camera-card img {
                max-width: 100%;
                height: auto;
                border: 2px solid #eee;
                border-radius: 4px;
                margin-top: 10px;
            }
            .status {
                color: #28a745;
                font-weight: bold;
                margin-top: 10px;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Multi-Camera Inspector - Live Feeds</h1>
            <div class="nav-links">
                <a href="/">Live Feeds</a>
                <a href="/playback">Video Playback</a>
                <a href="/logout">Logout</a>
            </div>
        </div>
        
        <div class="camera-container">
            {% for cam_id, camera in cameras.items() %}
            <div class="camera-card">
                <h2>{{ camera.camera_name }} ({{ cam_id }})</h2>
                <img src="{{ url_for('video_feed', camera_id=cam_id) }}" width="640" height="480" alt="Video Feed">
                <div class="status">Status: Live Recording</div>
            </div>
            {% endfor %}
        </div>
        {% if not cameras %}
        <div style="text-align: center; margin-top: 50px;">
            <h2>No cameras are currently active or detected.</h2>
        </div>
        {% endif %}
    </body>
    </html>
    """
    html_playback_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Playback - Multi-Camera Inspector</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .header {
                background-color: #333;
                color: white;
                padding: 15px;
                margin: -20px -20px 20px -20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .nav-links a {
                color: white;
                text-decoration: none;
                margin-left: 20px;
                padding: 8px 16px;
                background-color: #555;
                border-radius: 4px;
            }
            .nav-links a:hover {
                background-color: #777;
            }
            .playback-container {
                display: flex;
                gap: 20px;
                margin-top: 20px;
            }
            .video-player {
                flex: 1;
                background-color: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 2px 2px 8px rgba(0,0,0,0.1);
            }
            .video-list {
                width: 400px;
                background-color: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 2px 2px 8px rgba(0,0,0,0.1);
                max-height: 600px;
                overflow-y: auto;
            }
            .video-feed {
                width: 100%;
                max-width: 800px;
                height: 600px;
                border: 2px solid #eee;
                border-radius: 4px;
                margin-bottom: 20px;
            }
            .controls {
                text-align: center;
                margin: 20px 0;
            }
            .btn {
                background-color: #007bff;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                margin: 0 5px;
            }
            .btn:hover {
                background-color: #0056b3;
            }
            .btn-danger {
                background-color: #dc3545;
            }
            .btn-danger:hover {
                background-color: #c82333;
            }
            .camera-section {
                margin-bottom: 30px;
                border: 1px solid #ddd;
                border-radius: 6px;
                overflow: hidden;
            }
            .camera-header {
                background-color: #007bff;
                color: white;
                padding: 15px;
                font-weight: bold;
            }
            .video-item {
                padding: 10px;
                border-bottom: 1px solid #eee;
                cursor: pointer;
                transition: background-color 0.2s;
            }
            .video-item:hover {
                background-color: #f8f9fa;
            }
            .video-item:last-child {
                border-bottom: none;
            }
            .video-filename {
                font-weight: bold;
                color: #333;
            }
            .video-details {
                font-size: 12px;
                color: #666;
                margin-top: 5px;
            }
            .playback-info {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 15px;
                margin-bottom: 20px;
            }
            .progress-bar {
                width: 100%;
                height: 20px;
                background-color: #e9ecef;
                border-radius: 10px;
                overflow: hidden;
                margin: 10px 0;
            }
            .progress-fill {
                height: 100%;
                background-color: #007bff;
                transition: width 0.3s ease;
            }
            .download-btn {
                background-color: #28a745;
                font-size: 12px;
                padding: 5px 10px;
                margin-left: 10px;
            }
            .download-btn:hover {
                background-color: #218838;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Multi-Camera Inspector - Video Playback</h1>
            <div class="nav-links">
                <a href="/">Live Feeds</a>
                <a href="/playback">Video Playback</a>
                <a href="/logout">Logout</a>
            </div>
        </div>

        <div class="playback-container">
            <div class="video-player">
                <h2>Video Player</h2>
                <img id="videoFeed" class="video-feed" src="/playback_feed" alt="Video Playback">
                
                <div class="playback-info" id="playbackInfo">
                    <strong>No video selected</strong>
                </div>
                
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill" style="width: 0%"></div>
                </div>
                
                <div class="controls">
                    <button class="btn btn-danger" onclick="stopPlayback()">Stop Playback</button>
                    <button class="btn" onclick="refreshVideoList()">Refresh Video List</button>
                </div>
            </div>

            <div class="video-list">
                <h2>Available Videos</h2>
                <div id="videoListContainer">
                    {% for camera_name, video_files in videos.items() %}
                    <div class="camera-section">
                        <div class="camera-header">{{ camera_name }}</div>
                        {% for video in video_files %}
                        <div class="video-item" onclick="playVideo('{{ video.path }}')">
                            <div class="video-filename">{{ video.filename }}</div>
                            <div class="video-details">
                                {{ video.timestamp.strftime('%Y-%m-%d %H:%M:%S') }} | {{ video.size_mb }} MB
                                {% if video.metadata.duration_minutes %}
                                | {{ "%.1f"|format(video.metadata.duration_minutes) }} min
                                {% endif %}
                                <button class="btn download-btn" onclick="event.stopPropagation(); downloadVideo('{{ camera_name }}/{{ video.filename }}')">Download</button>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    {% endfor %}
                </div>
                {% if not videos %}
                <p>No video files found in {{ VIDEO_SAVE_PATH }}</p>
                {% endif %}
            </div>
        </div>

        <script>
            function playVideo(videoPath) {
                fetch('/api/play_video', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({video_path: videoPath})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        console.log('Video playback started');
                        updatePlaybackInfo();
                    } else {
                        alert('Failed to start video: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('Error starting video playback');
                });
            }

            function stopPlayback() {
                fetch('/api/stop_playback', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        console.log('Playback stopped');
                        updatePlaybackInfo();
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                });
            }

            function downloadVideo(videoPath) {
                window.open('/download_video/' + videoPath, '_blank');
            }

            function refreshVideoList() {
                location.reload();
            }

            function updatePlaybackInfo() {
                fetch('/api/playback_info')
                .then(response => response.json())
                .then(data => {
                    const infoDiv = document.getElementById('playbackInfo');
                    const progressFill = document.getElementById('progressFill');
                    
                    if (data.current_video && data.playing) {
                        infoDiv.innerHTML = `
                            <strong>Playing:</strong> ${data.current_video}<br>
                            <strong>Frame:</strong> ${data.current_frame} / ${data.total_frames}<br>
                            <strong>FPS:</strong> ${data.fps.toFixed(1)}
                        `;
                        progressFill.style.width = data.progress_percent.toFixed(1) + '%';
                    } else if (data.current_video) {
                        infoDiv.innerHTML = `<strong>Loaded:</strong> ${data.current_video} (stopped)`;
                        progressFill.style.width = '0%';
                    } else {
                        infoDiv.innerHTML = '<strong>No video selected</strong>';
                        progressFill.style.width = '0%';
                    }
                })
                .catch(error => {
                    console.error('Error updating playback info:', error);
                });
            }

            // Update playback info every second
            setInterval(updatePlaybackInfo, 1000);
            
            // Initial update
            updatePlaybackInfo();
        </script>
    </body>
    </html>
    """

    html_login_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - Multi-Camera Inspector</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f5f5f5;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .login-container {
                background-color: white;
                padding: 40px;
                border-radius: 8px;
                box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
                width: 300px;
                text-align: center;
            }
            h1 {
                color: #333;
                margin-bottom: 30px;
            }
            input[type="password"] {
                width: 100%;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
                margin-bottom: 20px;
                box-sizing: border-box;
            }
            .btn {
                background-color: #007bff;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                width: 100%;
            }
            .btn:hover {
                background-color: #0056b3;
            }
            .error {
                color: #dc3545;
                margin-top: 15px;
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <h1>Camera Inspector</h1>
            <form method="post">
                <input type="password" name="password" placeholder="Enter password" required>
                <button type="submit" class="btn">Login</button>
                {% if error %}
                <div class="error">{{ error }}</div>
                {% endif %}
            </form>
        </div>
    </body>
    </html>
    """
    
    template_dir = 'templates'
    os.makedirs(template_dir, exist_ok=True)

    # Write all template files
    with open(os.path.join(template_dir, 'index.html'), 'w') as f:
        f.write(html_index_template)
    
    with open(os.path.join(template_dir, 'playback.html'), 'w') as f:
        f.write(html_playback_template)
    
    with open(os.path.join(template_dir, 'login.html'), 'w') as f:
        f.write(html_login_template)
    
    # Check for password configuration
    if WEB_PASSWORD is None:
        print("WARNING: No WEB_PASSWORD environment variable set. Web interface will be unprotected!")
        print("Set WEB_PASSWORD environment variable to enable authentication.")
        print("Example: export WEB_PASSWORD='your_secure_password'")
    else:
        print("Password protection enabled for web interface.")
    
    main()