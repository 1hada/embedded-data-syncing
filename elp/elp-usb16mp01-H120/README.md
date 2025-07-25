
## Key Features:

See controls with :
`v4l2-ctl -d /dev/video2 -L`

1. **Named Camera Support**: Uses your camera naming scheme:
   - `camera_lr` → Lower Right
   - `camera_ur` → Upper Right  
   - `camera_ul` → Upper Left
   - `camera_ll` → Lower Left

2. **Automatic Detection**: Finds available cameras using `/dev/camera_*` devices

3. **Flexible Selection**: You can choose which specific cameras to use

## Usage Examples:

```bash
# Detect available cameras only
python3 elp-usb16mp01-H120.py --detect-only

# Use all available cameras
python3 elp-usb16mp01-H120.py

# Use specific cameras
python3 elp-usb16mp01-H120.py --cameras camera_lr camera_ur

# Save to SD card with specific cameras
python3 elp-usb16mp01-H120.py --cameras camera_ul camera_ll --save-path /media/sdcard/camera_data

# Lower resolution for better performance
python3 elp-usb16mp01-H120.py --resolution 1280x720 --scale 0.4
```

## Setup Steps:

1. **Apply your udev rules**:
   ```bash
   sudo cp your_rules_file /etc/udev/rules.d/99-usb-camera.rules
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

2. **Add yourself to plugdev group** :
   ```bash
   sudo usermod -a -G plugdev $USER
   # Then logout and login again
   ```

3. **Plug in cameras** to the correct USB ports (*.1, *.2, *.3, *.4)

4. **Test detection**:
   ```bash
   python3 elp-usb16mp01-H120.py --detect-only
   ```

The script will automatically handle the device path resolution and provide clear feedback about which cameras are found and working. The camera names in the display will show the descriptive names (Upper Left, Lower Right, etc.) making it easy to identify which camera is which.