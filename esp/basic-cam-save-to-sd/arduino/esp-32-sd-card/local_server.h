#ifndef LOCAL_SERVER_H
#define LOCAL_SERVER_H

#include "esp_camera.h"
#include "visual_processing.h"
#include <WiFi.h>
#include <WebServer.h>
#include <FS.h>
#include <SD_MMC.h>

// Button definition (Flash button on most ESP32-CAMs)
const int BUTTON_PIN = 0;

// WiFi settings
const char* ssid = "ESP32Network";
char password[10];

// WebServer object on port 80
WebServer server(80);

// Server state
bool serverRunning = true;

// Performance optimizations
static bool camera_configured = false;
static unsigned long last_debug = 0;
static unsigned long last_adjustment = 0;
static int brightness = -1;

// Function prototypes
void generateRandomPassword();
void startCameraServer();
void stopCameraServer();
void handleRoot();
void handleStream();
void handleFileList();
String getContentType(String filename);
bool setupCamera();
void setupSDCard();
void checkButtonPress();
void adjustExposureCompensation(int level);
void calculateAndManageBrightness(camera_fb_t *fb, int frame_count);

void setupServer() {
  generateRandomPassword();
  Serial.print("Generated AP Password: ");
  Serial.println(password);
  
  WiFi.softAP(ssid, password, 1, true, 4);
  IPAddress IP = WiFi.softAPIP();
  Serial.print("AP IP address: ");
  Serial.println(IP);
  Serial.print("AP MAC Address: ");
  Serial.println(WiFi.softAPmacAddress());
  Serial.println("Connect to this AP and navigate to http://" + IP.toString() + " in your browser.");
  
  server.on("/", HTTP_GET, handleRoot);
  server.on("/stream", HTTP_GET, handleStream);
  server.on("/files", HTTP_GET, handleFileList);
  
  server.begin();
}

void generateRandomPassword() {
  const char charset[] = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  for (int i = 0; i < 8; i++) {
    password[i] = charset[random(0, sizeof(charset) - 1)];
  }
  password[8] = '\0';
}

