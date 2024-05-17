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

// Core
#include "Arduino.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// Hardware
#include <esp_camera.h>
#include "camera_pins.h"

// Connectivity
#include <ArduinoMDNS.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

#include <PubSubClient.h>

#include "secrets.h"
#include "hardware_constants.h"

#include <base64.h>

// Helpers
void nameFound(const char *name, IPAddress ip);
void sendFrameToServerHttps(uint8_t *data, size_t len);
void reconnect();

// Tasks
void captureAndPublishImage(void *parameter);
void resolveHostIp(void *parameter);
void initCamera(void *parameter);

// Network data
int status = WL_IDLE_STATUS; // the WiFi radio's status
WiFiUDP udp;
MDNS mdns(udp);
IPAddress ip;
String server_url = "https://your_ubuntu_server_ip/video_stream";
bool server_found = false;
// Use WiFiClientSecure for HTTPS
WiFiClientSecure client;
PubSubClient mqttClient(client);
bool mqtt_setup_required = true;

// Function to connect to MQTT broker
void reconnect()
{
  while (!mqttClient.connected())
  {
    if (mqttClient.connect("ESP32Client"))
    {
      Serial.println("Connected to MQTT Broker");
      mqtt_setup_required = true;
    }
    else
    {
      Serial.print("Failed to connect to MQTT Broker, retrying in 5 seconds...");
      delay(5000);
    }
  }
}

void captureAndPublishImage(void *parameter)
{
  while (true)
  {
    if (server_found)
    {
      camera_fb_t *fb = esp_camera_fb_get();
      if (!fb)
      {
        Serial.println("Camera capture failed");
        vTaskDelay(pdMS_TO_TICKS(1000));
        continue;
      }

      if (mqtt_setup_required)
      {

        // Connect to MQTT Broker
        client.setCACert(rootCA);
        client.setCertificate(server_crt);
        client.setPrivateKey(server_key);
        client.setServer(mqtt_server, 8883);
        reconnect();
      }
      // Send the frame to the server
      // FOR TESTING sendFrameToServerHttps(fb->buf, fb->len);

      // Publish camera frame as MQTT message
      mqttClient.publish("camera", (char *)fb->buf, fb->len);

      // Release the frame buffer
      esp_camera_fb_return(fb);
    }

    // Delay for next capture
    vTaskDelay(pdMS_TO_TICKS(5000)); // Delay for 1000 milliseconds (1 second)
  }
}

void sendFrameToServerHttps(uint8_t *data, size_t len)
{

  // Make sure to match the root ca certificate of the server
  // client.setCACert(CERT_CA);

  // Set server certificate and private key
  // client.setCertificate(CERT_CRT);
  // client.setPrivateKey(CERT_PRIVATE);

  // Connect to the server
  // WiFiClientSecure::connect(IPAddress ip, uint16_t port, const char *CA_cert, const char *cert, const char *private_key)
  // if (!client.connect(ip, MDNS_PORT))
  if (!client.connect(ip, MDNS_PORT, CERT_CA, CERT_CRT, CERT_PRIVATE))
  {
    Serial.println("Connection to server failed");
    return;
  }

  // Base64 encode the frame data
  String frameData = base64::encode(data, len);

  // Set up the HTTPS request headers
  String headers = "POST /video_stream HTTP/1.1\r\n";
  headers += "Host: " + String(server_url) + "\r\n";
  headers += "Content-Type: application/x-www-form-urlencoded\r\n";
  headers += "Content-Length: " + String(frameData.length()) + "\r\n";
  headers += "X-Camera-ID: " + String(SOURCE_ID) + "\r\n";
  headers += "\r\n";

  // Send the HTTP request
  client.print(headers);
  client.print("frame=");
  client.println(frameData);

  // Wait for server response
  while (client.connected())
  {
    if (client.available())
    {
      String line = client.readStringUntil('\r');
      Serial.print(line);
    }
  }
  client.stop();
}

// This function is called when a name is resolved via mDNS/Bonjour. We set
// this up in the setup() function above. The name you give to this callback
// function does not matter at all, but it must take exactly these arguments
// (a const char*, which is the hostName you wanted resolved, and a const
// byte[4], which contains the IP address of the host on success, or NULL if
// the name resolution timed out).
void nameFound(const char *name, IPAddress curIp)
{
  if (curIp != INADDR_NONE)
  {
    Serial.print("The IP address for '");
    Serial.print(name);
    Serial.print("' is ");
    Serial.println(curIp);
    ip = curIp;
    server_url = "https://" + ip.toString() + "/video_stream";
    Serial.print("Server URL is ");
    Serial.println(server_url);
    server_found = true;
  }
  else
  {
    Serial.print("Resolving '");
    Serial.print(name);
    Serial.println("' timed out.");
  }
}

void resolveHostIp(void *parameter)
{
  int loopWait_ms = 5000;
  while (ip == INADDR_NONE)
  {
    // You can use the "isResolvingName()" function to find out whether the
    // mDNS library is currently resolving a host name.
    // If so, we skip this input, since we want our previous request to continue.
    if (!mdns.isResolvingName())
    {
      // Now we tell the mDNS library to resolve the host name. We give it a
      // timeout of 5 seconds (e.g. 5000 milliseconds) to find an answer. The
      // library will automatically resend the query every second until it
      // either receives an answer or your timeout is reached - In either case,
      // the callback function you specified in setup() will be called.
      mdns.resolveName(MDNS_HOSTNAME.c_str(), loopWait_ms);
    }

    // This actually runs the mDNS module. YOU HAVE TO CALL THIS PERIODICALLY,
    // OR NOTHING WILL WORK! Preferably, call it once per loop().
    mdns.run();
    vTaskDelay(pdMS_TO_TICKS(loopWait_ms)); // Delay for 1000 milliseconds (1 second)
  }

  // Task complete, delete the task
  vTaskDelete(NULL);
}

// Function to initialize camera
void initCamera(void *parameter)
{
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
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
    ESP.restart();
  }

  // Task complete, delete the task
  vTaskDelete(NULL);
}

void setup()
{
  Serial.begin(115200);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");

  // Initialize the mDNS library. You can now reach or ping this
  // Arduino via the host name "arduino.local", provided that your operating
  // system is mDNS/Bonjour-enabled (such as macOS).
  // Always call this before any other method!
  mdns.begin(WiFi.localIP(), SOURCE_ID);
  // We specify the function that the mDNS library will call when it
  // resolves a host name. In this case, we will call the function named
  // "nameFound".
  mdns.setNameResolvedCallback(nameFound);

  // Create tasks for camera initialization and image capture
  xTaskCreatePinnedToCore(resolveHostIp, "resolveHostIp", 4096, NULL, 10, NULL, 1);
  xTaskCreatePinnedToCore(initCamera, "initCamera", 4096, NULL, 7, NULL, 1);
  xTaskCreatePinnedToCore(captureAndPublishImage, "captureAndPublishImage", 16384, NULL, 5, NULL, 1); // 16384 stack depth
}

void loop()
{
  // This loop will not execute since tasks are running in FreeRTOS
}
