#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "secrets.h"
//ADVANCED// #include <CameraLibrary.h> // Assuming this is the library for your camera
//ADVANCED// #include <Ultrasonic.h> // Assuming this is the library for your ultrasonic sensor

// Constants for ultrasonic sensor
//ADVANCED// const int TRIGGER_PIN = 4;
//ADVANCED// const int ECHO_PIN = 5;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// FreeRTOS task prototypes
//ADVANCED// void cameraTask1(void *parameter);
//ADVANCED// void cameraTask2(void *parameter);
//ADVANCED// void ultrasonicTask(void *parameter);
void publishTask(void *parameter);

void setup() {
  Serial.begin(115200);
  
  // Connect to WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("Connected to WiFi");

  // Connect to AWS IoT
  mqttClient.setServer(AWS_IOT_ENDPOINT, 8883);

  // Create FreeRTOS tasks
  //ADVANCED// xTaskCreatePinnedToCore(cameraTask1, "Camera Task 1", 10000, NULL, 1, NULL, 0);
  //ADVANCED// xTaskCreatePinnedToCore(cameraTask2, "Camera Task 2", 10000, NULL, 1, NULL, 0);
  //ADVANCED// xTaskCreatePinnedToCore(ultrasonicTask, "Ultrasonic Task", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(publishTask, "Publish Task", 10000, NULL, 1, NULL, 0);
}

void loop() {
  // Nothing to do here since tasks are running independently
}

/*
// START ADVANCED
void cameraTask1(void *parameter) {
  // Code to capture data from camera 1
  while (true) {
    // Capture image or video from camera 1
    // Example:
    // camera1.capture();
    vTaskDelay(5000 / portTICK_PERIOD_MS); // Delay for 5 seconds
  }
}

void cameraTask2(void *parameter) {
  // Code to capture data from camera 2
  while (true) {
    // Capture image or video from camera 2
    // Example:
    // camera2.capture();
    vTaskDelay(5000 / portTICK_PERIOD_MS); // Delay for 5 seconds
  }
}

void ultrasonicTask(void *parameter) {
  Ultrasonic ultrasonic(TRIGGER_PIN, ECHO_PIN);
  while (true) {
    // Read distance from ultrasonic sensor
    float distance_cm = ultrasonic.distanceRead();
    Serial.print("Distance: ");
    Serial.print(distance_cm);
    Serial.println(" cm");
    vTaskDelay(1000 / portTICK_PERIOD_MS); // Delay for 1 second
  }
}
// END ADVANCED
*/

void publishTask(void *parameter) {
  while (true) {
    if (!mqttClient.connected()) {
      reconnect();
    }
    mqttClient.loop();

    // Publish data to AWS IoT
    // Example:
    // mqttClient.publish("topic", data);
    vTaskDelay(5000 / portTICK_PERIOD_MS); // Publish every 5 seconds
  }
}

void reconnect() {
  while (!mqttClient.connected()) {
    Serial.println("Attempting MQTT connection...");
    if (mqttClient.connect(CLIENT_ID)) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}
