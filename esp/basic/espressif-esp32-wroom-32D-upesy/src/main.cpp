#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <math.h> // Include math library for 'e' ('M_E')

// FreeRTOS task prototypes
void printTask(void *parameter);

void setup()
{
  Serial.begin(921600);

  // Create FreeRTOS tasks
  xTaskCreatePinnedToCore(printTask, "Print Task", 10000, NULL, 1, NULL, 0);
}

void loop()
{
  // Nothing to do here since tasks are running independently
}

void printTask(void *parameter)

{
  unsigned long previousMillis = 0;
  unsigned long interval = 1000; // Initial print interval (1 second)

  while (true)
  {
    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis >= interval)
    {
      // Print to monitor on an Interval
      Serial.print("The current interval is "); // FOR TESTING
      Serial.print(interval);                   // FOR TESTING
      Serial.println(" milliseconds.");         // FOR TESTING

      // Update interval based on exponential growth (e^x)
      interval = interval * M_E;
      if (interval > 8000)
      {
        interval = 1000; // Reset interval if it exceeds 8 seconds
      }

      previousMillis = currentMillis;
    }
    vTaskDelay(100 / portTICK_PERIOD_MS); // Task delay
  }
}
