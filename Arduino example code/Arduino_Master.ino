/*
 * Master Arduino Template
 * 
 * This template handles:
 * 1. Communication with multiple slave Arduinos via I2C
 * 2. Reading local sensors
 * 3. Responding to PC requests
 * 
 * === USER CONFIGURATION SECTION START ===
 */

#include <Wire.h>
// Add your sensor libraries here
#include <dht.h>  // Example sensor library, modify as needed

// Define your sensor pins here
#define DHT11PIN 2  // Example sensor pin, modify as needed

// Configure your slave devices
byte slaveAddresses[] = {8, 9, 10};  // Modify addresses as needed
int numSlaves = sizeof(slaveAddresses) / sizeof(slaveAddresses[0]);

// Name your sensor measurements
String masterSensorName1 = "Humidity";    // Modify sensor names
String masterSensorName2 = "Temperature"; // according to your sensors

// Sensor update interval
const unsigned long sensorUpdateInterval = 2000; // Adjust if needed (in milliseconds). In this case, the DHT11 is slow.

// === USER CONFIGURATION SECTION END ===

// Global variables 
dht DHT;  // Example sensor object
String masterData;  // Stores local sensor data
String slaveData[3];  // Stores data from slaves
unsigned long lastSensorUpdate = 0;

void setup() {
  Wire.begin();        // Initialize I2C as master
  Serial.begin(9600);  // Initialize serial communication
  
  // Add your sensor initialization here if needed
}

void loop() {
  // Update sensors at defined interval
  if (millis() - lastSensorUpdate >= sensorUpdateInterval) {
    updateSensorData();
    lastSensorUpdate = millis();
    
    // Request data from all slaves
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

  // Handle PC communication
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command == "TEST") {
      Serial.println("ACK");
    }
    
    // Send all data to PC
    String dataBuffer = masterData;
    for (int i = 0; i < numSlaves; i++) {
      dataBuffer += ";" + slaveData[i];
    }
    Serial.println(dataBuffer);
  }
}

/*
 * === USER MODIFICATION REQUIRED ===
 * Modify this function according to your sensors
 * Ensure to update the global masterData string with your sensor readings
 * Format: "SensorName1:Value1;SensorName2:Value2"
 */
void updateSensorData() {
  // Example sensor reading - Replace with your sensor code
  int chk = DHT.read11(DHT11PIN);
  float humidity = DHT.humidity;
  float temperature = DHT.temperature;
  
  if (!isnan(humidity) && !isnan(temperature)) {
    masterData = masterSensorName1 + ":" + String(humidity, 1) + ";" + 
                 masterSensorName2 + ":" + String(temperature, 1);
  }
}
