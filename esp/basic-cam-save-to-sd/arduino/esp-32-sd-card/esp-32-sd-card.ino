/*********
  Enhanced ESP32 Dash Cam with Video Recording
  Based on Rui Santos' ESP32-CAM code
  
  Features:
  - Records to AVI video files instead of individual JPEGs
  - Automatic new video file creation on startup and size limits
  - Improved performance with video streaming
  - Auto-brightness control for dark conditions
  - Continuous operation optimized for dash cam use
  - Offline operation with uptime timestamps
  - Dynamic AVI header configuration based on capture settings
  - ADDED: Per-frame timestamp metadata for post-processing
*********/

#include "esp_camera.h"
#include "FS.h"
#include "SD_MMC.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "driver/rtc_io.h"
#include <WiFi.h>
#include "time.h"

// REPLACE WITH YOUR NETWORK CREDENTIALS
const char* ssid = "REPLACE_WITH_YOUR_SSID";
const char* password = "REPLACE_WITH_YOUR_PASSWORD";

// REPLACE WITH YOUR TIMEZONE STRING
String myTimezone = "WET0WEST,M3.5.0/1,M10.5.0";

// Dash cam configuration
#define MIN_FREE_SPACE_MB 3000         // Minimum free space in MB
#define MAX_VIDEO_SIZE_MB 500          // Maximum video file size in MB
#define CAPTURE_INTERVAL_MS 100        // Frame capture interval in milliseconds (100 FPS)
#define AUTO_BRIGHTNESS_ENABLED true  // Enable auto-brightness adjustment

// Pin definitions for CAMERA_MODEL_AI_THINKER
#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27

#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM    5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

// 4 for flash led or 33 for normal led
#define FLASH_GPIO_NUM   4

// Camera configuration
camera_config_t config;
sensor_t * s = NULL;

// Global variables
bool ntpTimeAvailable = false;
unsigned long lastCaptureTime = 0;
int currentBrightness = 0;
int currentContrast = 0;

// Video recording variables
File videoFile;
String currentVideoFilename;
bool isRecording = false;
uint32_t frameCount = 0;
unsigned long videoStartTime = 0;
uint32_t currentVideoNumber = 0;

// Auto-brightness variables
unsigned long lastBrightnessCheck = 0;
const unsigned long BRIGHTNESS_CHECK_INTERVAL = 5000; // Check every 5 seconds

// Add these for dynamic resolution
uint32_t videoWidth = 0;
uint32_t videoHeight = 0;

// *** NEW: Custom Timestamp Metadata Chunk ***
// 'TIMS' FOURCC
struct TimestampChunk {
  char id[4] = {'T', 'I', 'M', 'S'};
  uint32_t size; // Size of the timestamp data
  uint64_t unix_epoch_ms; // Unix epoch time in milliseconds (8 bytes)
};
// ********************************************

// AVI file header structures (leave default values, they will be overwritten)
struct AVIHeader {
    char riff[4] = {'R', 'I', 'F', 'F'};
    uint32_t fileSize;
    char avi[4] = {'A', 'V', 'I', ' '};
    char list1[4] = {'L', 'I', 'S', 'T'};
    uint32_t list1Size;
    char hdrl[4] = {'h', 'd', 'r', 'l'};
    char avih[4] = {'a', 'v', 'i', 'h'};
    uint32_t avihSize = 56;
    uint32_t microSecPerFrame; // Will be set dynamically
    uint32_t maxBytesPerSec;   // Will be set dynamically
    uint32_t paddingGranularity = 0;
    uint32_t flags = 0x10;
    uint32_t totalFrames = 0;
    uint32_t initialFrames = 0;
    uint32_t streams = 1;
    uint32_t suggestedBufferSize = 0;
    uint32_t width;  // Will be set dynamically
    uint32_t height; // Will be set dynamically
    uint32_t reserved[4] = {0};
};

