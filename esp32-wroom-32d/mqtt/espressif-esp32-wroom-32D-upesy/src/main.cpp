#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <PubSubClient.h>
#include <ArduinoJson.h>
//ADVANCED// #include <PubSubClient.h>
#include "secrets.h"
#include "hardware_constants.h"
#include <math.h> // Include math library for 'e' ('M_E')

//ADVANCED// #include <CameraLibrary.h> // Assuming this is the library for your camera
//ADVANCED// #include <Ultrasonic.h> // Assuming this is the library for your ultrasonic sensor

// Constants for ultrasonic sensor
//ADVANCED// const int TRIGGER_PIN = 4;
//ADVANCED// const int ECHO_PIN = 5;

WiFiClientSecure net = WiFiClientSecure();
PubSubClient mqttClient(net);

// FreeRTOS task prototypes
//ADVANCED// void cameraTask1(void *parameter);
//ADVANCED// void cameraTask2(void *parameter);
//ADVANCED// void ultrasonicTask(void *parameter);
void publishTask(void *parameter);
void blinkTask(void *parameter);
void connectAWS();
void messageHandler(char* topic, byte* payload, unsigned int length);

// helpers
void reconnect();

void setup() {
  Serial.begin(921600);
  connectAWS();

  /*
  // start AWS
  // Connect to WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("Connected to WiFi");

  // Connect to AWS IoT
  mqttClient.setServer(AWS_IOT_ENDPOINT, 8883);
  // END AWS
  */

  // Create FreeRTOS tasks
  //ADVANCED// xTaskCreatePinnedToCore(cameraTask1, "Camera Task 1", 10000, NULL, 1, NULL, 0);
  //ADVANCED// xTaskCreatePinnedToCore(cameraTask2, "Camera Task 2", 10000, NULL, 1, NULL, 0);
  //ADVANCED// xTaskCreatePinnedToCore(ultrasonicTask, "Ultrasonic Task", 10000, NULL, 1, NULL, 0);
  // AWS // xTaskCreatePinnedToCore(publishTask, "Publish Task", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(blinkTask, "Blink Task", 10000, NULL, 1, NULL, 0);
}

void loop() {
  // Nothing to do here since tasks are running independently
}


void connectAWS()
{
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.println("Connecting to Wi-Fi");

  while (WiFi.status() != WL_CONNECTED){
    delay(500);
    Serial.print(".");
  }

  // Configure WiFiClientSecure to use the AWS IoT device credentials
  net.setCACert(AWS_CERT_CA);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);

  // Connect to the MQTT broker on the AWS endpoint we defined earlier
  mqttClient.setServer(AWS_IOT_ENDPOINT, 8883);

  // Create a message handler
  mqttClient.setCallback(messageHandler);

  Serial.print("Connecting to AWS IOT");

  while (!mqttClient.connect(THINGNAME)) {
    Serial.print(".");
    delay(100);
  }

  if(!mqttClient.connected()){
    Serial.println("AWS IoT Timeout!");
    return;
  }

  // Subscribe to a topic
  mqttClient.subscribe(AWS_IOT_SUBSCRIBE_TOPIC);

  Serial.println("AWS IoT Connected!");
}

void messageHandler(char* topic, byte* payload, unsigned int length){
  Serial.println("incoming: " + String(topic) );//+ " - " + String(payload));

//  StaticJsonDocument<200> doc;
//  deserializeJson(doc, payload);
//  const char* message = doc["message"];
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
  /*
  // START AWS
  // END AWS
  */
  while (true) {
    if (!mqttClient.connected()) {
      reconnect();
    }
    mqttClient.loop();

    // Publish data to AWS IoT
    // Example:
    JsonDocument doc;
    doc["time"] = millis();
    doc["sensor_a0"] = analogRead(0);
    char jsonBuffer[512];
    serializeJson(doc, jsonBuffer); // print to client
    mqttClient.publish(AWS_IOT_PUBLISH_TOPIC, jsonBuffer);
    vTaskDelay(5000 / portTICK_PERIOD_MS); // Publish every 5 seconds
  }
}

void blinkTask(void *parameter) {
  unsigned long previousMillis = 0;
  unsigned long interval = 1000; // Initial blink interval (1 second)
  
  while (true) {
    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis >= interval) {
      // Blink LED
      digitalWrite(LED_PIN, !digitalRead(LED_PIN));
      
      // Update interval based on exponential growth (e^x)
      interval = interval * M_E;
      if (interval > 8000) {
        interval = 1000; // Reset interval if it exceeds 8 seconds
      }
      
      previousMillis = currentMillis;
      Serial.print("The current interval is "); // FOR TESTING
      Serial.print(interval);// FOR TESTING
      Serial.println(" milliseconds.");// FOR TESTING
    }
    vTaskDelay(100 / portTICK_PERIOD_MS); // Task delay
  }
}

void reconnect() {
  while (!mqttClient.connected()) {
    Serial.println("Attempting MQTT connection...");
    if (mqttClient.connect(THINGNAME)) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}
