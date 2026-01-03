#include <Wire.h> 
#include <SPI.h>
#include <Adafruit_MAX31855.h>

#define MAXDO   12   // Data Out (MISO)
#define MAXCS   10   // Chip Select (SS)
#define MAXCLK  13   // Clock (SCK)

// ======== USER CONFIGURATION ========
const byte I2C_ADDRESS = 8;        // Unique address for this slave
const unsigned long BAUD_RATE = 9600; // For debugging only

double temp_out = 0;
// ====================================

// ======== USER CUSTOMIZATION ========

// Initialising the Sensor
Adafruit_MAX31855 thermocouple(MAXCLK, MAXCS, MAXDO);

void setupSensor() {
  // Initialize your sensors here
  // pinMode(A0, INPUT);
}

String readSensorData() {
  // Replace with actual sensor reading logic
  return "K-Type1:" + String(temp_out) + ";";
}
// ====================================

void setup() {
  Wire.begin(I2C_ADDRESS);      // Join I2C bus as slave
  Wire.onRequest(requestEvent); // Register callback
  Serial.begin(BAUD_RATE);      // For debugging
  setupSensor();
}

void loop() {
  double tempC = thermocouple.readCelsius();
  if (!isnan(tempC)) {  // Syntaxfehler korrigiert: "not" → "!"
    temp_out = tempC;
    delay(100);
  }
}

// I2C request handler
void requestEvent() {
  String response = readSensorData();
  Wire.write(response.c_str()); // Send response to master
}
