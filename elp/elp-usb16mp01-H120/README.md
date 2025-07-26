
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


# Jetson Nano (deprecated)

Please use newer Jetson nano's, though instructions for the older version will be list below : 
- https://developer.nvidia.com/embedded/learn/get-started-jetson-nano-devkit#prepare
- https://developer.download.nvidia.com/embedded/L4T/r32-3-1_Release_v1.0/Jetson_Nano_Developer_Kit_User_Guide.pdf?t=eyJscyI6ImdzZW8iLCJsc2QiOiJodHRwczovL3d3dy5nb29nbGUuY29tLyJ9


```
dmesg | grep --color 'tty'
ls -l /dev/ttyACM0
sudo apt-get install -y screen
sudo screen /dev/ttyACM0 115200
```

Install pytorch on the system
```
sudo apt-get -y update; 
sudo apt-get install -y  python3-pip libopenblas-dev;

```


```
sudo nmcli d wifi connect [SSID] password [PASSWORD]


```


After following the instructions from 
https://github.com/dnovischi/jetson-tutorials/blob/main/jetson-nano-ubuntu-18-04-install.md

Make sure to update to the next ubuntu 20 via 
```
sudo apt remove --purge chromium-browser chromium-browser-l10n libreoffice-* rhythmbox* -y
sudo apt autoremove -y
sudo reboot

sudo apt-get update;sudo apt-get upgrade -y
sudo vim /etc/update-manager/release-upgrades
sudo apt-get update
sudo apt-get dist-upgrade
sudo reboot

sudo do-release-upgrade
# press no if a reboot is necessary
# check WaylandEnable=false
sudo vim /etc/gdm3/custom.conf
# uncomment the line # Driver "nividia" 
sudo vim /etc/X11/xorg.conf
sudo vim /etc/update-manager/release-upgrades
sudo reboot
```
