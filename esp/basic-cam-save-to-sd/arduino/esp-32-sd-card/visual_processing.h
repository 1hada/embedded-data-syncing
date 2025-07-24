#ifndef VISUAL_PROCESSING_H
#define VISUAL_PROCESSING_H

#include "esp_camera.h"
#include "esp_log.h"
#include "img_converters.h"
#include "Arduino.h"

// Define thumbnail resolution for sensor-based brightness fallback (optional)
//#define BRIGHTNESS_THUMBNAIL_FRAMESIZE FRAMESIZE_QQVGA

// Logging tag
static const char *TAG = "VisualProcessing";

// Forward declarations
int calculateBrightnessYUV422(camera_fb_t *fb);
int calculateBrightnessJPEG(camera_fb_t *fb_current_stream);
void manageAutoExposure(int brightness);
uint8_t rgb565ToLuma(uint16_t pixel);

// --- YUV422 Brightness Calculation ---
int calculateBrightnessYUV422(camera_fb_t *fb) {
    if (!fb || fb->format != PIXFORMAT_YUV422) {
        ESP_LOGE(TAG, "Invalid frame buffer for YUV422 brightness.");
        return -1;
    }

    unsigned long totalY = 0;
    int count = 0;
    int step = max(1, (int)(fb->width / 16));  // Sample every ~16 pixels

    for (int y = 0; y < fb->height; y += step) {
        for (int x = 0; x < fb->width; x += step) {
            int index = (y * fb->width + x) * 2; // Y component at even index
            totalY += fb->buf[index];
            count++;
        }
    }

    return (count > 0) ? totalY / count : -1;
}

// --- JPEG Brightness Calculation (fast + safe) ---
int calculateBrightnessJPEG(camera_fb_t *fb_current_stream) {
    if (!fb_current_stream || fb_current_stream->format != PIXFORMAT_JPEG) {
        ESP_LOGE(TAG, "Invalid JPEG frame buffer for brightness calculation.");
        return -1;
    }

    jpg_scale_t scale = JPG_SCALE_4X; // or JPG_SCALE_QUARTER, depending on your enum
    uint32_t width = 0, height = 0;

    // Allocate a buffer to hold the decoded RGB565 image
    // Size = width * height * 2 bytes per pixel max at full scale (worst case)
    // But since we decode at scaled size, use max image size for scale 1/4:
    // Image size at 1/4 scale = (orig_width / 4) * (orig_height / 4)
    // Use camera frame size for orig_width and orig_height or just allocate max size

    // For demonstration: allocate max possible for your frame
    size_t max_buffer_size = 320 * 240 * 2; // adjust if you know frame size (QVGAx2 bytes)
    uint8_t *rgb_buf = (uint8_t *)malloc(max_buffer_size);
    if (!rgb_buf) {
        ESP_LOGE(TAG, "Failed to allocate RGB buffer");
        return -1;
    }

    bool success = jpg2rgb565(fb_current_stream->buf, fb_current_stream->len, rgb_buf, scale);
    if (!success) {
        ESP_LOGE(TAG, "jpg2rgb565() decode failed.");
        free(rgb_buf);
        return -1;
    }

    // Calculate width and height after scaling
    // Usually width and height are scaled by jpg2rgb565 by factor of scale
    // But if you have original width/height, you can compute scaled dims manually
    width = fb_current_stream->width / 4;  // for JPG_SCALE_4X
    height = fb_current_stream->height / 4;

    int step = (width / 6) > 1 ? (width / 6) : 1;

    unsigned long totalY = 0;
    int count = 0;
    for (int y = 0; y < (int)height; y += step) {
        for (int x = 0; x < (int)width; x += step) {
            int index = (y * width + x) * 2;
            uint16_t pixel = rgb_buf[index] | (rgb_buf[index + 1] << 8);
            totalY += rgb565ToLuma(pixel);
            count++;
        }
    }

    free(rgb_buf);
    return (count > 0) ? (int)(totalY / count) : -1;
}



// Map brightness [0..255] to AE level changes [-2..2] with smaller steps
int mapBrightnessToAeLevel(int calculated_brightness) {
    if (calculated_brightness < 80) {
        // For low brightness, gradually increase AE level from 0 to +2
        // Scale linearly from 0-79 => 0 to +2
        return (calculated_brightness * 2) / 80; // approx 0 to +1.975
    } else if (calculated_brightness > 180) {
        // For high brightness, gradually decrease AE level from 0 to -2
        // Scale linearly from 181-255 => 0 to -2
        return -((calculated_brightness - 180) * 2) / 75; // approx 0 to -2
    } else {
        // Brightness OK, no adjustment
        return 0;
    }
}

// --- Convert RGB565 pixel to brightness (luma) ---
uint8_t rgb565ToLuma(uint16_t pixel) {
    uint8_t r = ((pixel >> 11) & 0x1F) << 3;
    uint8_t g = ((pixel >> 5) & 0x3F) << 2;
    uint8_t b = (pixel & 0x1F) << 3;
    return (uint8_t)((r * 299 + g * 587 + b * 114) / 1000);  // Y = 0.299R + 0.587G + 0.114B
}

// --- Basic auto-exposure handler ---
void manageAutoExposure(int calculated_brightness) {
    sensor_t *s = esp_camera_sensor_get();
    if (!s) {
        ESP_LOGE(TAG, "Sensor not available for AE.");
        return;
    }

    s->set_ae_level(s, mapBrightnessToAeLevel(calculated_brightness));
}

#endif // VISUAL_PROCESSING_H