void handleRoot() {
  Serial.println("Handling Root...");
  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <title>ESP32-CAM Web Server</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }
        .container { display: flex; flex-wrap: wrap; justify-content: space-around; }
        .camera-feed, .file-list { border: 1px solid #ccc; padding: 15px; margin: 10px; border-radius: 8px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); background: white; }
        .camera-feed img { max-width: 100%; height: auto; display: block; margin: 0 auto; border-radius: 4px; }
        .file-list ul { list-style-type: none; padding: 0; max-height: 400px; overflow-y: auto; }
        .file-list li { padding: 5px 0; border-bottom: 1px dashed #eee; }
        .file-list li:last-child { border-bottom: none; }
        h2 { color: #333; }
        .warning { color: red; font-weight: bold; }
        .status { color: green; font-size: 14px; margin-top: 10px; }
    </style>
</head>
<body>
    <h1>ESP32-CAM Control</h1>
    <div class="status">Optimized for speed - YUV422 stream</div>

    <div class="container">
        <div class="camera-feed">
            <h2>Live Camera Feed</h2>
            <img src="/stream" alt="Live Camera Feed" id="cameraImg">
        </div>

        <div class="file-list">
            <h2>SD Card Files</h2>
            <ul id="sdFiles"></ul>
            <p class="warning">Files cannot be accessed or downloaded through this interface directly.</p>
        </div>
    </div>

    <script>
        let fileRefreshInterval = 10000; // Reduced frequency to 10 seconds
        
        function fetchFiles() {
            fetch('/files')
                .then(response => response.text())
                .then(data => {
                    document.getElementById('sdFiles').innerHTML = data;
                })
                .catch(error => {
                    console.error('Error fetching file list:', error);
                    document.getElementById('sdFiles').innerHTML = '<li>Error loading files</li>';
                });
        }

        // Handle image loading errors
        document.getElementById('cameraImg').onerror = function() {
            console.log('Stream connection lost, retrying...');
            setTimeout(() => {
                this.src = '/stream?' + Date.now(); // Force refresh
            }, 2000);
        };

        // Fetch files less frequently to reduce server load
        setInterval(fetchFiles, fileRefreshInterval);
        fetchFiles(); // Initial fetch
    </script>
</body>
</html>
)rawliteral";
  server.send(200, "text/html", html);
}

// Optimized camera configuration for speed and correct orientation
void configureCameraForDashCam() {
  sensor_t *s = esp_camera_sensor_get();
  if (!s) return;

  s->set_quality(s, 10);
  s->set_contrast(s, 0);
  s->set_brightness(s, 0);
  s->set_saturation(s, 0);
  s->set_gainceiling(s, (gainceiling_t)20);
  s->set_colorbar(s, false);
  //s->set_whitebal(s, val);
  //s->set_gain_ctrl(s, val);
  //s->set_exposure_ctrl(s, val);
  s->set_hmirror(s, false);
  s->set_vflip(s, false);
  s->set_awb_gain(s, false);
  s->set_agc_gain(s, false);
  //s->set_aec_value(s, 2);
  s->set_aec2(s, true);
  s->set_dcw(s, false);
  s->set_bpc(s, false);
  s->set_wpc(s, true);
  s->set_raw_gma(s, true);
  s->set_lenc(s, false);
  //s->set_special_effect(s, val);
  //s->set_wb_mode(s, val);
  s->set_ae_level(s, 2);
  delay(500); // Reduced stabilization time
  
  Serial.println("Camera configured for speed with correct orientation");
}

void calculateAndManageBrightness(camera_fb_t *fb, int frame_count) {
  // Simplified brightness calculation (less frequent)
  if (frame_count % 20 != 0) return; // Only every 20th frame

  int prev_brightness = brightness ;

  if (fb->format == PIXFORMAT_YUV422) {
    brightness = calculateBrightnessYUV422(fb);
  } else if (fb->format == PIXFORMAT_JPEG) {
    // Use a thumbnail or other method internally
    brightness = calculateBrightnessJPEG(fb);
  } else {
    Serial.printf("Brightness calculation not supported for pixformat: %d\n", fb->format);
    return;
  }

  if (brightness != prev_brightness) {
    manageAutoExposure(brightness);
  }
}

void handleStream() { // Renamed from handleStream for broader applicability
  Serial.println("Serving camera stream...");
  WiFiClient client = server.client();

  // Optimized HTTP headers
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: multipart/x-mixed-replace; boundary=--jpgboundary");
  client.println("Access-Control-Allow-Origin: *");
  client.println("Cache-Control: no-cache");
  client.println();

  // Configure camera once
  if (!camera_configured) {
    configureCameraForDashCam();
    camera_configured = true;
  }

  camera_fb_t *fb = NULL;
  size_t _jpg_buf_len = 0;
  uint8_t *_jpg_buf = NULL;
  bool jpeg_needs_free = false; // Flag to indicate if _jpg_buf needs to be freed

  // Performance tracking
  unsigned long frame_start, conversion_time;
  int frame_count = 0;
  unsigned long fps_start = millis();
  // last_debug is assumed to be a global/class member as per original code

  while (client.connected()) {
    frame_start = millis();

    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      delay(50);
      continue;
    }

    // Simplified brightness calculation
    calculateAndManageBrightness(fb, frame_count);

    // Handle different pixel formats
    if (fb->format == PIXFORMAT_YUV422) {
      // Convert YUV422 to JPEG with optimized quality
      bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len); // Reduced quality for speed
      jpeg_needs_free = true; // We allocated a new JPEG buffer, so it needs to be freed
      conversion_time = millis() - frame_start;

      esp_camera_fb_return(fb); // Return the YUV frame buffer
      fb = NULL;

      if (!jpeg_converted || !_jpg_buf) {
        Serial.println("YUV422→JPEG conversion failed");
        delay(10);
        continue;
      }
    } else if (fb->format == PIXFORMAT_JPEG) {
      // If the camera directly provides JPEG, use its buffer
      _jpg_buf = fb->buf;
      _jpg_buf_len = fb->len;
      jpeg_needs_free = false; // The camera frame buffer will be returned, not explicitly freed here
      conversion_time = millis() - frame_start; // Time taken is just capture time

      // Return the frame buffer *after* using its data
      esp_camera_fb_return(fb);
      fb = NULL;

      if (!_jpg_buf) {
        Serial.println("JPEG buffer is null from camera");
        delay(10);
        continue;
      }
    } else {
      Serial.printf("Unsupported pixel format: %d\n", fb->format);
      esp_camera_fb_return(fb);
      fb = NULL;
      delay(10);
      continue;
    }

    // Send multipart boundary and headers
    client.println("--jpgboundary");
    client.println("Content-Type: image/jpeg");
    client.println("Content-Length: " + String(_jpg_buf_len));
    client.println();

    // Send the JPEG data
    client.write(_jpg_buf, _jpg_buf_len);
    client.println();

    // Clean up if the JPEG buffer was allocated by us
    if (jpeg_needs_free && _jpg_buf) {
      free(_jpg_buf);
      _jpg_buf = NULL;
    }

    frame_count++;

    // Performance stats every 5 seconds
    if (millis() - last_debug > 5000) {
      unsigned long elapsed = millis() - fps_start;
      float fps = (frame_count * 1000.0) / elapsed;
      Serial.printf("FPS: %.1f, Avg conversion/capture: %lums, Brightness: %d\n",
                    fps, conversion_time, brightness);
      last_debug = millis();
      frame_count = 0;
      fps_start = millis();
    }

    // Minimal delay for maximum speed
    delay(10);
  }

  // Ensure any lingering fb or _jpg_buf is freed if client disconnects mid-loop
  if (fb) { // If loop exited with an active fb
    esp_camera_fb_return(fb);
  }
  if (jpeg_needs_free && _jpg_buf) { // If loop exited with an active _jpg_buf needing free
    free(_jpg_buf);
  }

  Serial.println("Client disconnected from stream.");
}

