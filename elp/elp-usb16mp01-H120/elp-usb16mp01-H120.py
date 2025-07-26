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
from datetime import datetime
import queue
import argparse
from collections import deque
import glob
import subprocess # Import for v4l2-ctl
import sys

# Flask imports for web server
from flask import Flask, Response, render_template

# --- Configuration Constants ---
ADJUSTMENT_INTERVAL = 1  # Seconds between image adjustments
BRIGHTNESS_TARGET_LOW = 90 # Target average pixel value for "not too dark"
BRIGHTNESS_TARGET_HIGH = 110 # Target average pixel value for "not too bright"
ADJUSTMENT_STEP_EXPOSURE = 25 # Base amount to change exposure by
ADJUSTMENT_STEP_BRIGHTNESS = 5 # Base amount to change brightness by
ADJUSTMENT_STEP_CONTRAST = 5 # Base amount to change contrast by
ADJUSTMENT_STEP_GAIN = 15 # Base amount to change gain by

# NEW: Scaling factor for dynamic adjustments
BRIGHTNESS_DEVIATION_SCALE = 0.5 # Adjust this value: higher means more aggressive scaling

# Define common camera setting ranges (these are typical, might need fine-tuning for your specific camera)
# !!! UPDATED BASED ON v4l2-ctl -d /dev/video2 -L OUTPUT !!!
SETTING_RANGES = {
    'auto_exposure': {'manual': 1, 'aperture_priority': 3}, # Your camera uses 1 for Manual, 3 for Aperture Priority
    'exposure_time_absolute': {'min': 1, 'max': 5000}, # Correct name and range
    'brightness': {'min': -64, 'max': 64}, # Correct range
    'contrast': {'min': 0, 'max': 64}, # Correct range
    'saturation': {'min': 0, 'max': 128},
    'hue': {'min': -40, 'max': 40},
    'gamma': {'min': 72, 'max': 500},
    'gain': {'min': 0, 'max': 100}, # Correct range
    'power_line_frequency': {'disabled': 0, '50hz': 1, '60hz': 2},
    'white_balance_automatic': {'off': 0, 'on': 1}, # Correct name and boolean values
    'white_balance_temperature': {'min': 2800, 'max': 6500}, # This is inactive when auto is on
    'sharpness': {'min': 0, 'max': 6},
    'backlight_compensation': {'min': 0, 'max': 2},
    'pan_absolute': {'min': -36000, 'max': 36000}, # If your camera supports it
    'tilt_absolute': {'min': -36000, 'max': 36000}, # If your camera supports it
    'zoom_absolute': {'min': 0, 'max': 9}, # If your camera supports it
}

# --- Default Camera Settings ---
DEFAULT_CAMERA_SETTINGS = {
    'exposure_time_absolute': 500,  # A moderate exposure time (e.g., 100-1000)
    'brightness': 0,                # Neutral brightness
    'contrast': 32,                 # Mid-range contrast
    'gain': 0,                      # Low gain to reduce noise, increased by auto-adjust if needed
    'white_balance_temperature': 4000 # A neutral white balance temperature, if auto WB is off
}


