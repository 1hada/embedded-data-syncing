# Setting Up Communication Between ESP32s and Jetson Nano with ROS2, mDNS, and DNS-SD

## Requirements:
- 4 ESP32 devices
- 1 Jetson Nano
- ROS2 installed on the Jetson Nano
- Access to both ESP32 and Jetson Nano terminals

## Step 1: Install ROS2 on Jetson Nano
Follow the official ROS2 installation instructions for Ubuntu ARM64 (Jetson Nano) [here](https://docs.ros.org/en/foxy/Installation/Ubuntu-Install-Debians.html).

## Step 2: Configure mDNS and DNS-SD on Jetson Nano
1. Install Avahi (mDNS/DNS-SD implementation) on the Jetson Nano:
    ```bash
    sudo apt-get update
    sudo apt-get install avahi-daemon
    ```

2. Configure Avahi to advertise ROS2 nodes using DNS-SD:
    - Create a file named `ros2.service` in `/etc/avahi/services/` directory:
      ```bash
      sudo nano /etc/avahi/services/ros2.service
      ```
    - Add the following content to the `ros2.service` file:
      ```xml
      <?xml version="1.0" standalone='no'?>
      <!DOCTYPE service-group SYSTEM "avahi-service.dtd">
      <service-group>
        <name replace-wildcards="yes">ROS 2 Nodes on Jetson Nano</name>
        <service>
          <type>_ros2._tcp</type>
          <port>8080</port>
        </service>
      </service-group>
      ```
    - Save and exit the file.

3. Restart the Avahi service:
    ```bash
    sudo systemctl restart avahi-daemon
    ```

## Step 3: Configure ESP32 Devices
1. Install the required libraries for mDNS/DNS-SD support on ESP32 using the Arduino IDE or PlatformIO.
2. Write code to discover ROS2 nodes using mDNS/DNS-SD. Example code:
   ```cpp
   #include <ESPmDNS.h>

   void setup() {
     Serial.begin(115200);
     if (!MDNS.begin("esp32")) 
     {
       Serial.println("Error setting up MDNS responder!");
       delay(10000);  // Wait for 10 seconds before restarting
       ESP.restart(); // Restart the ESP32
     }
     Serial.println("MDNS responder started");
     Serial.println("MDNS responder started");
     MDNS.addService("ros2", "tcp", 8080);
   }

   void loop() {
     // do nothing
   }
   ```


## Step 4: Subscribe To data from the ESP32 on another machine
```
#https://docs.ros.org/en/humble/Tutorials/Beginner-Client-Libraries/Writing-A-Simple-Py-Publisher-And-Subscriber.html
ros2 pkg create --build-type ament_python --license Apache-2.0 py_pubsub
cd ros2_ws
cd ros2_ws/src/py_pubsub/py_pubsub
wget https://raw.githubusercontent.com/ros2/examples/humble/rclpy/topics/minimal_publisher/examples_rclpy_minimal_publisher/publisher_member_function.py
wget https://raw.githubusercontent.com/ros2/examples/humble/rclpy/topics/minimal_subscriber/examples_rclpy_minimal_subscriber/subscriber_member_function.py

```