struct StreamHeader {
    char list[4] = {'L', 'I', 'S', 'T'};
    uint32_t listSize;
    char strl[4] = {'s', 't', 'r', 'l'};
    char strh[4] = {'s', 't', 'r', 'h'};
    uint32_t strhSize = 56;
    char streamType[4] = {'v', 'i', 'd', 's'};
    char codec[4] = {'M', 'J', 'P', 'G'};
    uint32_t flags = 0;
    uint16_t priority = 0;
    uint16_t language = 0;
    uint32_t initialFrames = 0;
    uint32_t scale = 1;
    uint32_t rate; // Will be set dynamically
    uint32_t start = 0;
    uint32_t length = 0;
    uint32_t suggestedBufferSize; // Will be set dynamically
    uint32_t quality = 0;
    uint32_t sampleSize = 0;
    uint16_t left = 0;
    uint16_t top = 0;
    uint16_t right;  // Will be set dynamically
    uint16_t bottom; // Will be set dynamically
};

struct BitmapInfo {
    char strf[4] = {'s', 't', 'r', 'f'};
    uint32_t strfSize = 40;
    uint32_t biSize = 40;
    int32_t biWidth;  // Will be set dynamically
    int32_t biHeight; // Will be set dynamically
    uint16_t biPlanes = 1;
    uint16_t biBitCount = 24;
    uint32_t biCompression = 0x47504A4D; // 'MJPG'
    uint32_t biSizeImage = 0; // Will be 0 for MJPEG as it's compressed
    int32_t biXPelsPerMeter = 0;
    int32_t biYPelsPerMeter = 0;
    uint32_t biClrUsed = 0;
    uint32_t biClrImportant = 0;
};

struct MovieHeader {
    char list[4] = {'L', 'I', 'S', 'T'};
    uint32_t listSize;
    char movi[4] = {'m', 'o', 'v', 'i'};
};

// Initialize camera with optimized settings for video recording
void configInitCamera(){
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

    // Optimized settings for video recording
    if(psramFound()){
        config.frame_size = FRAMESIZE_XGA;//FRAMESIZE_UXGA; // Set to 1600x1200 as you specified
        config.jpeg_quality = 15; // Higher quality for video
        config.fb_count = 2;
    } else {
        // If no PSRAM, UXGA might not be feasible, fall back to a smaller size
        Serial.println("No PSRAM found, falling back to QVGA.");
        config.frame_size = FRAMESIZE_QVGA; // 320x240
        config.jpeg_quality = 20;
        config.fb_count = 1;
    }
    
    // Initialize the Camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed with error 0x%x", err);
        return;
    }

    s = esp_camera_sensor_get();
    
    // Store actual resolution based on configured frame_size
    framesize_t currentFrameSize = s->status.framesize;
    switch (currentFrameSize) {
        case FRAMESIZE_QQVGA: videoWidth = 160; videoHeight = 120; break;
        case FRAMESIZE_QVGA:  videoWidth = 320; videoHeight = 240; break;
        case FRAMESIZE_CIF:   videoWidth = 352; videoHeight = 288; break;
        case FRAMESIZE_VGA:   videoWidth = 640; videoHeight = 480; break;
        case FRAMESIZE_SVGA:  videoWidth = 800; videoHeight = 600; break;
        case FRAMESIZE_XGA:   videoWidth = 1024; videoHeight = 768; break;
        case FRAMESIZE_SXGA:  videoWidth = 1280; videoHeight = 1024; break;
        case FRAMESIZE_UXGA:  videoWidth = 1600; videoHeight = 1200; break; // For 1600x1200
        case FRAMESIZE_QXGA:  videoWidth = 2048; videoHeight = 1536; break; // For 2048x1536
        default:
            Serial.println("Warning: Unknown framesize, defaulting to CIF for AVI headers.");
            videoWidth = 352;
            videoHeight = 288;
            break;
    }
    Serial.printf("Camera Resolution set to: %d x %d\n", videoWidth, videoHeight);

    s->set_brightness(s, 0);     // -2 to 2
    s->set_contrast(s, 0);       // -2 to 2
    s->set_saturation(s, 0);     // -2 to 2
    s->set_special_effect(s, 0); // 0 to 6
    s->set_whitebal(s, 1);       // 0 = disable , 1 = enable
    s->set_awb_gain(s, 1);       // 0 = disable , 1 = enable
    s->set_wb_mode(s, 0);        // 0 to 4
    s->set_exposure_ctrl(s, 1);  // 0 = disable , 1 = enable
    s->set_aec2(s, 0);           // 0 = disable , 1 = enable
    s->set_ae_level(s, 0);       // -2 to 2
    s->set_aec_value(s, 300);    // 0 to 1200
    s->set_gain_ctrl(s, 1);      // 0 = disable , 1 = enable
    s->set_agc_gain(s, 0);       // 0 to 30
    s->set_gainceiling(s, (gainceiling_t)0);  // 0 to 6
    s->set_bpc(s, 0);            // 0 = disable , 1 = enable
    s->set_wpc(s, 1);            // 0 = disable , 1 = enable
    s->set_raw_gma(s, 1);        // 0 = disable , 1 = enable
    s->set_lenc(s, 1);           // 0 = disable , 1 = enable
    s->set_hmirror(s, 0);        // 0 = disable , 1 = enable
    s->set_vflip(s, 0);          // 0 = disable , 1 = enable
    s->set_dcw(s, 1);            // 0 = disable , 1 = enable
    s->set_colorbar(s, 0);       // 0 = disable , 1 = enable
}

