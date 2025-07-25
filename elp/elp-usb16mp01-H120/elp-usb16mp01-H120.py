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

class CameraInspector:
    def __init__(self, camera_device, camera_name, save_path=None, max_resolution=(1920, 1080), real_device_path=None):
        self.camera_device = camera_device  # Can be device path or index (e.g., /dev/camera_lr)
        self.camera_name = camera_name      # Human readable name
        self.save_path = save_path
        self.max_resolution = max_resolution
        self.real_device_path = real_device_path # Actual /dev/videoX path for v4l2-ctl
        self.cap = None
        self.frame_queue = queue.Queue(maxsize=5)
        self.fps_counter = deque(maxlen=30)  # Store last 30 frame times
        self.running = False
        self.thread = None
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.dropped_frames = 0
        
    def initialize_camera(self):
        """Initialize camera with optimal settings for Jetson Nano"""
        print(f"Initializing {self.camera_name} ({self.camera_device})...")
        
        # Try different backends for better performance on Jetson
        backends = [cv2.CAP_V4L2, cv2.CAP_GSTREAMER, cv2.CAP_ANY]
        
        for backend in backends:
            try:
                if isinstance(self.camera_device, str) and self.camera_device.startswith('/dev/'):
                    # For device paths, convert to index by finding the real device
                    if os.path.exists(self.camera_device):
                        # Ensure real_device_path is set from detect_cameras for v4l2-ctl
                        if self.real_device_path and 'video' in self.real_device_path:
                            device_num = int(self.real_device_path.split('video')[1])
                            self.cap = cv2.VideoCapture(device_num, backend)
                        else:
                            # Fallback if real_device_path is not explicitly passed or is not a video device
                            self.cap = cv2.VideoCapture(self.camera_device, backend)
                    else:
                        print(f"Device {self.camera_device} does not exist")
                        continue
                else:
                    # Direct index
                    self.cap = cv2.VideoCapture(self.camera_device, backend)
                
                if self.cap.isOpened():
                    # Test if we can actually read a frame
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None:
                        print(f"{self.camera_name} opened successfully with backend: {backend}")
                        break
                    else:
                        print(f"{self.camera_name} opened but cannot read frames with backend: {backend}")
                        self.cap.release()
                        self.cap = None
                else:
                    if self.cap:
                        self.cap.release()
                    self.cap = None
                    
            except Exception as e:
                print(f"Error trying backend {backend} for {self.camera_name}: {e}")
                if self.cap:
                    self.cap.release()
                self.cap = None
        
        if not self.cap or not self.cap.isOpened():
            raise RuntimeError(f"Failed to open {self.camera_name} ({self.camera_device})")
        
        # Set camera properties for ELP-USB16MP01-H120
        width, height = self.max_resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)  # Target 30 FPS
        
        # Enable auto-exposure and auto-white balance if supported
        try:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1) # Set to auto
            self.cap.set(cv2.CAP_PROP_AUTO_WB, 1)      # Set to auto
        except:
            pass  # Some properties might not be supported
        
        # Set buffer size to reduce latency
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # Get actual resolution
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        print(f"{self.camera_name} - Resolution: {actual_width}x{actual_height}, Target FPS: {actual_fps}")
        
        return True
    
    def set_camera_setting(self, setting_name, value):
        """
        Set a camera property using v4l2-ctl.
        Requires the actual /dev/videoX path.
        Example setting_name: 'exposure_auto', 'exposure_absolute', 'brightness', 'contrast', 'gain', 'white_balance_temperature_auto', 'white_balance_temperature'
        """
        if not self.real_device_path:
            print(f"Error: Cannot set {setting_name}. Real device path not known for {self.camera_name}.")
            return False

        try:
            # First, disable auto settings if we are setting a manual value
            if setting_name in ['exposure_absolute', 'white_balance_temperature']:
                if setting_name == 'exposure_absolute':
                    self.set_camera_setting('exposure_auto', 1) # V4L2_EXPOSURE_APERTURE_PRIORITY (auto mode) or 3 (manual mode)
                    print(f"Setting exposure_auto for {self.camera_name} to 1 (Aperture Priority Mode)...")
                    time.sleep(0.1) # Give it a moment
                elif setting_name == 'white_balance_temperature':
                    self.set_camera_setting('white_balance_temperature_auto', 0) # Disable auto WB
                    print(f"Disabling auto white_balance_temperature for {self.camera_name}...")
                    time.sleep(0.1) # Give it a moment

            command = ["v4l2-ctl", "-d", self.real_device_path, f"--set-ctrl={setting_name}={value}"]
            print(f"Executing: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"Successfully set {setting_name} to {value} for {self.camera_name}.")
                return True
            else:
                print(f"Failed to set {setting_name} for {self.camera_name}. Error: {result.stderr.strip()}")
                print("Note: Run 'v4l2-ctl -d /dev/videoX -L' to list available controls and their ranges.")
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
        if not self.real_device_path:
            print(f"Error: Cannot get {setting_name}. Real device path not known for {self.camera_name}.")
            return None

        try:
            command = ["v4l2-ctl", "-d", self.real_device_path, f"--get-ctrl={setting_name}"]
            print(f"Executing: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True)

            if result.returncode == 0:
                # Expected output format: 'control_name: value'
                output_line = result.stdout.strip()
                if ':' in output_line:
                    value_str = output_line.split(':', 1)[1].strip()
                    try:
                        return int(value_str)
                    except ValueError:
                        print(f"Could not parse integer value for {setting_name}: {value_str}")
                        return value_str # Return as string if not an int
                else:
                    print(f"Unexpected output format for {setting_name}: {output_line}")
                    return None
            else:
                print(f"Failed to get {setting_name} for {self.camera_name}. Error: {result.stderr.strip()}")
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
                print(f"{self.camera_name}: Failed to read frame")
                time.sleep(0.01)  # Brief pause on read failure
    
    def get_fps(self):
        """Calculate current FPS based on recent frames"""
        if len(self.fps_counter) < 2:
            return 0.0
        
        time_span = self.fps_counter[-1] - self.fps_counter[0]
        if time_span > 0:
            return (len(self.fps_counter) - 1) / time_span
        return 0.0
    
    def get_frame_info(self):
        """Get current frame and statistics"""
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
    
    def start(self):
        """Start camera capture"""
        if not self.initialize_camera():
            return False
            
        self.running = True
        self.thread = threading.Thread(target=self.capture_frames)
        self.thread.daemon = True
        self.thread.start()
        return True
    
    def stop(self):
        """Stop camera capture"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
    
    def save_frame(self, frame, timestamp):
        """Save frame to SD card"""
        if self.save_path:
            filename = f"{self.camera_name}_{datetime.fromtimestamp(timestamp).strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = os.path.join(self.save_path, filename)
            cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return filepath
        return None

def detect_cameras():
    """Detect available cameras using the udev naming scheme"""
    cameras = {}
    
    # Define camera mappings based on your udev rules
    camera_mappings = {
        'camera_lr': 'Lower Right',
        'camera_ur': 'Upper Right', 
        'camera_ul': 'Upper Left',
        'camera_ll': 'Lower Left'
    }
    
    print("Detecting cameras...")
    
    # Check for named camera devices
    for device_name, display_name in camera_mappings.items():
        device_path = f"/dev/{device_name}"
        if os.path.exists(device_path):
            # Get the real device it points to
            real_device = os.path.realpath(device_path)
            print(f"✓ Found {display_name}: {device_path} -> {real_device}")
            cameras[device_name] = {
                'path': device_path,
                'name': display_name,
                'real_device': real_device
            }
        else:
            print(f"✗ {display_name} not found at {device_path}")
    
    # Also check for standard video devices as fallback
    video_devices = glob.glob("/dev/video*")
    if video_devices and not cameras:
        print("\nNo named cameras found, checking standard video devices...")
        for i, device in enumerate(sorted(video_devices)):
            cameras[f"video{i}"] = {
                'path': device,
                'name': f"Camera {i}",
                'real_device': device
            }
            print(f"✓ Found standard device: {device}")
    
    return cameras

class MultiCameraInspector:
    def __init__(self, camera_selection=None, save_path=None, display_scale=0.3, max_resolution=(1920, 1080)):
        self.camera_selection = camera_selection  # Specific cameras to use
        self.save_path = save_path
        self.display_scale = display_scale
        self.max_resolution = max_resolution
        self.cameras = {}
        self.running = False
        self.setting_prompt_active = False # Flag to manage setting input
        
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
        if self.camera_selection:
            # Use specified cameras
            cameras_to_init = {}
            for cam_id in self.camera_selection:
                if cam_id in available_cameras:
                    cameras_to_init[cam_id] = available_cameras[cam_id]
                else:
                    print(f"Warning: Requested camera '{cam_id}' not found")
        else:
            # Use all available cameras
            cameras_to_init = available_cameras
        
        print(f"\nInitializing {len(cameras_to_init)} cameras...")
        
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
    
    def create_info_overlay(self, frame, cam_info, frame_info):
        """Add information overlay to frame"""
        h, w = frame.shape[:2]
        overlay = frame.copy()
        
        # Semi-transparent background for text
        cv2.rectangle(overlay, (5, 5), (350, 140), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        
        # Add text information
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        color = (0, 255, 0)  # Green
        thickness = 1
        
        texts = [
            f"Camera: {cam_info['name']}",
            f"Device: {cam_info['path']}",
            f"FPS: {frame_info['fps']:.1f}",
            f"Frames: {frame_info['frame_count']}",
            f"Dropped: {frame_info['dropped_frames']}",
            f"Queue: {frame_info['queue_size']}/5",
            f"Resolution: {w}x{h}"
        ]
        
        for i, text in enumerate(texts):
            y = 20 + i * 15
            cv2.putText(frame, text, (10, y), font, font_scale, color, thickness)
        
        return frame
    
    def run_inspection(self):
        """Main inspection loop"""
        if not self.initialize_cameras():
            print("No cameras available. Exiting.")
            return
        
        # Get camera info for overlays
        available_cameras = detect_cameras()
        
        self.running = True
        print("\nCamera inspection started. Controls:")
        print("  'q' - Quit")
        print("  's' - Save current frames")
        print("  'r' - Reset frame counters")
        print("  'p' - Print current stats")
        print("  'c' - Change camera settings (exposure, gain, etc.)")
        
        display_cameras = set(self.cameras.keys())
        
        try:
            while self.running:
                frames_to_show = []
                
                for cam_id in sorted(self.cameras.keys()):
                    # Only process frames if setting prompt is not active to avoid blocking
                    if not self.setting_prompt_active:
                        if cam_id not in display_cameras:
                            continue
                            
                        camera = self.cameras[cam_id]
                        frame_info = camera.get_frame_info()
                        
                        if frame_info:
                            frame = frame_info['frame'].copy()
                            
                            # Add overlay information
                            cam_info = available_cameras.get(cam_id, {'name': cam_id, 'path': 'unknown'})
                            frame_with_info = self.create_info_overlay(frame, cam_info, frame_info)
                            
                            # Resize for display
                            h, w = frame_with_info.shape[:2]
                            new_w = int(w * self.display_scale)
                            new_h = int(h * self.display_scale)
                            resized_frame = cv2.resize(frame_with_info, (new_w, new_h))
                            
                            window_name = cam_info['name']
                            frames_to_show.append((window_name, resized_frame))
                
                # Display frames only if not in setting prompt mode
                if not self.setting_prompt_active:
                    for window_name, frame in frames_to_show:
                        cv2.imshow(window_name, frame)
                else:
                    # If setting prompt is active, ensure windows are not constantly updated
                    # and potentially clear existing displays
                    for window_name, _ in frames_to_show:
                        cv2.destroyWindow(window_name) # Close windows while input is taken
                    # This ensures the terminal isn't fighting with OpenCV's event loop
                    time.sleep(0.1) 
                
                # Handle keyboard input
                # Only process key presses if not in setting input mode
                if not self.setting_prompt_active:
                    key = cv2.waitKey(1) & 0xFF
                    
                    if key == ord('q'):
                        break
                    elif key == ord('s'):
                        self.save_current_frames()
                    elif key == ord('r'):
                        self.reset_counters()
                    elif key == ord('p'):
                        self.print_stats()
                    elif key == ord('c'):
                        self.setting_prompt_active = True
                        self.prompt_camera_settings()
                        self.setting_prompt_active = False # Reset flag after input
                else:
                    # In setting prompt active mode, we yield control to allow input
                    pass # Input handled in prompt_camera_settings
        
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        
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
            frame_info = camera.get_frame_info()
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
        print("Frame counters reset")
    
    def print_stats(self):
        """Print current statistics"""
        print(f"\n--- Stats at {datetime.now().strftime('%H:%M:%S')} ---")
        for cam_id, camera in self.cameras.items():
            fps = camera.get_fps()
            print(f"{camera.camera_name}: {fps:.1f} FPS, "
                  f"{camera.frame_count} frames, "
                  f"{camera.dropped_frames} dropped")
    
    def cleanup(self):
        """Clean up resources"""
        print("\nCleaning up...")
        self.running = False
        
        for camera in self.cameras.values():
            camera.stop()
        
        cv2.destroyAllWindows()
        print("Cleanup complete")

def main():
    parser = argparse.ArgumentParser(description='Multi-camera inspector for ELP USB cameras on Jetson Nano')
    parser.add_argument('--cameras', nargs='+', type=str, 
                        choices=['camera_lr', 'camera_ur', 'camera_ul', 'camera_ll'],
                        help='Specific cameras to use (e.g., --cameras camera_lr camera_ur)')
    parser.add_argument('--save-path', type=str, default=None,
                        help='Path to save frames (e.g., /media/sdcard/images)')
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Display scale factor (default: 1.0)')
    parser.add_argument('--resolution', type=str, default='1040x800',
    #parser.add_argument('--resolution', type=str, default='1920x1080',
                        help='Maximum resolution (default: 1920x1080)')
    parser.add_argument('--detect-only', action='store_true',
                        help='Only detect cameras and exit')
    
    args = parser.parse_args()
    
    if args.detect_only:
        detect_cameras()
        return
    
    # Parse resolution
    width, height = map(int, args.resolution.split('x'))
    
    inspector = MultiCameraInspector(
        camera_selection=args.cameras,
        save_path=args.save_path,
        display_scale=args.scale,
        max_resolution=(width, height)
    )
    
    inspector.run_inspection()

if __name__ == "__main__":
    main()