class CameraInspector:
    def __init__(self, camera_device, camera_name, save_path=None, max_resolution=(1920, 1080), real_device_path=None):
        self.camera_device = camera_device  # Can be device path or index (e.g., /dev/camera_lr)
        self.camera_name = camera_name      # Human readable name
        self.save_path = save_path
        self.max_resolution = max_resolution
        self.real_device_path = real_device_path # Actual /dev/videoX path for v4l2-ctl
        self.cap = None
        self.frame_queue = queue.Queue(maxsize=30) # Increased queue size significantly
        self.fps_counter = deque(maxlen=30)  # Store last 30 frame times
        self.running = False
        self.capture_thread = None
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.dropped_frames = 0
        
    def initialize_camera(self):
        """Initialize camera with optimal settings for Jetson Nano"""
        print(f"Initializing {self.camera_name} ({self.camera_device})...")
        
        # Determine the numeric device ID if using a symlink like /dev/camera_lr
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
                device_identifier = self.camera_device # Fallback to direct path string (less reliable for some backends)
        else:
            device_identifier = self.camera_device # Assume it's an integer index

        if device_identifier is None:
            print(f"Error: Could not determine camera device identifier for {self.camera_name}.")
            return False

        # Try opening with CAP_V4L2 first, then CAP_ANY
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
        
        for backend in backends:
            print(f"Attempting to open {self.camera_name} with backend: {backend} (ID: {device_identifier})...")
            self.cap = cv2.VideoCapture(device_identifier, backend)
            
            if self.cap.isOpened():
                # Test if we can actually read a frame
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    print(f"{self.camera_name} opened successfully and read test frame with backend: {backend}.")
                    break # Success, break out of backend loop
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
        
        # --- Crucial Order: Set MJPEG FOURCC, then resolution, then FPS ---
        # This order is often critical for V4L2 devices to negotiate correctly.
        try:
            # MJPG is the FourCC for MJPEG format
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            print(f"{self.camera_name}: Attempted to set FOURCC to MJPG.")
        except Exception as e:
            print(f"Warning: Could not set FOURCC for {self.camera_name}: {e}")

        width, height = self.max_resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)  # Target 30 FPS (adjust lower if still seeing timeouts)
        
        # Removed CAP_PROP_BUFFERSIZE = 1: Let OpenCV manage its default buffer, which is often more robust.
        
        # --- Attempt to disable auto exposure/white balance immediately via v4l2-ctl ---
        # This is often more reliable and persistent for ELP cameras than OpenCV properties.
        if self.real_device_path and os.path.exists(self.real_device_path):
            try:
                # !!! UPDATED: Control name is 'auto_exposure', and 'manual' mode is 1 !!!
                if self.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['manual']):
                    print(f"{self.camera_name}: Auto-exposure disabled (set to manual).")
                else:
                    print(f"{self.camera_name}: Could not set auto_exposure to manual via v4l2-ctl.")

                # !!! UPDATED: Control name is 'white_balance_automatic' !!!
                if self.set_camera_setting('white_balance_automatic', SETTING_RANGES['white_balance_automatic']['off']):
                    print(f"{self.camera_name}: Auto-white balance disabled.")
                else:
                    print(f"{self.camera_name}: Could not set white_balance_automatic to off via v4l2-ctl.")
                time.sleep(0.1) # Give camera time to apply settings
            except Exception as e:
                print(f"Error attempting initial v4l2-ctl settings for {self.camera_name}: {e}")
        else:
            print(f"Warning: Real device path '{self.real_device_path}' not available or does not exist for {self.camera_name}. Cannot set v4l2-ctl properties.")

        # Get and print actual camera settings after attempts
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        print(f"{self.camera_name} - Actual Resolution: {actual_width}x{actual_height}, Actual FPS: {actual_fps}")
        
        return True
    
    def set_default_camera_settings(self):
        """
        Sets predefined default settings for the camera using v4l2-ctl.
        This is called once upon initialization.
        """
        if not self.real_device_path or not os.path.exists(self.real_device_path):
            print(f"[{self.camera_name}] Cannot set default settings: real device path not available.")
            return

        print(f"[{self.camera_name}] Applying default camera settings...")

        # Ensure auto exposure is manual and auto white balance is off first
        self.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['manual'])
        self.set_camera_setting('white_balance_automatic', SETTING_RANGES['white_balance_automatic']['off'])
        time.sleep(0.1) # Give camera time to switch modes

        for setting, default_value in DEFAULT_CAMERA_SETTINGS.items():
            # Check if the setting is valid for this camera (optional, but good for robustness)
            if setting in SETTING_RANGES:
                # Clamp the default value to the defined range
                min_val = SETTING_RANGES[setting].get('min', default_value)
                max_val = SETTING_RANGES[setting].get('max', default_value)
                clamped_value = max(min_val, min(default_value, max_val))
                
                if self.set_camera_setting(setting, clamped_value):
                    print(f"[{self.camera_name}] Set default {setting} to {clamped_value}.")
                else:
                    print(f"[{self.camera_name}] Failed to set default {setting} to {clamped_value}.")
            else:
                print(f"[{self.camera_name}] Warning: Default setting '{setting}' not in SETTING_RANGES, skipping.")
        time.sleep(0.2) # Small pause after applying all defaults


    def set_camera_setting(self, setting_name, value):
        """
        Set a camera property using v4l2-ctl.
        Requires the actual /dev/videoX path.
        Example setting_name: 'auto_exposure', 'exposure_time_absolute', 'brightness', etc.
        """
        if not self.real_device_path or not os.path.exists(self.real_device_path):
            return False

        try:
            # Handle specific control interactions for manual/auto modes
            # !!! UPDATED: Control name is 'exposure_time_absolute' and 'auto_exposure' !!!
            if setting_name == 'exposure_time_absolute':
                # Ensure auto exposure is set to manual mode (1 for your ELP)
                if self.get_camera_setting('auto_exposure') != SETTING_RANGES['auto_exposure']['manual']:
                    self.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['manual'])
                    time.sleep(0.05) # Give it a moment to switch modes
            # !!! UPDATED: Control name is 'white_balance_temperature' and 'white_balance_automatic' !!!
            elif setting_name == 'white_balance_temperature':
                # Ensure auto WB is off
                if self.get_camera_setting('white_balance_automatic') != SETTING_RANGES['white_balance_automatic']['off']:
                    self.set_camera_setting('white_balance_automatic', SETTING_RANGES['white_balance_automatic']['off'])
                    time.sleep(0.05) # Give it a moment

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
        """
        Get a camera property using v4l2-ctl.
        Requires the actual /dev/videoX path.
        """
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
                        return value_str # Return as string if not an int
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
        """Capture frames in a separate thread"""
        while self.running:
            ret, frame = self.cap.read()
            current_time = time.time()
            
            if ret and frame is not None:
                self.frame_count += 1
                self.fps_counter.append(current_time)
                
                # Try to put frame in queue, drop if full
                try:
                    self.frame_queue.put_nowait((frame, current_time))
                except queue.Full:
                    self.dropped_frames += 1
                    
            else:
                time.sleep(0.01)
    
    def get_fps(self):
        """Calculate current FPS based on recent frames"""
        if len(self.fps_counter) < 2:
            return 0.0
        
        time_span = self.fps_counter[-1] - self.fps_counter[0]
        if time_span > 0:
            return (len(self.fps_counter) - 1) / time_span
        return 0.0
    
    def get_frame_info(self):
        """Get current frame and statistics (non-blocking)"""
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
        """Get the most recent frame, clearing the queue to get the freshest for analysis."""
        frame = None
        timestamp = None
        # Consume all frames in queue to get the latest one
        while not self.frame_queue.empty():
            try:
                frame, timestamp = self.frame_queue.get_nowait()
            except queue.Empty:
                break
        if frame is not None:
            return {'frame': frame, 'timestamp': timestamp}
        return None

    def generate_mjpeg_frames(self):
        """Generate JPEG frames for MJPEG streaming."""
        while self.running:
            frame_info = self.get_frame_info() # Get frame from queue
            if frame_info and frame_info['frame'] is not None:
                ret, jpeg = cv2.imencode('.jpg', frame_info['frame'], [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if not ret:
                    time.sleep(0.005) # Small sleep on encode failure
                    continue
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            else:
                time.sleep(0.01) # Wait a bit if no frame available
    
    def start(self):
        """Start camera capture"""
        if not self.initialize_camera():
            return False
        
        # NEW: Set default settings immediately after camera initialization but before starting capture
        self.set_default_camera_settings()
            
        self.running = True
        self.capture_thread = threading.Thread(target=self.capture_frames)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        print(f"{self.camera_name} capture thread started.")
        return True
    
    def stop(self):
        """Stop camera capture"""
        self.running = False
        if self.capture_thread:
            print(f"Stopping {self.camera_name} capture thread...")
            self.capture_thread.join(timeout=2.0)
            if self.capture_thread.is_alive():
                print(f"Warning: {self.camera_name} capture thread did not terminate cleanly.")
        if self.cap:
            self.cap.release()
            print(f"{self.camera_name} camera released.")
    
    def save_frame(self, frame, timestamp):
        """Save frame to SD card"""
        if self.save_path:
            filename = f"{self.camera_name}_{datetime.fromtimestamp(timestamp).strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = os.path.join(self.save_path, filename)
            try:
                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return filepath
            except Exception as e:
                print(f"Error saving frame for {self.camera_name} to {filepath}: {e}")
        return None

def detect_cameras():
    """Detect available cameras using the udev naming scheme and standard video devices."""
    cameras = {}
    
    # Define camera mappings based on your udev rules (adjust as needed based on your actual rules)
    camera_mappings = {
        'camera_lr': 'Lower Right',
        'camera_ur': 'Upper Right', 
        'camera_ul': 'Upper Left',
        'camera_ll': 'Lower Left'
    }
    
    print("Detecting cameras...")
    
    # Check for named camera devices first
    for device_name, display_name in camera_mappings.items():
        device_path = f"/dev/{device_name}"
        if os.path.exists(device_path):
            real_device = os.path.realpath(device_path)
            # Verify if the real device is an actual /dev/videoX device
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
    
    # If not all mapped cameras are found, or no mappings exist, check standard video devices
    video_devices = sorted(glob.glob("/dev/video*"))
    for device in video_devices:
        # Check if this device is already mapped by udev or is part of a mapped camera
        already_mapped = False
        for cam_info in cameras.values():
            if cam_info['real_device'] == device:
                already_mapped = True
                break
        
        if already_mapped:
            continue # Skip if already handled by udev rules

        # Attempt to get Vendor/Product ID to identify ELP cameras
        vendor_id = None
        product_id = None
        try:
            # Use udevadm to get attributes.
            udevadm_output = subprocess.check_output(['udevadm', 'info', '--name', device, '--attribute-walk'], text=True)
            for line in udevadm_output.splitlines():
                if 'ATTRS{idVendor}' in line:
                    vendor_id = line.split('==')[1].strip().strip('"')
                if 'ATTRS{idProduct}' in line:
                    product_id = line.split('==')[1].strip().strip('"')
                if vendor_id and product_id:
                    break

            # Your ELP camera vendor/product ID. This should be '32e4:0298' based on your previous logs.
            if vendor_id == "32e4" and product_id == "0298": 
                # This appears to be an ELP camera, and it's not mapped by symlink
                device_num = int(device.split('video')[1])
                generic_name = f"ELP Camera {device_num}"
                print(f"✓ Found unmapped ELP device: {device} (Assigned name: {generic_name})")
                cameras[f"video{device_num}"] = {
                    'path': device, # Use the direct path for consistency
                    'name': generic_name,
                    'real_device': device
                }
        except subprocess.CalledProcessError:
            pass 
        except Exception as e:
            pass

    if not cameras:
        print("No cameras detected at all. Please check connections, udev rules, and permissions.")
        
    return cameras

def calculate_brightness_level(frame):
    """
    Calculate the average brightness level of an image.
    A higher value indicates a brighter image.
    """
    if frame is None or frame.size == 0:
        return 0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return np.mean(gray)

def adjust_image_settings(camera: CameraInspector, current_brightness: float):
    """
    Automatically adjusts camera settings (exposure, brightness, contrast, gain)
    based on the current image brightness level. Prioritizes mixing adjustments,
    with larger steps when deviation from target is high.
    """
    cam_name = camera.camera_name
    real_device = camera.real_device_path

    if not real_device or not os.path.exists(real_device):
        return
    """
    # Ensure camera is in manual exposure mode for adjustments
    if camera.get_camera_setting('auto_exposure') != SETTING_RANGES['auto_exposure']['aperture_priority']:
        camera.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['aperture_priority'])
        time.sleep(0.05) # Give camera time to apply change
    """
    # Ensure camera is in manual exposure mode for adjustments
    if camera.get_camera_setting('auto_exposure') != SETTING_RANGES['auto_exposure']['manual']:
        camera.set_camera_setting('auto_exposure', SETTING_RANGES['auto_exposure']['manual'])
        time.sleep(0.05) # Give camera time to apply change
    adjusted_any_setting = False

    # Get current settings and their ranges
    current_exposure = camera.get_camera_setting('exposure_time_absolute')
    exposure_min = SETTING_RANGES.get('exposure_time_absolute', {}).get('min', 1)
    exposure_max = SETTING_RANGES.get('exposure_time_absolute', {}).get('max', 5000)

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
        # Image is too dark: Increase exposure, brightness, contrast, gain
        deviation = BRIGHTNESS_TARGET_LOW - current_brightness
        # Calculate dynamic step size, ensuring it's at least the base step
        dynamic_step_exposure = max(ADJUSTMENT_STEP_EXPOSURE, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_EXPOSURE / 50)))
        dynamic_step_brightness = max(ADJUSTMENT_STEP_BRIGHTNESS, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_BRIGHTNESS / 10)))
        dynamic_step_contrast = max(ADJUSTMENT_STEP_CONTRAST, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_CONTRAST / 10)))
        dynamic_step_gain = max(ADJUSTMENT_STEP_GAIN, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_GAIN / 5)))
        
        if current_exposure is not None and current_exposure < exposure_max:
            new_exposure = min(current_exposure + dynamic_step_exposure, exposure_max)
            if camera.set_camera_setting('exposure_time_absolute', new_exposure):
                print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc exposure ({dynamic_step_exposure}): {current_exposure}->{new_exposure}.")
                adjusted_any_setting = True

        if current_brightness_val is not None and current_brightness_val < brightness_max:
            new_val = min(current_brightness_val + dynamic_step_brightness, brightness_max)
            if camera.set_camera_setting('brightness', new_val):
                print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc brightness ({dynamic_step_brightness}): {current_brightness_val}->{new_val}.")
                adjusted_any_setting = True

        if current_contrast is not None and current_contrast < contrast_max:
            new_val = min(current_contrast + dynamic_step_contrast, contrast_max)
            if camera.set_camera_setting('contrast', new_val):
                print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc contrast ({dynamic_step_contrast}): {current_contrast}->{new_val}.")
                adjusted_any_setting = True
            
        if current_gain is not None and current_gain < gain_max:
            new_val = min(current_gain + dynamic_step_gain, gain_max)
            if camera.set_camera_setting('gain', new_val):
                print(f"[{cam_name}] Dark ({current_brightness:.2f}). Inc gain ({dynamic_step_gain}): {current_gain}->{new_val}.")
                adjusted_any_setting = True

    elif current_brightness > BRIGHTNESS_TARGET_HIGH:
        # Image is too bright: Decrease exposure, brightness, contrast, gain
        deviation = current_brightness - BRIGHTNESS_TARGET_HIGH
        # Calculate dynamic step size, ensuring it's at least the base step
        dynamic_step_exposure = max(ADJUSTMENT_STEP_EXPOSURE, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_EXPOSURE / 50)))
        dynamic_step_brightness = max(ADJUSTMENT_STEP_BRIGHTNESS, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_BRIGHTNESS / 10)))
        dynamic_step_contrast = max(ADJUSTMENT_STEP_CONTRAST, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_CONTRAST / 10)))
        dynamic_step_gain = max(ADJUSTMENT_STEP_GAIN, int(deviation * BRIGHTNESS_DEVIATION_SCALE * (ADJUSTMENT_STEP_GAIN / 5)))

        if current_exposure is not None and current_exposure > exposure_min:
            new_exposure = max(current_exposure - dynamic_step_exposure, exposure_min)
            if camera.set_camera_setting('exposure_time_absolute', new_exposure):
                print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec exposure ({dynamic_step_exposure}): {current_exposure}->{new_exposure}.")
                adjusted_any_setting = True

        if current_brightness_val is not None and current_brightness_val > brightness_min:
            new_val = max(current_brightness_val - dynamic_step_brightness, brightness_min)
            if camera.set_camera_setting('brightness', new_val):
                print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec brightness ({dynamic_step_brightness}): {current_brightness_val}->{new_val}.")
                adjusted_any_setting = True

        if current_contrast is not None and current_contrast > contrast_min:
            new_val = max(current_contrast - dynamic_step_contrast, contrast_min)
            if camera.set_camera_setting('contrast', new_val):
                print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec contrast ({dynamic_step_contrast}): {current_contrast}->{new_val}.")
                adjusted_any_setting = True
            
        if current_gain is not None and current_gain > gain_min:
            new_val = max(current_gain - dynamic_step_gain, gain_min)
            if camera.set_camera_setting('gain', new_val):
                print(f"[{cam_name}] Bright ({current_brightness:.2f}). Dec gain ({dynamic_step_gain}): {current_gain}->{new_val}.")
                adjusted_any_setting = True

    if not adjusted_any_setting:
        print(f"[{cam_name}] Brightness within target range or no further adjustment possible.")