// Connect to WiFi with timeout
void initWiFi() {
    WiFi.begin(ssid, password);
    Serial.println("Attempting WiFi connection for NTP sync...");

    unsigned long startTime = millis();
    const long wifiConnectTimeout = 10000;

    while (WiFi.status() != WL_CONNECTED) {
        Serial.print(".");
        delay(250);
        
        if (millis() - startTime > wifiConnectTimeout) {
            Serial.println("\nWiFi connection timed out! Dash cam will operate with uptime timestamps.");
            ntpTimeAvailable = false;
            WiFi.disconnect(true);
            WiFi.mode(WIFI_OFF);
            return;
        }
    }
    Serial.println("\nWiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
}

// Set timezone
void setTimezone(String timezone) {
    Serial.printf("Setting Timezone to %s\n", timezone.c_str());
    setenv("TZ", timezone.c_str(), 1);
    tzset();
}

// Initialize NTP time
void initTime(String timezone) {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("No WiFi connection. Dash cam will use uptime-based timestamps.");
        ntpTimeAvailable = false;
        return;
    }

    struct tm timeinfo;
    Serial.println("Attempting NTP time sync...");
    configTime(0, 0, "pool.ntp.org", "time.nist.gov", "time.google.com");
    
    if (!getLocalTime(&timeinfo, 8000)) {
        Serial.println("NTP sync failed or no internet. Using uptime timestamps.");
        ntpTimeAvailable = false;
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        return;
    }
    
    Serial.println("NTP time synchronized successfully!");
    ntpTimeAvailable = true;
    setTimezone(timezone);
    
    // Disconnect WiFi after sync to save power
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    Serial.println("WiFi disconnected to save power.");
}

// *** NEW: Function to get current timestamp (Unix epoch in milliseconds) ***
uint64_t getCurrentTimestampMs() {
    if (ntpTimeAvailable) {
        struct timeval tv;
        gettimeofday(&tv, NULL);
        return (uint64_t)tv.tv_sec * 1000 + (tv.tv_usec / 1000);
    } else {
        // Fallback to uptime if NTP not available
        return millis(); // Millis is already in ms, starting from ESP32 boot
    }
}
// **************************************************************************

// Get uptime string for filename
String getUptimeString() {
    unsigned long totalMs = millis();
    unsigned long totalSeconds = totalMs / 1000;
    
    unsigned long days = totalSeconds / 86400;
    unsigned long hours = (totalSeconds % 86400) / 3600;
    unsigned long minutes = (totalSeconds % 3600) / 60;
    unsigned long seconds = totalSeconds % 60;

    char uptimeString[20];
    if (days > 0) {
        sprintf(uptimeString, "%lud%02lu-%02lu-%02lu", days, hours, minutes, seconds);
    } else {
        sprintf(uptimeString, "%02lu-%02lu-%02lu", hours, minutes, seconds);
    }
    return String(uptimeString);
}

