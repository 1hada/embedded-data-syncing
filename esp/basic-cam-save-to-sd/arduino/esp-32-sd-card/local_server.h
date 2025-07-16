#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <FS.h>
#include <SD_MMC.h>

// Button definition (Flash button on most ESP32-CAMs)
const int BUTTON_PIN = 0;

// WiFi settings
const char* ssid = "espcamap";
char password[10];

// WebServer object on port 80
WebServer server(80);

// Server state
bool serverRunning = true;

// Performance optimizations
static bool camera_configured = false;
static unsigned long last_debug = 0;
static unsigned long last_adjustment = 0;

// Function prototypes
void generateRandomPassword();
void startCameraServer();
void stopCameraServer();
void handleRoot();
void handleYuvStream();
void handleFileList();
String getContentType(String filename);
bool setupCamera();
void setupSDCard();
void checkButtonPress();
void adjustExposureCompensation(int level);

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
  server.on("/stream", HTTP_GET, handleYuvStream);
  server.on("/files", HTTP_GET, handleFileList);
  
  server.begin();
}

void generateRandomPassword() {
  const char charset[] = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  for (int i = 0; i < 8; i++) {
    // FOR TESTING the random password is removed //     password[i] = charset[random(0, sizeof(charset) - 1)];
    password[i] = charset[i];
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

  // Enable hardware auto-exposure (let OV2640 handle it)
  s->set_vflip(s, 1);      // Vertical flip to correct inversion
  s->set_hmirror(s, 1);    // Horizontal mirror if needed
  
  // Optimized settings for speed
  s->set_exposure_ctrl(s, 1);    // Enable AEC
  s->set_aec2(s, 0);             // Disable AEC2 for speed
  s->set_ae_level(s, 0);         // Neutral AE level
  
  s->set_gain_ctrl(s, 1);        // Enable AGC
  s->set_agc_gain(s, 0);         // Let hardware decide
  
  s->set_whitebal(s, 1);         // Enable AWB
  s->set_awb_gain(s, 1);         // Enable AWB gain
  
  // Balanced settings for speed vs quality
  s->set_brightness(s, 0);       
  s->set_contrast(s, 0);         // Reduce processing
  s->set_saturation(s, 0);       
  s->set_sharpness(s, 0);        // Reduce processing for speed
  
  s->set_lenc(s, 0);             // Disable lens correction for speed
  s->set_denoise(s, 0);          // Disable denoise for speed
  
  // Set quality high for license plate detail
  s->set_quality(s, 63);          // Higher quality (1-63, lower = better)
  
  delay(500); // Reduced stabilization time
  
  Serial.println("Camera configured for speed with correct orientation");
}

// Simplified brightness calculation with sampling
int calculateBrightnessYUV422(camera_fb_t *fb) {
  if (!fb || fb->len == 0) return -1;
  
  // More aggressive sampling for speed
  uint32_t total_brightness = 0;
  int sample_count = 0;
  int step = 16; // Larger step for faster processing
  
  for (int i = 0; i < fb->len && i < 8000; i += step) { // Limit samples
    total_brightness += fb->buf[i];
    sample_count++;
  }
  
  return sample_count > 0 ? total_brightness / sample_count : -1;
}

// Simplified auto-exposure with less frequent adjustments
void manageAutoExposure(int current_brightness) {
  static int current_compensation = 0;
  const unsigned long adjustment_interval = 3000; // Slower adjustments
  
  if (millis() - last_adjustment < adjustment_interval) return;
  
  const int target_brightness = 140;
  const int tolerance = 40; // Wider tolerance
  
  int brightness_diff = target_brightness - current_brightness;
  
  if (abs(brightness_diff) > tolerance) {
    int new_compensation = current_compensation;
    
    if (brightness_diff > 60) {
      new_compensation = std::min(current_compensation + 1, 2);
    } else if (brightness_diff < -60) {
      new_compensation = std::max(current_compensation - 1, -2);
    }
    
    if (new_compensation != current_compensation) {
      adjustExposureCompensation(new_compensation);
      current_compensation = new_compensation;
      Serial.printf("Auto-exposure: Brightness %d, Compensation: %d\n", 
                    current_brightness, new_compensation);
    }
    
    last_adjustment = millis();
  }
}

void handleYuvStream() {
  Serial.println("Serving optimized YUV422→JPEG stream...");
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
  
  // Performance tracking
  unsigned long frame_start, conversion_time;
  int frame_count = 0;
  unsigned long fps_start = millis();
  
  while (client.connected()) {
    frame_start = millis();
    
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      delay(50);
      continue;
    }
    
    // Simplified brightness calculation (less frequent)
    int brightness = -1;
    if (frame_count % 10 == 0) { // Only every 10th frame
      brightness = calculateBrightnessYUV422(fb);
      if (brightness >= 0) {
        manageAutoExposure(brightness);
      }
    }
    
    // Convert YUV422 to JPEG with optimized quality
    bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len); // Reduced quality for speed
    conversion_time = millis() - frame_start;
    
    esp_camera_fb_return(fb);
    fb = NULL;
    
    if (!jpeg_converted || !_jpg_buf) {
      Serial.println("YUV422→JPEG conversion failed");
      delay(10);
      continue;
    }
    
    // Send multipart boundary and headers
    client.println("--jpgboundary");
    client.println("Content-Type: image/jpeg");
    client.println("Content-Length: " + String(_jpg_buf_len));
    client.println();
    
    // Send the converted JPEG data
    client.write(_jpg_buf, _jpg_buf_len);
    client.println();
    
    // Clean up
    free(_jpg_buf);
    _jpg_buf = NULL;
    
    frame_count++;
    
    // Performance stats every 5 seconds
    if (millis() - last_debug > 5000) {
      unsigned long elapsed = millis() - fps_start;
      float fps = (frame_count * 1000.0) / elapsed;
      Serial.printf("FPS: %.1f, Avg conversion: %lums, Brightness: %d\n", 
                    fps, conversion_time, brightness);
      last_debug = millis();
      frame_count = 0;
      fps_start = millis();
    }
    
    // Minimal delay for maximum speed
    delay(10);
  }
  
  Serial.println("Client disconnected from optimized stream.");
}

void adjustExposureCompensation(int level) {
  sensor_t *s = esp_camera_sensor_get();
  if (!s) return;
  
  level = constrain(level, -2, 2);
  s->set_ae_level(s, level);
  
  Serial.printf("Exposure compensation set to: %d\n", level);
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