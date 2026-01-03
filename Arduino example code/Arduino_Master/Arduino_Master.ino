/*
 * Master Arduino Template
 * 
 * Handles:
 * 1. I2C communication with slaves
 * 2. Local sensor readings
 * 3. PC communication
 */

#include <Wire.h>
#include <DHT.h>

// === SENSOR CONFIGURATION ===
#define DHTPIN 2
#define DHTTYPE DHT11   // Change to DHT22 if needed

// === SLAVE CONFIGURATION ===
byte slaveAddresses[] = {8, 9, 10};
int numSlaves = sizeof(slaveAddresses) / sizeof(slaveAddresses[0]);

// === SENSOR NAMES ===
String masterSensorName1 = "Humidity";
String masterSensorName2 = "Temperature";

// === TIMING ===
const unsigned long sensorUpdateInterval = 400;  //2000 for dht

// === GLOBALS ===
DHT dht(DHTPIN, DHTTYPE);

String masterData;
String slaveData[3];
unsigned long lastSensorUpdate = 0;

void setup() {
  Wire.begin();
  Serial.begin(9600);

  dht.begin();   // REQUIRED for Adafruit DHT library
}

void loop() {
  // Update sensors
  if (millis() - lastSensorUpdate >= sensorUpdateInterval) {
    updateSensorData();
    lastSensorUpdate = millis();

    // Request data from slaves
    for (int i = 0; i < numSlaves; i++) {
      Wire.requestFrom((uint8_t)slaveAddresses[i], (uint8_t)32);
      slaveData[i] = "";

      while (Wire.available()) {
        char c = Wire.read();
        if (c == 0) break;
        slaveData[i] += c;
      }
    }
  }

  // Handle PC commands
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "TEST") {
      Serial.println("ACK");
    }

    String dataBuffer = masterData;
    for (int i = 0; i < numSlaves; i++) {
      dataBuffer += ";" + slaveData[i];
    }
    Serial.println(dataBuffer);
  }
}

/*
 * Read local sensors and update masterData
 * Format:
 * "Humidity:xx.x;Temperature:yy.y"
 */
void updateSensorData() {
  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature(); // Celsius

  if (isnan(humidity) || isnan(temperature)) {
    masterData = "Humidity:NaN;Temperature:NaN";
    return;
  }

  masterData = masterSensorName1 + ":" + String(humidity, 1) + ";" +
               masterSensorName2 + ":" + String(temperature, 1);
}