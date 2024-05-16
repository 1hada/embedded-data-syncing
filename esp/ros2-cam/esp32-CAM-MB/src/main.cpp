#include "Arduino.h"
#include <esp_camera.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <ros2arduino.h>
// #include <ArduinoMDNS.h>

#include <WiFi.h>

#include "secrets.h"
// https://www.instructables.com/Getting-Started-With-ESP32-CAM-Streaming-Video-Usi/
// https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino

//
// WARNING!!! PSRAM IC required for UXGA resolution and high JPEG quality
//            Ensure ESP32 Wrover Module or other board with PSRAM is selected
//            Partial images will be transmitted if image exceeds buffer size
//
//            You must select partition scheme from the board menu that has at least 3MB APP space.
//            Face Recognition is DISABLED for ESP32 and ESP32-S2, because it takes up from 15
//            seconds to process single frame. Face Detection is ENABLED if PSRAM is enabled as well

// ===================
// Select camera model
// ===================
// #define CAMERA_MODEL_WROVER_KIT // Has PSRAM
// #define CAMERA_MODEL_ESP_EYE // Has PSRAM
// #define CAMERA_MODEL_ESP32S3_EYE // Has PSRAM
// #define CAMERA_MODEL_M5STACK_PSRAM // Has PSRAM
// #define CAMERA_MODEL_M5STACK_V2_PSRAM // M5Camera version B Has PSRAM
// #define CAMERA_MODEL_M5STACK_WIDE // Has PSRAM
// #define CAMERA_MODEL_M5STACK_ESP32CAM // No PSRAM
// #define CAMERA_MODEL_M5STACK_UNITCAM // No PSRAM
#define CAMERA_MODEL_AI_THINKER // Has PSRAM
// #define CAMERA_MODEL_TTGO_T_JOURNAL // No PSRAM
// #define CAMERA_MODEL_XIAO_ESP32S3 // Has PSRAM
//  ** Espressif Internal Boards **
// #define CAMERA_MODEL_ESP32_CAM_BOARD
// #define CAMERA_MODEL_ESP32S2_CAM_BOARD
// #define CAMERA_MODEL_ESP32S3_CAM_LCD
// #define CAMERA_MODEL_DFRobot_FireBeetle2_ESP32S3 // Has PSRAM
// #define CAMERA_MODEL_DFRobot_Romeo_ESP32S3 // Has PSRAM
#include "camera_pins.h"

void startCameraServer();
void setupLedFlash(int pin);

// ROS 2 node
ros2::Node node("esp32_camera_publisher");

// Function to initialize camera
void initCamera(void *parameter)
{
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = CAMERA_Y2_GPIO_NUM;
  config.pin_d1 = CAMERA_Y3_GPIO_NUM;
  config.pin_d2 = CAMERA_Y4_GPIO_NUM;
  config.pin_d3 = CAMERA_Y5_GPIO_NUM;
  config.pin_d4 = CAMERA_Y6_GPIO_NUM;
  config.pin_d5 = CAMERA_Y7_GPIO_NUM;
  config.pin_d6 = CAMERA_Y8_GPIO_NUM;
  config.pin_d7 = CAMERA_Y9_GPIO_NUM;
  config.pin_xclk = CAMERA_XCLK_GPIO_NUM;
  config.pin_pclk = CAMERA_PCLK_GPIO_NUM;
  config.pin_vsync = CAMERA_VSYNC_GPIO_NUM;
  config.pin_href = CAMERA_HREF_GPIO_NUM;
  config.pin_sscb_sda = CAMERA_SIOD_GPIO_NUM;
  config.pin_sscb_scl = CAMERA_SIOC_GPIO_NUM;
  config.pin_pwdn = CAMERA_PWDN_GPIO_NUM;
  config.pin_reset = CAMERA_RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_UXGA;
  config.jpeg_quality = 10;
  config.fb_count = 1;

  // Initialize camera with specified configuration
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK)
  {
    Serial.printf("Camera init failed with error 0x%x", err);
    vTaskDelete(NULL);
  }

  // Task complete, delete the task
  vTaskDelete(NULL);
}

// Function to capture image and publish to ROS 2
void captureAndPublishImage(void *parameter)
{
  while (true)
  {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
    {
      Serial.println("Camera capture failed");
      continue;
    }

    // Create Image message
    sensor_msgs::msg::Image img_msg;
    img_msg.header.stamp = node.now();
    img_msg.height = fb->height;
    img_msg.width = fb->width;
    img_msg.encoding = "jpeg";
    img_msg.is_bigendian = false;
    img_msg.step = fb->len / fb->height;
    img_msg.data.resize(fb->len);
    memcpy(img_msg.data.data(), fb->buf, fb->len);

    // Publish Image message
    node.publish("/image/color/source_1", img_msg);

    // Release the frame buffer
    esp_camera_fb_return(fb);

    // Delay for next capture (adjust as needed)
    vTaskDelay(pdMS_TO_TICKS(1000)); // Delay for 1000 milliseconds (1 second)
  }
}

void setup()
{
  Serial.begin(115200);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  /*
  The ESP32 has built-in power-saving features that can put the Wi-Fi module into sleep mode when it's not actively transmitting or receiving data. While in sleep mode, the Wi-Fi module consumes less power, which can be beneficial for battery-powered applications to conserve energy.

  However, in some cases, particularly in applications where continuous network connectivity is required, such as in IoT devices communicating with ROS2, it may be necessary to disable the Wi-Fi sleep mode to ensure consistent and uninterrupted communication.
  */
  WiFi.setSleep(false);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");

  /*
  if (!MDNS.begin("esp32"))
  {
    Serial.println("Error setting up MDNS responder!");
    delay(10000);  // Wait for 10 seconds before restarting
    ESP.restart(); // Restart the ESP32
  }
  Serial.println("MDNS responder started");
  MDNS.addService(SERVICE_NAME, "tcp", SERVICE_PORT);
  */

  // Initialize ROS 2 node
  node.initNode();

  // Create tasks for camera initialization and image capture
  xTaskCreatePinnedToCore(initCamera, "initCamera", 4096, NULL, 5, NULL, 1);
  xTaskCreatePinnedToCore(captureAndPublishImage, "captureAndPublishImage", 16384, NULL, 5, NULL, 1); // 16384 stack depth

  // startCameraServer();
}

void loop()
{
  // This loop will not execute since tasks are running in FreeRTOS
}