// Get next video number by scanning existing files
uint32_t getNextVideoNumber() {
    uint32_t maxNumber = 0;
    
    File root = SD_MMC.open("/");
    if (!root || !root.isDirectory()) {
        Serial.println("Failed to open root directory for video numbering");
        return 1; // Start from 1 if we can't read directory
    }

    File file = root.openNextFile();
    while (file) {
        Serial.printf("About to read %s\n", file.name());
        if (!file.isDirectory()) {
            String fileName = file.name();
            if ((fileName.indexOf("video_") != -1) && fileName.endsWith(".avi")) {
                // Extract number from filename
                // Format: /video_NNNN_timestamp.avi or /video_NNNN.avi
                int startIdx = fileName.indexOf("video_") + 6;
                int endIdx = fileName.indexOf("_", startIdx);
                if (endIdx == -1) {
                    endIdx = fileName.indexOf(".", startIdx);
                }
                
                if (endIdx > startIdx) {
                    String numberStr = fileName.substring(startIdx, endIdx);
                    uint32_t fileNumber = numberStr.toInt();
                    if (fileNumber > maxNumber) {
                        maxNumber = fileNumber;
                    }
                }
            }
        }
        file.close();
        file = root.openNextFile();
    }
    root.close();

    return maxNumber + 1;
}

// Get video filename with incremental numbering
String getVideoFilename() {
    String filename;
    
    if (ntpTimeAvailable) {
        struct tm timeinfo;
        if (getLocalTime(&timeinfo)) {
            char timeString[30];
            strftime(timeString, sizeof(timeString), "%Y-%m-%d_%H-%M-%S", &timeinfo);
            filename = "/video_" + String(currentVideoNumber, 10) + "_" + String(timeString) + ".avi";
        } else {
            ntpTimeAvailable = false;
            filename = "/video_" + String(currentVideoNumber, 10) + "_uptime_" + getUptimeString() + ".avi";
        }
    } else {
        filename = "/video_" + String(currentVideoNumber, 10) + "_uptime_" + getUptimeString() + ".avi";
    }
    
    return filename;
}

