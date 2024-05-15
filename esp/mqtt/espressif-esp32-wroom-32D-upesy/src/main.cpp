#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <WiFiClientSecure.h>

#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "secrets.h"
#include "hardware_constants.h"
#include "UUID.h"

WiFiClientSecure net = WiFiClientSecure();
PubSubClient mqttClient(net);
UUID uuid; // A unique identifier for the current session
unsigned int publishRateMinutes = 3;

// FreeRTOS task prototypes
void publishTask(void *parameter);

// Helpers
void connectAWS();
void messageHandler(char* topic, byte* payload, unsigned int length);
void reconnect();


void setup() {
  Serial.begin(921600);
  connectAWS();

  // Generate a unique identifier to make it easier to post-process the devices current uptime
  uint32_t seed1 = random(999999999L);
  uint32_t seed2 = random(999999999L);
  uuid.seed(seed1, seed2);
  uuid.generate();

  // Create FreeRTOS tasks
  xTaskCreatePinnedToCore(publishTask, "Publish Task", 10000, NULL, 1, NULL, 0);
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
  Serial.println("incoming: " + String(topic) );

//  StaticJsonDocument<200> doc;
//  deserializeJson(doc, payload);
//  const char* message = doc["message"];
}

void publishTask(void *parameter) {

  while (true) {
    if (!mqttClient.connected()) {
      reconnect();
    }
    mqttClient.loop();

    // Publish data to AWS IoT
    // Example:
    JsonDocument doc;
    doc["uptime_s"] = millis()/1000.0;
    doc["thing_name"] = THINGNAME;
    doc["session_id"] = uuid;
    
    char jsonBuffer[512];
    serializeJson(doc, jsonBuffer); // print to client
    mqttClient.publish(AWS_IOT_PUBLISH_TOPIC, jsonBuffer);
    vTaskDelay(publishRateMinutes * 60000 / portTICK_PERIOD_MS); // Publish every publishRateMinutes * 60 seconds
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