class MultiCameraInspector:
    def __init__(self, camera_selection=None, save_path=None, max_resolution=(1920, 1080)):
        self.camera_selection = camera_selection  # Specific cameras to use
        self.save_path = save_path
        self.max_resolution = max_resolution
        self.cameras = {}
        self.running = False
        self.setting_prompt_active = False # Flag to manage setting input
        self.adjustment_thread = None
        
        # Create save directory if specified
        if self.save_path:
            os.makedirs(self.save_path, exist_ok=True)
            print(f"Saving frames to: {self.save_path}")
    
    def initialize_cameras(self):
        """Initialize selected cameras"""
        available_cameras = detect_cameras()
        
        if not available_cameras:
            print("No cameras detected!")
            return False
        
        # Determine which cameras to initialize
        cameras_to_init = {}
        if self.camera_selection:
            for cam_id in self.camera_selection:
                # Allow using 'videoX' directly from command line if udev rules aren't perfect
                if cam_id in available_cameras:
                    cameras_to_init[cam_id] = available_cameras[cam_id]
                elif cam_id.startswith('video') and cam_id in [k for k in available_cameras.keys() if k.startswith('video')]:
                    # If user specifies 'video0' and it's detected as such
                    cameras_to_init[cam_id] = available_cameras[cam_id]
                else:
                    print(f"Warning: Requested camera '{cam_id}' not found or not in detected list. Skipping.")
        else:
            # Use all available cameras if no specific selection
            cameras_to_init = available_cameras
        
        print(f"\nInitializing {len(cameras_to_init)} cameras...")
        
        if not cameras_to_init:
            print("No cameras selected for initialization based on --cameras argument or detection.")
            return False

        for cam_id, cam_info in cameras_to_init.items():
            try:
                camera = CameraInspector(
                    camera_device=cam_info['path'],
                    camera_name=cam_info['name'],
                    save_path=self.save_path,
                    max_resolution=self.max_resolution,
                    real_device_path=cam_info['real_device'] # Pass the real device path
                )
                if camera.start(): # The .start() method now calls set_default_camera_settings
                    self.cameras[cam_id] = camera
                    print(f"✓ {cam_info['name']} initialized successfully")
                else:
                    print(f"✗ Failed to initialize {cam_info['name']}")
            except Exception as e:
                print(f"✗ Error initializing {cam_info['name']}: {e}")
        
        print(f"Successfully initialized {len(self.cameras)} out of {len(cameras_to_init)} cameras")
        return len(self.cameras) > 0
    
    def monitor_and_adjust_settings(self):
        """Thread function to periodically monitor and adjust camera settings."""
        while self.running:
            for cam_id, camera in list(self.cameras.items()): # Iterate over a copy to avoid modification issues
                frame_info = camera.get_latest_frame() # Get the freshest frame for analysis
                if frame_info and frame_info['frame'] is not None:
                    brightness = calculate_brightness_level(frame_info['frame'])
                    adjust_image_settings(camera, brightness)
            time.sleep(ADJUSTMENT_INTERVAL)

    def run_inspection(self):
        """Starts camera initialization and the Flask web server."""
        if not self.initialize_cameras():
            print("No cameras available to run inspection. Exiting.")
            sys.exit(1) # Exit if no cameras found
        
        self.running = True

        # Start the adjustment thread
        if self.cameras: # Only start if there are cameras to adjust
            self.adjustment_thread = threading.Thread(target=self.monitor_and_adjust_settings)
            self.adjustment_thread.daemon = True
            self.adjustment_thread.start()
            print(f"Started automatic image adjustment thread, interval: {ADJUSTMENT_INTERVAL} seconds.")
        
        print("\n--- Command Line Controls (while web server runs) ---")
        print("  'q' - Quit")
        print("  's' - Save current frames")
        print("  'r' - Reset frame counters")
        print("  'p' - Print current stats")
        print("  'c' - Change camera settings (exposure, gain, etc.)")
        print("  Access camera feeds at http://<your_jetson_ip>:5000")

        # Start Flask app in a separate thread to allow CLI interaction in the main thread
        app = Flask(__name__, template_folder='templates')

        @app.route('/')
        def index():
            return render_template('index.html', cameras=self.cameras)

        @app.route('/video_feed/<camera_id>')
        def video_feed(camera_id):
            camera = self.cameras.get(camera_id)
            if not camera:
                return "Camera not found", 404
            return Response(camera.generate_mjpeg_frames(),
                            mimetype='multipart/x-mixed-replace; boundary=frame')
        
        # Suppress Flask's default logging to keep terminal cleaner
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR) # Only show errors for Flask server

        flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False))
        flask_thread.daemon = True # Daemonize thread so it exits with main program
        flask_thread.start()
        print("Flask server started on http://0.0.0.0:5000")

        # Main loop for CLI interaction
        try:
            while self.running:
                user_input = input("Enter command ('q', 's', 'r', 'p', 'c' for settings): ").strip().lower()
                if user_input == 'q':
                    self.running = False
                elif user_input == 's':
                    print("Saving current frames for all active cameras...")
                    for cam_id, camera in self.cameras.items():
                        frame_info = camera.get_latest_frame()
                        if frame_info and frame_info['frame'] is not None:
                            filepath = camera.save_frame(frame_info['frame'], frame_info['timestamp'])
                            if filepath:
                                print(f"  {camera.camera_name}: Frame saved to {filepath}")
                            else:
                                print(f"  {camera.camera_name}: Failed to save frame.")
                elif user_input == 'r':
                    print("Resetting frame counters for all cameras.")
                    for cam_id, camera in self.cameras.items():
                        camera.frame_count = 0
                        camera.dropped_frames = 0
                        camera.fps_counter.clear()
                    print("Counters reset.")
                elif user_input == 'p':
                    print("\n--- Camera Statistics ---")
                    if not self.cameras:
                        print("No cameras active.")
                    for cam_id, camera in self.cameras.items():
                        print(f"\n[{camera.camera_name} ({cam_id})]:")
                        print(f"  FPS: {camera.get_fps():.2f}")
                        print(f"  Total Frames: {camera.frame_count}")
                        print(f"  Dropped Frames: {camera.dropped_frames}")
                        print(f"  Queue Size: {camera.frame_queue.qsize()}")
                        
                        # Get and print current camera settings
                        if camera.real_device_path and os.path.exists(camera.real_device_path):
                            print("  Current v4l2-ctl Settings:")
                            for setting_name in ['exposure_time_absolute', 'brightness', 'contrast', 'gain', 'white_balance_temperature', 'auto_exposure', 'white_balance_automatic']:
                                value = camera.get_camera_setting(setting_name)
                                print(f"    {setting_name}: {value}")
                        else:
                            print("  v4l2-ctl settings not available (real device path missing).")

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
                        elif 'manual' in s_range: # For auto_exposure
                             print(f"  {setting_name} (Current: {current_val}, Options: manual={s_range['manual']}, aperture_priority={s_range['aperture_priority']})")
                        elif 'off' in s_range: # For white_balance_automatic
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
                    
                    # Special handling for boolean/enum settings
                    if 'manual' in SETTING_RANGES[setting_name] or 'off' in SETTING_RANGES[setting_name]:
                        print(f"Valid options for {setting_name}: {SETTING_RANGES[setting_name]}")
                        value_input = input(f"Enter new value for {setting_name} (e.g., '{SETTING_RANGES[setting_name].get('manual', SETTING_RANGES[setting_name].get('off'))}'): ").strip()
                    else:
                        value_input = input(f"Enter new value for {setting_name} (Current: {selected_camera.get_camera_setting(setting_name)}, Range: {SETTING_RANGES[setting_name].get('min')}-{SETTING_RANGES[setting_name].get('max')}): ").strip()
                    
                    try:
                        # Attempt to convert to int, if it fails, keep as string (for enum values)
                        new_value = int(value_input)
                    except ValueError:
                        new_value = value_input # Keep as string for non-numeric values (like '0' or '1' for on/off)

                    if selected_camera.set_camera_setting(setting_name, new_value):
                        print(f"Successfully set {setting_name} to {new_value} for {selected_camera.camera_name}.")
                    else:
                        print(f"Failed to set {setting_name} for {selected_camera.camera_name}.")
                    
                    self.setting_prompt_active = False # Reset flag after input
                else:
                    print("Invalid command. Press 'q' to quit, 's' to save, 'r' to reset, 'p' to print stats, 'c' to change settings.")
                
                if not self.setting_prompt_active: # Only sleep if not in the middle of a setting prompt
                    time.sleep(0.1) # Small sleep to prevent busy-waiting
        
        except KeyboardInterrupt:
            print("\nCtrl+C detected. Shutting down...")
        finally:
            self.stop_all_cameras()

    def stop_all_cameras(self):
        """Stops all running camera threads and releases resources."""
        print("Stopping all cameras...")
        self.running = False # Signal adjustment thread to stop
        if self.adjustment_thread:
            self.adjustment_thread.join(timeout=2.0)
            if self.adjustment_thread.is_alive():
                print("Warning: Adjustment thread did not terminate cleanly.")
        
        for cam_id, camera in self.cameras.items():
            camera.stop()
        print("All cameras stopped and resources released.")