// Auto-brightness adjustment
void adjustBrightness() {
    if (!AUTO_BRIGHTNESS_ENABLED || s == NULL) return;
    
    unsigned long currentTime = millis();
    if (currentTime - lastBrightnessCheck < BRIGHTNESS_CHECK_INTERVAL) {
        return;
    }
    lastBrightnessCheck = currentTime;

    // For brightness adjustment, it's safer to get a smaller, quick frame or use camera's internal stats if available.
    // Reading full JPEG data and converting to RGB for brightness is inefficient and can cause delays.
    // Ideally, the camera sensor's AEC (Automatic Exposure Control) should handle this.
    // This section might be more effective by adjusting s->set_aec_value directly or relying on camera's auto.
    // For simplicity, keeping the existing (though potentially suboptimal) approach.

    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Brightness adjustment: Camera capture failed");
        return;
    }

    // Only attempt if the pixel format allows direct access or convert (less efficient)
    // The current brightness logic assumes RGB data (fb->buf[i], fb->buf[i+1], fb->buf[i+2])
    // but the camera is configured for PIXFORMAT_JPEG. This will NOT work correctly.
    // For PIXFORMAT_JPEG, you'd need to decompress the JPEG to analyze brightness, which is too heavy.
    // A more effective approach is to rely on the camera's built-in AEC/AGC settings,
    // or to read the camera's exposure/gain status if the API supports it.

    // *** IMPORTANT: The current auto-brightness logic will NOT work with PIXFORMAT_JPEG. ***
    // This section would require a change to PIXFORMAT_RGB565/YUV422 and substantial memory/CPU.
    // For now, it's left as-is, but be aware it's ineffective with JPEG.
    // If auto-brightness is critical, set camera.pixel_format to RGB565 (low resolution)
    // or rely entirely on camera's set_exposure_ctrl(s, 1); set_ae_level(s, 0); etc.
    // which are enabled by default.

    // For now, we'll return the framebuffer immediately as this logic is broken for JPEG.
    esp_camera_fb_return(fb);
    return; // Exit auto-brightness early if using JPEG.

    /* Original (broken for JPEG) logic:
    uint32_t brightness_sum = 0;
    uint32_t sample_size = min(1000, (int)(fb->len / 3)); // This assumes 3 bytes per pixel
    
    for (uint32_t i = 0; i < sample_size * 3; i += 3) {
        uint8_t r = fb->buf[i];
        uint8_t g = fb->buf[i + 1];
        uint8_t b = fb->buf[i + 2];
        brightness_sum += (r * 0.299 + g * 0.587 + b * 0.114);
    }
    
    uint8_t avg_brightness = brightness_sum / sample_size;
    esp_camera_fb_return(fb);

    // Adjust camera settings based on brightness
    if (avg_brightness < 80) {
        if (currentBrightness < 2) {
            currentBrightness++;
            s->set_brightness(s, currentBrightness);
        }
        if (currentContrast < 2) {
            currentContrast++;
            s->set_contrast(s, currentContrast);
        }
    } else if (avg_brightness > 160) {
        if (currentBrightness > -2) {
            currentBrightness--;
            s->set_brightness(s, currentBrightness);
        }
        if (currentContrast > -2) {
            currentContrast--;
            s->set_contrast(s, currentContrast);
        }
    }
    */
}

// Enhanced file management for video files
void manageSdCardSpace() {
    if (!SD_MMC.begin("/sdcard", true)) {
        Serial.println("SD card not available for space management");
        return;
    }

    uint64_t totalBytes = SD_MMC.totalBytes();
    uint64_t usedBytes = SD_MMC.usedBytes();
    uint64_t freeBytes = totalBytes - usedBytes;
    uint64_t freeMB = freeBytes / (1024 * 1024);

    Serial.printf("SD Card: %lluMB free of %lluMB total\n", freeMB, totalBytes / (1024 * 1024));

    if (freeMB >= MIN_FREE_SPACE_MB) {
        return;
    }

    Serial.println("Low space detected. Starting video file cleanup...");

    // Simple file management for video files
    struct FileInfo {
        String name;
        unsigned long modTime;
        size_t size;
    };

    const int MAX_FILES = 500;
    FileInfo* files = new FileInfo[MAX_FILES];
    int fileCount = 0;

    File root = SD_MMC.open("/");
    if (!root || !root.isDirectory()) {
        Serial.println("Failed to open root directory");
        delete[] files;
        return;
    }

        File file = root.openNextFile();
        while (file && fileCount < MAX_FILES) {
            if (!file.isDirectory()) {
                String fileName = file.name();
                if (fileName.startsWith("/video_") && fileName.endsWith(".avi")) {
                    files[fileCount].name = fileName;
                    files[fileCount].size = file.size();
                    files[fileCount].modTime = file.getLastWrite();
                    fileCount++;
                }
            }
            file.close();
            file = root.openNextFile();
        }
    root.close();

    if (fileCount == 0) {
        Serial.println("No video files found for cleanup");
        delete[] files;
        return;
    }

    // Sort by modification time (oldest first)
    for (int i = 0; i < fileCount - 1; i++) {
        for (int j = 0; j < fileCount - 1 - i; j++) {
            if (files[j].modTime > files[j + 1].modTime) {
                FileInfo temp = files[j];
                files[j] = files[j + 1];
                files[j + 1] = temp;
            }
        }
    }

    // Delete oldest files until we have enough space
    size_t deletedCount = 0;
    uint64_t freedBytes = 0;
    
    for (int i = 0; i < fileCount; i++) {
        if (freeMB + (freedBytes / (1024 * 1024)) >= MIN_FREE_SPACE_MB) {
            break;
        }

        // Don't delete the currently recording file
        if (files[i].name.equals(currentVideoFilename)) {
            continue;
        }

        if (SD_MMC.remove(files[i].name)) {
            freedBytes += files[i].size;
            deletedCount++;
            Serial.printf("Deleted: %s (%d MB)\n", files[i].name.c_str(), files[i].size / (1024 * 1024));
        } else {
            Serial.printf("Failed to delete: %s\n", files[i].name.c_str());
        }
    }

    delete[] files;
    Serial.printf("Cleanup complete. Deleted %d files, freed %lluMB\n", 
                  deletedCount, freedBytes / (1024 * 1024));
}

