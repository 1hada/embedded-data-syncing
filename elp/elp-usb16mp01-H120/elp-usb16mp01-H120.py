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
ADJUSTMENT_INTERVAL = 7  # Seconds between image adjustments
BRIGHTNESS_TARGET_LOW = 80 # Target average pixel value for "not too dark"
BRIGHTNESS_TARGET_HIGH = 120 # Target average pixel value for "not too bright"
ADJUSTMENT_STEP_EXPOSURE = 50 # How much to change exposure by
ADJUSTMENT_STEP_BRIGHTNESS = 10 # How much to change brightness by
ADJUSTMENT_STEP_CONTRAST = 10 # How much to change contrast by
ADJUSTMENT_STEP_GAIN = 5 # How much to change gain by

# Define common camera setting ranges (these are typical, might need fine-tuning for your specific camera)
# Use 'v4l2-ctl -d /dev/videoX -L' to get actual ranges for your device
SETTING_RANGES = {
    'exposure_auto': {'manual': 3, 'aperture_priority': 1, 'auto_mode': 1, 'manual_mode': 3}, # ELP cameras often use 1 (auto) or 3 (manual)
    'exposure_absolute': {'min': 10, 'max': 2047}, # Typical range, verify with v4l2-ctl
    'brightness': {'min': 0, 'max': 255},
    'contrast': {'min': 0, 'max': 255},
    'gain': {'min': 0, 'max': 255},
    'white_balance_temperature_auto': {'off': 0, 'on': 1},
    'white_balance_temperature': {'min': 2800, 'max': 6500}, # Typical range, verify with v4l2-ctl
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
                # Set to manual exposure (typically 3 for ELP cameras)
                if self.set_camera_setting('exposure_auto', SETTING_RANGES['exposure_auto']['manual']):
                    print(f"{self.camera_name}: Auto-exposure disabled (set to manual).")
                else:
                    print(f"{self.camera_name}: Could not set exposure_auto to manual via v4l2-ctl.")

                # Set to manual white balance (typically 0 for off)
                if self.set_camera_setting('white_balance_temperature_auto', SETTING_RANGES['white_balance_temperature_auto']['off']):
                    print(f"{self.camera_name}: Auto-white balance disabled.")
                else:
                    print(f"{self.camera_name}: Could not set white_balance_temperature_auto to off via v4l2-ctl.")
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
    
    # set_camera_setting, get_camera_setting, calculate_brightness_level, adjust_image_settings
    # ... (These methods remain largely the same as in the previous, comprehensive update) ...
    def set_camera_setting(self, setting_name, value):
        """
        Set a camera property using v4l2-ctl.
        Requires the actual /dev/videoX path.
        Example setting_name: 'exposure_auto', 'exposure_absolute', 'brightness', 'contrast', 'gain', 'white_balance_temperature_auto', 'white_balance_temperature'
        """
        if not self.real_device_path or not os.path.exists(self.real_device_path):
            # print(f"Error: Cannot set {setting_name}. Real device path '{self.real_device_path}' not valid for {self.camera_name}.")
            return False

        try:
            # Handle specific control interactions for manual/auto modes
            if setting_name == 'exposure_absolute':
                # Ensure auto exposure is set to manual mode (3 for ELP)
                if self.get_camera_setting('exposure_auto') != SETTING_RANGES['exposure_auto']['manual']:
                    self.set_camera_setting('exposure_auto', SETTING_RANGES['exposure_auto']['manual'])
                    time.sleep(0.05) # Give it a moment to switch modes
            elif setting_name == 'white_balance_temperature':
                # Ensure auto WB is off
                if self.get_camera_setting('white_balance_temperature_auto') != SETTING_RANGES['white_balance_temperature_auto']['off']:
                    self.set_camera_setting('white_balance_temperature_auto', SETTING_RANGES['white_balance_temperature_auto']['off'])
                    time.sleep(0.05) # Give it a moment

            command = ["v4l2-ctl", "-d", self.real_device_path, f"--set-ctrl={setting_name}={value}"]
            result = subprocess.run(command, capture_output=True, text=True)

            if result.returncode == 0:
                # print(f"Successfully set {setting_name} to {value} for {self.camera_name}.")
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
            # print(f"Error: Cannot get {setting_name}. Real device path '{self.real_device_path}' not valid for {self.camera_name}.")
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
                        # print(f"Could not parse integer value for {setting_name}: {value_str}")
                        return value_str # Return as string if not an int
                else:
                    # print(f"Unexpected output format for {setting_name}: {output_line}")
                    return None
            else:
                # print(f"Failed to get {setting_name} for {self.camera_name}. Error: {result.stderr.strip()}")
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
                    # print(f"[{self.camera_name}] Frame queue full, dropped frame. Queue size: {self.frame_queue.qsize()}") # Uncomment for debug
                    
            else:
                # print(f"[{self.camera_name}] Failed to read frame (might be select() timeout). Retrying...")
                # Add a small delay if read fails to prevent rapid, continuous failures from overwhelming.
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
                break # Should not happen with while not empty, but for safety
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
            # This is a bit heavy, but it's the best way to verify if it's an ELP.
            udevadm_output = subprocess.check_output(['udevadm', 'info', '--name', device, '--attribute-walk'], text=True)
            for line in udevadm_output.splitlines():
                if 'ATTRS{idVendor}' in line:
                    vendor_id = line.split('==')[1].strip().strip('"')
                if 'ATTRS{idProduct}' in line:
                    product_id = line.split('==')[1].strip().strip('"')
                if vendor_id and product_id:
                    break

            # Your ELP camera vendor/product ID. **UPDATE THESE IF DIFFERENT**
            # Based on your udev rules, it's 32e4:0298
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
            # else:
            #     print(f"Found non-ELP video device: {device} (Vendor: {vendor_id}, Product: {product_id}). Skipping.")

        except subprocess.CalledProcessError:
            # print(f"Could not get udevadm info for {device}. Skipping.")
            pass # Silently skip if udevadm fails for this device
        except Exception as e:
            # print(f"Error checking {device} with udevadm: {e}. Skipping.")
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
    based on the current image brightness level.
    """
    cam_name = camera.camera_name
    real_device = camera.real_device_path

    if not real_device or not os.path.exists(real_device):
        # print(f"Cannot adjust settings for {cam_name}: Real device path unknown or invalid.")
        return

    # print(f"[{cam_name}] Current Brightness: {current_brightness:.2f}")

    # Prioritize exposure
    current_exposure_auto = camera.get_camera_setting('exposure_auto')
    
    # Ensure camera is in manual exposure mode for adjustments
    if current_exposure_auto != SETTING_RANGES['exposure_auto']['manual']:
        camera.set_camera_setting('exposure_auto', SETTING_RANGES['exposure_auto']['manual'])
        time.sleep(0.05) # Give camera time to apply change
    
    current_exposure = camera.get_camera_setting('exposure_absolute')
    exposure_min = SETTING_RANGES.get('exposure_absolute', {}).get('min', 10)
    exposure_max = SETTING_RANGES.get('exposure_absolute', {}).get('max', 2047)

    if current_exposure is not None:
        if current_brightness < BRIGHTNESS_TARGET_LOW:
            if current_exposure < exposure_max:
                new_exposure = min(current_exposure + ADJUSTMENT_STEP_EXPOSURE, exposure_max)
                print(f"[{cam_name}] Image too dark ({current_brightness:.2f}). Increasing exposure from {current_exposure} to {new_exposure}.")
                camera.set_camera_setting('exposure_absolute', new_exposure)
                return # Only adjust one major setting at a time

        elif current_brightness > BRIGHTNESS_TARGET_HIGH:
            if current_exposure > exposure_min:
                new_exposure = max(current_exposure - ADJUSTMENT_STEP_EXPOSURE, exposure_min)
                print(f"[{cam_name}] Image too bright ({current_brightness:.2f}). Decreasing exposure from {current_exposure} to {new_exposure}.")
                camera.set_camera_setting('exposure_absolute', new_exposure)
                return # Only adjust one major setting at a time

    # If exposure is at limits or not adjustable, try brightness
    current_brightness_val = camera.get_camera_setting('brightness')
    brightness_min = SETTING_RANGES.get('brightness', {}).get('min', 0)
    brightness_max = SETTING_RANGES.get('brightness', {}).get('max', 255)

    if current_brightness_val is not None:
        if current_brightness < BRIGHTNESS_TARGET_LOW:
            if current_brightness_val < brightness_max:
                new_val = min(current_brightness_val + ADJUSTMENT_STEP_BRIGHTNESS, brightness_max)
                print(f"[{cam_name}] Image too dark ({current_brightness:.2f}). Increasing brightness from {current_brightness_val} to {new_val}.")
                camera.set_camera_setting('brightness', new_val)
                return

        elif current_brightness > BRIGHTNESS_TARGET_HIGH:
            if current_brightness_val > brightness_min:
                new_val = max(current_brightness_val - ADJUSTMENT_STEP_BRIGHTNESS, brightness_min)
                print(f"[{cam_name}] Image too bright ({current_brightness:.2f}). Decreasing brightness from {current_brightness_val} to {new_val}.")
                camera.set_camera_setting('brightness', new_val)
                return

    # Then contrast
    current_contrast = camera.get_camera_setting('contrast')
    contrast_min = SETTING_RANGES.get('contrast', {}).get('min', 0)
    contrast_max = SETTING_RANGES.get('contrast', {}).get('max', 255)

    if current_contrast is not None:
        if current_brightness < BRIGHTNESS_TARGET_LOW:
            if current_contrast < contrast_max:
                new_val = min(current_contrast + ADJUSTMENT_STEP_CONTRAST, contrast_max)
                print(f"[{cam_name}] Image too dark ({current_brightness:.2f}). Increasing contrast from {current_contrast} to {new_val}.")
                camera.set_camera_setting('contrast', new_val)
                return
        elif current_brightness > BRIGHTNESS_TARGET_HIGH:
            if current_contrast > contrast_min:
                new_val = max(current_contrast - ADJUSTMENT_STEP_CONTRAST, contrast_min)
                print(f"[{cam_name}] Image too bright ({current_brightness:.2f}). Decreasing contrast from {current_contrast} to {new_val}.")
                camera.set_camera_setting('contrast', new_val)
                return
            
    # Finally, gain
    current_gain = camera.get_camera_setting('gain')
    gain_min = SETTING_RANGES.get('gain', {}).get('min', 0)
    gain_max = SETTING_RANGES.get('gain', {}).get('max', 255)

    if current_gain is not None:
        if current_brightness < BRIGHTNESS_TARGET_LOW:
            if current_gain < gain_max:
                new_val = min(current_gain + ADJUSTMENT_STEP_GAIN, gain_max)
                print(f"[{cam_name}] Image too dark ({current_brightness:.2f}). Increasing gain from {current_gain} to {new_val}.")
                camera.set_camera_setting('gain', new_val)
                return
        elif current_brightness > BRIGHTNESS_TARGET_HIGH:
            if current_gain > gain_min:
                new_val = max(current_gain - ADJUSTMENT_STEP_GAIN, gain_min)
                print(f"[{cam_name}] Image too bright ({current_brightness:.2f}). Decreasing gain from {current_gain} to {new_val}.")
                camera.set_camera_setting('gain', new_val)
                return

    # print(f"[{cam_name}] Brightness within target range or no further adjustment possible.")


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
                if camera.start():
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
                user_input = input("Enter command ('q', 's', 'r', 'p', 'c'): ").strip().lower()

                if user_input == 'q':
                    self.running = False
                    break
                elif user_input == 's':
                    self.save_current_frames()
                elif user_input == 'r':
                    self.reset_counters()
                elif user_input == 'p':
                    self.print_stats()
                elif user_input == 'c':
                    self.setting_prompt_active = True
                    self.prompt_camera_settings()
                    self.setting_prompt_active = False # Reset flag after input
                else:
                    print("Unknown command. Please use 'q', 's', 'r', 'p', or 'c'.")
                
                time.sleep(0.1) # Prevent busy-waiting too much
                
        except KeyboardInterrupt:
            print("\nInterrupted by user (Ctrl+C).")
        
        finally:
            self.cleanup()
    
    def prompt_camera_settings(self):
        """Prompt user for camera and settings to modify."""
        print("\n--- Camera Settings ---")
        if not self.cameras:
            print("No active cameras to configure.")
            return

        print("Available Cameras:")
        camera_map = {}
        for i, (cam_id, camera_obj) in enumerate(self.cameras.items()):
            print(f"  {i+1}. {camera_obj.camera_name} (ID: {cam_id}, Device: {camera_obj.real_device_path})")
            camera_map[str(i+1)] = cam_id

        while True:
            choice = input("Enter camera number to configure (or 'b' to go back, 'l' to list controls): ").strip().lower()
            if choice == 'b':
                return
            elif choice == 'l':
                print("\nCommon ELP Camera Controls (use 'v4l2-ctl -d /dev/videoX -L' for full list and ranges):")
                print("  exposure_auto: 0 (Manual), 1 (Aperture Priority), 3 (Shutter Priority)")
                print("  exposure_absolute: [1-2047] (manual exposure time, depends on camera)")
                print("  brightness: [0-255]")
                print("  contrast: [0-255]")
                print("  saturation: [0-255]")
                print("  gain: [0-255]")
                print("  white_balance_temperature_auto: 0 (off), 1 (on)")
                print("  white_balance_temperature: [2800-6500] (manual temperature, depends on camera)")
                print("  power_line_frequency: 0 (Disabled), 1 (50Hz), 2 (60Hz)")
                print("  sharpness: [0-255]")
                print("  backlight_compensation: [0-1]")
                print("  pan_absolute: [-36000, 36000] (if supported)")
                print("  tilt_absolute: [-36000, 36000] (if supported)")
                print("  zoom_absolute: [0-500] (if supported)")
                continue
            
            if choice not in camera_map:
                print("Invalid camera choice. Please try again.")
                continue
            
            selected_cam_id = camera_map[choice]
            selected_camera = self.cameras[selected_cam_id]
            
            while True:
                setting_name = input(f"Enter setting name for {selected_camera.camera_name} (e.g., 'exposure_absolute', 'brightness', or 'b' to go back, 'g' to get current value): ").strip()
                if setting_name == 'b':
                    break
                elif setting_name == 'g':
                    setting_to_get = input("Enter setting name to get its current value: ").strip()
                    if setting_to_get:
                        current_value = selected_camera.get_camera_setting(setting_to_get)
                        if current_value is not None:
                            print(f"Current value of {setting_to_get} for {selected_camera.camera_name}: {current_value}")
                    continue

                if not setting_name:
                    print("Setting name cannot be empty.")
                    continue
                
                value_str = input(f"Enter value for {setting_name} (e.g., 100, 2047): ").strip()
                if not value_str.isdigit():
                    print("Value must be an integer. Please try again.")
                    continue
                
                value = int(value_str)
                selected_camera.set_camera_setting(setting_name, value)
                
                another = input("Set another setting for this camera? (y/N): ").strip().lower()
                if another != 'y':
                    break
            
            another_camera = input("Configure another camera? (y/N): ").strip().lower()
            if another_camera != 'y':
                break

    def save_current_frames(self):
        """Save current frame from all cameras"""
        timestamp = time.time()
        saved_files = []
        
        for cam_id, camera in self.cameras.items():
            frame_info = camera.get_latest_frame() # Get latest frame for saving
            if frame_info:
                filepath = camera.save_frame(frame_info['frame'], timestamp)
                if filepath:
                    saved_files.append(filepath)
        
        print(f"Saved {len(saved_files)} frames at {datetime.fromtimestamp(timestamp)}")
    
    def reset_counters(self):
        """Reset frame counters for all cameras"""
        for camera in self.cameras.values():
            camera.frame_count = 0
            camera.dropped_frames = 0
            camera.fps_counter.clear()
            # Clear frame queue to ensure fresh start
            while not camera.frame_queue.empty():
                try:
                    camera.frame_queue.get_nowait()
                except queue.Empty:
                    break
        print("Frame counters reset")
    
    def print_stats(self):
        """Print current statistics"""
        print(f"\n--- Stats at {datetime.now().strftime('%H:%M:%S')} ---")
        for cam_id, camera in self.cameras.items():
            fps = camera.get_fps()
            print(f"{camera.camera_name}: {fps:.1f} FPS, "
                  f"{camera.frame_count} frames, "
                  f"{camera.dropped_frames} dropped, "
                  f"Queue: {camera.frame_queue.qsize()}/{camera.frame_queue.maxsize}")
    
    def cleanup(self):
        """Clean up resources"""
        print("\nCleaning up...")
        self.running = False
        
        # Stop all camera capture threads
        for camera in self.cameras.values():
            camera.stop()
        
        # Wait for adjustment thread to finish
        if self.adjustment_thread and self.adjustment_thread.is_alive():
            print("Stopping adjustment thread...")
            self.adjustment_thread.join(timeout=2.0)
            if self.adjustment_thread.is_alive():
                print("Warning: Adjustment thread did not terminate cleanly.")

        # Close all OpenCV display windows (if any were created, though with web UI this is less critical)
        cv2.destroyAllWindows()
        print("Cleanup complete")

def main():
    parser = argparse.ArgumentParser(description='Multi-camera inspector for ELP USB cameras on Jetson Nano with Web UI and Auto Adjustment')
    parser.add_argument('--cameras', nargs='+', type=str, 
                        # Updated choices: allow generic videoX to be specified
                        choices=['camera_lr', 'camera_ur', 'camera_ul', 'camera_ll'] + [f'video{i}' for i in range(10)], 
                        help='Specific cameras to use (e.g., --cameras camera_lr camera_ur video0). If not specified, all detected cameras will be used.')
    parser.add_argument('--save-path', type=str, default=None,
                        help='Path to save frames (e.g., /media/sdcard/images)')
    parser.add_argument('--resolution', type=str, default='1280x720', # Default to a safer resolution
                        help='Maximum resolution for cameras (e.g., 1920x1080, 1280x720). Default: 1280x720.')
    parser.add_argument('--detect-only', action='store_true',
                        help='Only detect cameras and exit.')
    
    args = parser.parse_args()
    
    if args.detect_only:
        # Added a check here for detect_cameras to print more info for the user
        detected_cams = detect_cameras()
        if detected_cams:
            print("\n--- Detected Cameras ---")
            for cam_id, info in detected_cams.items():
                print(f"  ID: {cam_id}, Name: {info['name']}, Path: {info['path']}, Real Device: {info['real_device']}")
        else:
            print("No cameras detected by the script's detection logic.")
        return
    
    # Parse resolution
    try:
        width, height = map(int, args.resolution.split('x'))
    except ValueError:
        print("Error: Invalid resolution format. Please use WIDTHxHEIGHT, e.g., 1280x720.")
        sys.exit(1)
    
    inspector = MultiCameraInspector(
        camera_selection=args.cameras,
        save_path=args.save_path,
        max_resolution=(width, height)
    )
    
    inspector.run_inspection()

if __name__ == "__main__":
    main()