def main():
    parser = argparse.ArgumentParser(description="Multi-Camera Inspector for Jetson Nano with Flask web interface.")
    parser.add_argument('--cameras', nargs='+', help="Specific camera IDs/names to use (e.g., camera_lr video0). If omitted, all detected cameras will be used.")
    parser.add_argument('--save_path', type=str, default=os.path.join(os.getcwd(), 'captured_frames'),
                        help="Path to save captured frames. Defaults to a 'captured_frames' directory in the current working directory.")
    parser.add_argument('--width', type=int, default=1920, help="Set the width resolution for cameras.")
    parser.add_argument('--height', type=int, default=1080, help="Set the height resolution for cameras.")
    
    args = parser.parse_args()

    max_resolution = (args.width, args.height)

    inspector = MultiCameraInspector(
        camera_selection=args.cameras,
        save_path=args.save_path,
        max_resolution=max_resolution
    )
    
    inspector.run_inspection()

if __name__ == "__main__":
    # HTML template for Flask. This should be saved as 'templates/index.html'
    # relative to where your script is run.
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Multi-Camera Inspector</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .camera-container {
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                justify-content: center;
            }
            .camera-card {
                border: 1px solid #ccc;
                padding: 10px;
                box-shadow: 2px 2px 8px rgba(0,0,0,0.1);
                border-radius: 8px;
                background-color: #f9f9f9;
                text-align: center;
            }
            .camera-card h2 {
                margin-top: 0;
                color: #333;
            }
            .camera-card img {
                max-width: 100%;
                height: auto;
                border: 1px solid #eee;
                border-radius: 4px;
                margin-top: 10px;
            }
        </style>
    </head>
    <body>
        <h1>Multi-Camera Inspector</h1>
        <div class="camera-container">
            {% for cam_id, camera in cameras.items() %}
            <div class="camera-card">
                <h2>{{ camera.camera_name }} ({{ cam_id }})</h2>
                <img src="{{ url_for('video_feed', camera_id=cam_id) }}" width="640" height="480" alt="Video Feed">
                <p>Status: Live</p>
                </div>
            {% endfor %}
        </div>
        {% if not cameras %}
        <p>No cameras are currently active or detected.</p>
        {% endif %}
    </body>
    </html>
    """

    # Create the 'templates' directory if it doesn't exist
    template_dir = 'templates'
    os.makedirs(template_dir, exist_ok=True)

    # Write the HTML template to a file inside the 'templates' directory
    with open(os.path.join(template_dir, 'index.html'), 'w') as f:
        f.write(html_template)
    
    main()