void handleFileList() {
  Serial.println("Serving File List...");
  String list = "";
  
  if (!SD_MMC.begin()) {
    list = "<li>SD Card not mounted.</li>";
  } else {
    File root = SD_MMC.open("/");
    if (root) {
      File file = root.openNextFile();
      int file_count = 0;
      
      while (file && file_count < 50) { // Limit files shown for speed
        if (file.isDirectory()) {
          list += "<li><strong>" + String(file.name()) + "/</strong></li>";
        } else {
          list += "<li>" + String(file.name()) + " (" + String(file.size()) + " bytes)</li>";
        }
        file = root.openNextFile();
        file_count++;
      }
      
      if (file_count == 0) {
        list = "<li>No files found on SD card.</li>";
      } else if (file_count >= 50) {
        list += "<li><em>... (showing first 50 files)</em></li>";
      }
      
    } else {
      list = "<li>Could not open root directory on SD card.</li>";
    }
  }
  
  server.send(200, "text/html", list);
}

String getContentType(String filename) {
  if (filename.endsWith(".html")) return "text/html";
  else if (filename.endsWith(".css")) return "text/css";
  else if (filename.endsWith(".js")) return "application/javascript";
  else if (filename.endsWith(".png")) return "image/png";
  else if (filename.endsWith(".gif")) return "image/gif";
  else if (filename.endsWith(".jpg")) return "image/jpeg";
  else if (filename.endsWith(".ico")) return "image/x-icon";
  else if (filename.endsWith(".xml")) return "text/xml";
  else if (filename.endsWith(".pdf")) return "application/x-pdf";
  else if (filename.endsWith(".zip")) return "application/x-zip";
  else if (filename.endsWith(".gz")) return "application/x-gzip";
  return "text/plain";
}

#endif // LOCAL_SERVER_H