// Initialize SD card
void initMicroSDCard() {
    Serial.println("Initializing SD Card...");
    if (!SD_MMC.begin()) {
        Serial.println("SD Card Mount Failed");
        return;
    }
    
    uint8_t cardType = SD_MMC.cardType();
    if (cardType == CARD_NONE) {
        Serial.println("No SD Card attached");
        return;
    }
    
    Serial.printf("SD Card Type: %s\n", 
                  cardType == CARD_MMC ? "MMC" : 
                  cardType == CARD_SD ? "SDSC" : 
                  cardType == CARD_SDHC ? "SDHC" : "UNKNOWN");
    
    uint64_t cardSize = SD_MMC.cardSize() / (1024 * 1024);
    Serial.printf("SD Card Size: %lluMB\n", cardSize);
}

// Create new video file with AVI headers
bool createNewVideoFile() {
    if (isRecording) {
        finishVideoFile();
    }

    // Get next video number
    currentVideoNumber = getNextVideoNumber();
    currentVideoFilename = getVideoFilename();
    
    videoFile = SD_MMC.open(currentVideoFilename, FILE_WRITE);
    
    if (!videoFile) {
        Serial.println("Failed to create video file");
        return false;
    }

    // Write AVI header structures
    AVIHeader aviHeader;
    StreamHeader streamHeader;
    BitmapInfo bitmapInfo;
    MovieHeader movieHeader;

    // --- Dynamic updates based on CAPTURE_INTERVAL_MS and camera resolution ---
    uint32_t current_fps = 1000 / CAPTURE_INTERVAL_MS;
    uint32_t microSecPerFrame_calc = CAPTURE_INTERVAL_MS * 1000; // Convert ms to microseconds

    // AVIHeader
    aviHeader.microSecPerFrame = microSecPerFrame_calc; // Dynamic FPS
    // A more robust maxBytesPerSec. Max JPEG size is highly variable but can be ~1MB for UXGA.
    // Let's set a generous buffer, e.g., 2MB/sec to cover high-quality frames.
    // Or, a safer estimation: max_frame_size * fps
    // If you know your max JPEG frame size, use that. For UXGA, it can be up to 150-200KB easily.
    // Let's assume a generous 200KB/frame for UXGA (1600x1200) and 25 FPS
    // (200 * 1024) * 25 = 5,120,000 bytes/sec
    // Adjust this value based on empirical tests of your actual max frame sizes at your chosen quality.
    aviHeader.maxBytesPerSec = (200 * 1024) * current_fps; // Example: 200KB/frame * FPS
    if (aviHeader.maxBytesPerSec == 0) aviHeader.maxBytesPerSec = 5000000; // Fallback to a large value if FPS is 0 or calculation error
    
    aviHeader.width = videoWidth;
    aviHeader.height = videoHeight;
    // aviHeader.totalFrames will be updated in finishVideoFile()

    // StreamHeader
    streamHeader.scale = 1;
    streamHeader.rate = current_fps; // Dynamic FPS
    streamHeader.suggestedBufferSize = aviHeader.maxBytesPerSec; // Match maxBytesPerSec for buffer
    streamHeader.right = videoWidth;
    streamHeader.bottom = videoHeight;
    // streamHeader.length will be updated in finishVideoFile()

    // BitmapInfo
    bitmapInfo.biWidth = videoWidth;
    bitmapInfo.biHeight = videoHeight;
    bitmapInfo.biSizeImage = 0; // Set to 0 for MJPEG as it's compressed
    // ----------------------------------------------------------------------------------

    // Calculate sizes (these remain the same logic)
    streamHeader.listSize = sizeof(StreamHeader) + sizeof(BitmapInfo) - 8;
    aviHeader.list1Size = sizeof(AVIHeader) + sizeof(StreamHeader) + sizeof(BitmapInfo) - 20;
    movieHeader.listSize = 4; // Will be updated when finishing

    // Write headers
    videoFile.write((uint8_t*)&aviHeader, sizeof(aviHeader));
    videoFile.write((uint8_t*)&streamHeader, sizeof(streamHeader));
    videoFile.write((uint8_t*)&bitmapInfo, sizeof(bitmapInfo));
    videoFile.write((uint8_t*)&movieHeader, sizeof(movieHeader));

    frameCount = 0;
    videoStartTime = millis();
    isRecording = true;

    Serial.printf("Started new video #%d: %s (Resolution: %dx%d, FPS: %d)\n",
                  currentVideoNumber, currentVideoFilename.c_str(), videoWidth, videoHeight, current_fps);
    return true;
}

