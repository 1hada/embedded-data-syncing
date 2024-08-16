#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

#define CAMERA_MODEL_AI_THINKER // Has PSRAM

#include "camera_pins.h"


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

#include "secrets.h"
#include "hardware_constants.h"

httpd_handle_t camera_httpd = NULL;

// Network data
WiFiUDP udp;
MDNS mdns(udp);
int loopWait_ms = 1000;
IPAddress ip;
String server_url = "https://your_server_ip/video_stream";
bool remote_server_found = false;
bool esp_server_running = false;
// Use WiFiClientSecure for HTTPS but you must eventually also use the keys and certificates, TODO
WiFiClientSecure client;


// Helpers
void nameFound(const char *name, IPAddress ip);
void resolveHostIp();
void initCamera();


esp_err_t print_request_handler(httpd_req_t *req) {
    char buffer[1024];
    int ret, remaining = req->content_len;

    // Print the request method and URI
    Serial.printf("Request URI: %s\n", req->uri);
    Serial.printf("Request Method: %s\n", req->method == HTTP_GET ? "GET" : "POST");

    // Print headers
    Serial.println("Headers:");
    httpd_req_get_hdr_value_len(req, "Host");
    httpd_req_get_hdr_value_str(req, "Host", buffer, sizeof(buffer));
    Serial.printf("Host: %s\n", buffer);

    httpd_req_get_hdr_value_len(req, "User-Agent");
    httpd_req_get_hdr_value_str(req, "User-Agent", buffer, sizeof(buffer));
    Serial.printf("User-Agent: %s\n", buffer);

    httpd_req_get_hdr_value_len(req, "Accept");
    httpd_req_get_hdr_value_str(req, "Accept", buffer, sizeof(buffer));
    Serial.printf("Accept: %s\n", buffer);

    httpd_req_get_hdr_value_len(req, "Origin");
    httpd_req_get_hdr_value_str(req, "Origin", buffer, sizeof(buffer));
    Serial.printf("Origin: %s\n", buffer);

    // Read and print the request body (if any)
    Serial.println("Body:");
    while (remaining > 0) {
        if ((ret = httpd_req_recv(req, buffer, std::min<int>(remaining, sizeof(buffer)))) <= 0) {
            if (ret == HTTPD_SOCK_ERR_TIMEOUT) {
                continue;
            }
            return ESP_FAIL;
        }
        buffer[ret] = '\0';
        Serial.printf("%s", buffer);
        remaining -= ret;
    }
    Serial.println();
    Serial.println("Done printing request");

    return ESP_OK;
}

esp_err_t stream_handler(httpd_req_t *req) {
    print_request_handler(req);
    
    camera_fb_t *fb = NULL;
    esp_err_t res = ESP_OK;

    char part_buf[64];
    static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=frame";
    static const char* _STREAM_BOUNDARY = "\r\n--frame\r\n";
    static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

    /*
    // Extract the Origin header
    char origin[128] = {0};
    size_t origin_len = httpd_req_get_hdr_value_len(req, "Host");
    if (origin_len > 0 && origin_len < sizeof(origin)) {
        httpd_req_get_hdr_value_str(req, "Host", origin, sizeof(origin));
    }
    Serial.print("Handling Request from ");
    Serial.print(origin);
    Serial.print(" trying to match with ");
    Serial.print(ip.toString());
    Serial.println();

    // Check if the origin matches the allowed IP prefix
    if (strncmp(origin, ip.toString().c_str(), strlen(ip.toString().c_str())) == 0) {
        Serial.println("Allowed Prefix Found");
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", origin);
    } else {
        Serial.println("Failed to match Prefix");
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "null");
        return ESP_FAIL;
    }
    */

    httpd_resp_set_hdr(req, "X-Framerate", "25");
    httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);

    while (true) {
        fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            return ESP_FAIL;
        }

        size_t hlen = snprintf(part_buf, 64, _STREAM_PART, fb->len);
        res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        if (res != ESP_OK) {
            esp_camera_fb_return(fb);
            break;
        }
        res = httpd_resp_send_chunk(req, part_buf, hlen);
        if (res != ESP_OK) {
            esp_camera_fb_return(fb);
            break;
        }
        res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
        if (res != ESP_OK) {
            esp_camera_fb_return(fb);
            break;
        }
        res = httpd_resp_send_chunk(req, "\r\n", 2);
        if (res != ESP_OK) {
            esp_camera_fb_return(fb);
            break;
        }
        esp_camera_fb_return(fb);

        delay(100); // Adjust delay as needed to control frame rate
    }

    // Go ahead and restart in case the host machine of interest has had it's IP changed
    // Note : in a high security scenario this could create an issue if multiple machines have the same MDNS name
    // so you might want to make the address static
    ESP.restart();
    return res;
}

void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    httpd_uri_t stream_uri = {
        .uri       = "/stream",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };


  Serial.print("My IP address: ");
  Serial.println(WiFi.localIP());
  Serial.printf("Starting web server on port: '%d'\n", config.server_port);
  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
      httpd_register_uri_handler(camera_httpd, &stream_uri);
  }
  config.server_port += 1;
  config.ctrl_port += 1;

  esp_server_running = true;
}


// Function to initialize camera
void initCamera()
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
  config.frame_size = FRAMESIZE_VGA; // FRAMESIZE_ + QVGA|CIF|VGA|SVGA|XGA|SXGA|UXGA
  config.jpeg_quality = 10;
  config.fb_count = 1;

  // Initialize camera with specified configuration
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK)
  {
    Serial.printf("Camera init failed with error 0x%x", err);
    ESP.restart();
  }
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
    server_url = "http://" + ip.toString() + "/video_stream";
    Serial.print("Server URL is ");
    Serial.println(server_url);
    remote_server_found = true;
  }
  else
  {
    Serial.print("Resolving '");
    Serial.print(name);
    Serial.println("' timed out.");
  }
}

void resolveHostIp()
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
}

void setup() {
    Serial.begin(115200);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long startTime = millis();  // Record the start time
    while (WiFi.status() != WL_CONNECTED) {
        delay(1000);
        Serial.println("Connecting to WiFi...");

        if (millis() - startTime >= 60000) {  // 1 minute timeout
            Serial.println("Failed to connect to WiFi. Restarting...");
            ESP.restart();  // Reset the ESP device
        }
    }

    Serial.println("Connected to WiFi");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());


    // Initialize the mDNS library. You can now reach or ping this
    // Arduino via the host name "arduino.local", provided that your operating
    // system is mDNS/Bonjour-enabled (such as macOS).
    // Always call this before any other method!
    mdns.begin(WiFi.localIP(), SOURCE_ID.c_str());
    // We specify the function that the mDNS library will call when it
    // resolves a host name. In this case, we will call the function named
    // "nameFound".
    mdns.setNameResolvedCallback(nameFound);
    mdns.addServiceRecord(SRV_RECORD.c_str(),
                        80,
                        MDNSServiceTCP);
    initCamera();
}

void loop() {
    if (ip == INADDR_NONE){
        resolveHostIp();
    }
    else{
        if (!esp_server_running)
        {
            // only starts the server if the HostIP is resolved
            startCameraServer();
        }
    }
    // This actually runs the mDNS module. YOU HAVE TO CALL THIS PERIODICALLY,
    // OR NOTHING WILL WORK! Preferably, call it once per loop().
    mdns.run();
    delay(loopWait_ms); // Adjust delay as needed to control frame rate
}