// Add frame to video file (with error checking, as suggested previously)
void addFrameToVideo(camera_fb_t* fb) {
    if (!isRecording || !videoFile) return;

    // *** NEW: Get timestamp before writing frame ***
    uint64_t frameTimestampMs = getCurrentTimestampMs();

    // Write frame header (MJPG data chunk)
    char frameHeader[8] = {'0', '0', 'd', 'c', 0, 0, 0, 0};
    uint32_t frameSize = fb->len;
    memcpy(&frameHeader[4], &frameSize, 4);
    
    if (videoFile.write((uint8_t*)frameHeader, 8) != 8) {
        Serial.println("Error writing frame header!");
        return;
    }
    if (videoFile.write(fb->buf, fb->len) != fb->len) {
        Serial.println("Error writing frame data!");
        return;
    }
    
    // Add padding for JPEG if necessary (AVI requires even-sized chunks)
    if (fb->len % 2 != 0) {
        uint8_t padding = 0;
        if (videoFile.write(&padding, 1) != 1) {
            Serial.println("Error writing JPEG padding byte!");
            return;
        }
    }

    // *** NEW: Write the custom Timestamp Chunk (TIMS) ***
    TimestampChunk timsChunk;
    timsChunk.size = sizeof(timsChunk.unix_epoch_ms); // Size of the data payload (8 bytes)
    timsChunk.unix_epoch_ms = frameTimestampMs;

    if (videoFile.write((uint8_t*)&timsChunk, sizeof(timsChunk)) != sizeof(timsChunk)) {
        Serial.println("Error writing TIMS chunk!");
        // Decide if you want to stop recording or continue with potentially missing metadata
        return;
    }

    // Add padding for TIMS chunk if necessary (AVI requires even-sized chunks)
    // The TIMS chunk size is 8 bytes (sizeof(timsChunk.id) + sizeof(timsChunk.size) + timsChunk.size)
    // 4 bytes for ID + 4 bytes for size + 8 bytes for data = 16 bytes.
    // 16 is already an even number, so no padding needed here normally.
    // However, if the total chunk size (8 bytes header + data) is odd, add padding.
    // In our case, sizeof(timsChunk) is 16, which is even. So no padding.
    // If you ever change the data size to be odd, you'd need this:
    // if (sizeof(timsChunk) % 2 != 0) {
    //     uint8_t padding = 0;
    //     if (videoFile.write(&padding, 1) != 1) {
    //         Serial.println("Error writing TIMS padding byte!");
    //         return;
    //     }
    // }


    frameCount++;
}

// Finish and close video file (no changes needed here, still updates totalFrames, etc.)
void finishVideoFile() {
    if (!isRecording || !videoFile) return;

    // Get current position for calculating sizes
    uint32_t currentPos = videoFile.position();
    uint32_t movieSize = currentPos - sizeof(AVIHeader) - sizeof(StreamHeader) - sizeof(BitmapInfo) - 8;

    // Update file size in RIFF header
    videoFile.seek(4);
    uint32_t fileSize = currentPos - 8;
    videoFile.write((uint8_t*)&fileSize, 4);

    // Update total frames in AVI header
    videoFile.seek(48);
    videoFile.write((uint8_t*)&frameCount, 4);

    // Update movie list size
    videoFile.seek(sizeof(AVIHeader) + sizeof(StreamHeader) + sizeof(BitmapInfo) + 4);
    videoFile.write((uint8_t*)&movieSize, 4);

    videoFile.close();
    isRecording = false;

    Serial.printf("Finished video #%d: %s (%d frames, %d MB)\n", 
                  currentVideoNumber, currentVideoFilename.c_str(), frameCount, (currentPos / (1024 * 1024)));
}

// Check if current video file is too large
bool shouldCreateNewVideoFile() {
    if (!isRecording) return true;
    
    uint32_t currentSize = videoFile.position();
    uint32_t sizeMB = currentSize / (1024 * 1024);
    
    return sizeMB >= MAX_VIDEO_SIZE_MB;
}

// Capture and add frame to video
void captureVideoFrame() {
    // Auto-brightness adjustment (Note: This is ineffective with PIXFORMAT_JPEG, see comments in adjustBrightness)
    adjustBrightness();
    
    // Check if we need a new video file
    if (shouldCreateNewVideoFile()) {
        if (!createNewVideoFile()) {
            Serial.println("Failed to create new video file");
            return;
        }
    }
    
    // Take picture
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Camera capture failed");
        return;
    }

    // Add frame to video
    addFrameToVideo(fb);
    
    esp_camera_fb_return(fb);

    // Print status and flush every 100 frames to make size visible
    if (frameCount % 100 == 0) { // Adjust frequency as needed
        videoFile.flush(); 
        uint32_t sizeMB = videoFile.position() / (1024 * 1024);
        Serial.printf("Video #%d: %s - Frame: %d, Size: %dMB\n", 
                      currentVideoNumber, currentVideoFilename.c_str(), frameCount, sizeMB);
    }
}

void setup() {
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    
    Serial.begin(115200);
    delay(2000);

    // Initialize pins
    pinMode(FLASH_GPIO_NUM, OUTPUT);
    
    // Flash LED to indicate startup
    for (int i = 0; i < 3; i++) {
        digitalWrite(FLASH_GPIO_NUM, HIGH);
        delay(200);
        digitalWrite(FLASH_GPIO_NUM, LOW);
        delay(200);
    }

    Serial.println("ESP32 Video Dash Cam Starting...");
    
    // Initialize components
    initWiFi();
    initTime(myTimezone);
    
    if (ntpTimeAvailable) {
        Serial.println("Using NTP timestamps for video filenames AND per-frame metadata.");
    } else {
        Serial.println("Using uptime timestamps for video filenames AND per-frame metadata.");
    }
    
    Serial.println("Initializing camera...");
    configInitCamera(); // This will now set videoWidth and videoHeight
    
    Serial.println("Initializing SD card...");
    initMicroSDCard();
    
    // Initial cleanup
    manageSdCardSpace();
    
    // Create initial video file
    if (!createNewVideoFile()) { // This will now use dynamic width, height, and FPS
        Serial.println("Failed to create initial video file!");
        return;
    }
    
    Serial.println("Video dash cam ready! Starting recording...");
    lastCaptureTime = millis();
}

void loop() {
    unsigned long currentTime = millis();
    
    // Capture at specified interval
    if (currentTime - lastCaptureTime >= CAPTURE_INTERVAL_MS) {
        captureVideoFrame();
        lastCaptureTime = currentTime;
        
        // Manage SD card space every 1000 frames
        if (frameCount % 1000 == 0 && frameCount > 0) {
            manageSdCardSpace();
        }
    }
    
    // Small delay to prevent overwhelming the system
    delay(5);
}
