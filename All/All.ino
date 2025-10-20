#include <Wire.h>
#include "Adafruit_MLX90614.h"
#include "MAX30105.h"
#include "spo2_algorithm.h"
#include "HX711.h"
#include "DHT.h"

// ================== PIN CONNECTIONS ==================
// MLX90614 -> ESP32
//   VCC  -> 3.3V
//   GND  -> GND
//   SDA  -> GPIO21
//   SCL  -> GPIO22
//
// MAX30102 -> ESP32
//   VIN  -> 3.3V or 5V
//   GND  -> GND
//   SDA  -> GPIO21
//   SCL  -> GPIO22
//
// HX711 -> ESP32
//   DT  -> GPIO25
//   SCK -> GPIO26
//
// DHT22 -> ESP32
//   VCC  -> 3.3V
//   GND  -> GND
//   DATA -> GPIO4
//
// LED -> GPIO5  | Buzzer -> GPIO18
// =====================================================

#define LED_PIN 5
#define BUZZER_PIN 18
#define DOUT_PIN 25
#define SCK_PIN 26
#define DHT_PIN 4
#define DHT_TYPE DHT22

// Thresholds
#define TEMP_LOW 35.5
#define TEMP_HIGH 38.0
#define TEMP_CRITICAL 39.5
#define SPO2_LOW 90
#define SPO2_CRITICAL 85
#define HR_LOW 50
#define HR_HIGH 120
#define HR_CRITICAL 150

Adafruit_MLX90614 mlx = Adafruit_MLX90614();
MAX30105 particleSensor;
HX711 scale;
DHT dht(DHT_PIN, DHT_TYPE);

float calibration_factor = -28; // Calibrated for your load cell
float weight = 0;
bool hx711Working = false;

// SpO2 buffers
#define BUFFER_LENGTH 100
uint32_t irBuffer[BUFFER_LENGTH];
uint32_t redBuffer[BUFFER_LENGTH];
int32_t spo2;
int8_t validSPO2;
int32_t heartRate;
int8_t validHeartRate;

unsigned long lastTempRead = 0;
unsigned long lastDHTRead = 0;
bool fingerDetected = false;
int measurementCount = 0;
bool mlxWorking = false;
bool max30102Working = false;
bool dhtWorking = false;
float envTemperature = 0;
float humidity = 0;

void setup() {
  Serial.begin(115200);
  delay(2000);
 
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);  // LED OFF at startup
  digitalWrite(BUZZER_PIN, LOW);
 
  Serial.println("\n");
  Serial.println("╔════════════════════════════════════════════════╗");
  Serial.println("║   HOSPITAL VITAL SIGNS MONITOR v3.4           ║");
  Serial.println("║   With Temperature, HR, SpO2 & Weight         ║");
  Serial.println("╚════════════════════════════════════════════════╝\n");
 
  // ---------- Initialize HX711 FIRST ----------
  Serial.println("⚖️  Step 1: Initializing HX711 Load Cell...");
  scale.begin(DOUT_PIN, SCK_PIN);
 
  Serial.println("   Remove any weight from the scale...");
  delay(2000);
 
  if (scale.is_ready()) {
    // Tare the scale (set current reading as zero) - EXACTLY like your working code
    scale.set_scale();
    scale.tare();
   
    hx711Working = true;
    Serial.println("   ✅ Tare complete. Scale is ready.");
    Serial.println("   Commands: 't' = Tare, 'c' = Calibrate");
    Serial.println("   Place object to weigh\n");
  } else {
    Serial.println("   ❌ HX711 not detected. Check wiring (DT=25, SCK=26)\n");
  }
 
  // Initialize I2C for other sensors
  Wire.begin(21, 22);
  Wire.setClock(100000);
  delay(500);
 
  // ---------- Initialize MLX90614 ----------
  Serial.println("🌡️  Step 2: Initializing MLX90614...");
  mlxWorking = mlx.begin();
  if (mlxWorking) {
    Serial.println("   ✅ MLX90614 detected\n");
  } else {
    Serial.println("   ❌ MLX90614 not found\n");
  }
 
  // ---------- Initialize MAX30102 ----------
  Serial.println("❤️  Step 3: Initializing MAX30102...");
  if (particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
    particleSensor.setup();
    particleSensor.setPulseAmplitudeRed(0x0A);
    particleSensor.setPulseAmplitudeGreen(0);
    max30102Working = true;
    Serial.println("   ✅ MAX30102 detected\n");
  } else {
    Serial.println("   ❌ MAX30102 not found\n");
  }

  // ---------- Initialize DHT22 ----------
  Serial.println("🌡️  Step 4: Initializing DHT22...");
  dht.begin();
  dhtWorking = true;
  Serial.println("   ✅ DHT22 initialized\n");
 
  Serial.println("──────────────────────────────────────────────────");
  Serial.println("System Ready!");
  Serial.println("──────────────────────────────────────────────────\n");
}

void loop() {
  // --- Read Temperature (MLX90614) ---
  float temperature = 0;
  if (mlxWorking && (millis() - lastTempRead >= 1000)) {
    temperature = mlx.readObjectTempC();
    lastTempRead = millis();
  }

  // --- Read Environmental Data (DHT22) ---
  if (dhtWorking && (millis() - lastDHTRead >= 2000)) {
    envTemperature = dht.readTemperature();
    humidity = dht.readHumidity();
    lastDHTRead = millis();
  }
 
  // --- Read Weight (HX711) - EXACTLY like your working code ---
  float weight_kg = 0;
  if (hx711Working && scale.is_ready()) {
    scale.set_scale(calibration_factor);
   
    // Get weight reading (average of 10 readings)
    weight = scale.get_units(10);
   
    // Add 4.5 kg offset
    weight = weight + 4500; // Adding 4500 grams (4.5 kg)
   
    // Convert to kg
    weight_kg = weight / 1000;
  }
 
  // --- Read MAX30102 (Heart Rate & SpO2) ---
  if (max30102Working) {
    uint32_t irValue = particleSensor.getIR();
   
    if (irValue > 50000) {  // Finger detected
      if (!fingerDetected) {
        fingerDetected = true;
        digitalWrite(LED_PIN, HIGH);  // Turn LED ON when finger detected
        Serial.println("👆 Finger detected! Collecting data...");
      }
     
      // Collect data for SpO2 calculation
      for (byte i = 0; i < BUFFER_LENGTH; i++) {
        while (particleSensor.available() == false)
          particleSensor.check();
       
        redBuffer[i] = particleSensor.getRed();
        irBuffer[i] = particleSensor.getIR();
        particleSensor.nextSample();
      }
     
      // Calculate SpO2 and Heart Rate
      maxim_heart_rate_and_oxygen_saturation(
        irBuffer, BUFFER_LENGTH,
        redBuffer, &spo2, &validSPO2,
        &heartRate, &validHeartRate
      );
     
      measurementCount++;
    } else {
      if (fingerDetected) {
        fingerDetected = false;
        digitalWrite(LED_PIN, LOW);  // Turn LED OFF when finger removed
        Serial.println("❌ Finger removed\n");
      }
    }
  }
 
  // --- Determine Overall Status ---
  String status = "normal";
  if (mlxWorking && (temperature > TEMP_CRITICAL || temperature < TEMP_LOW)) {
    status = "critical";
  } else if (max30102Working && fingerDetected) {
    if ((validHeartRate && (heartRate > HR_CRITICAL || heartRate < HR_LOW)) || 
        (validSPO2 && spo2 < SPO2_CRITICAL)) {
      status = "critical";
    } else if ((validHeartRate && (heartRate > HR_HIGH || heartRate < HR_LOW)) || 
               (validSPO2 && spo2 < SPO2_LOW)) {
      status = "warning";
    }
  }

  // --- Send JSON Data to Flask ---
  Serial.print("JSON:");
  Serial.print("{");
  Serial.print("\"temperature\":");
  Serial.print(temperature, 1);
  Serial.print(",\"heartRate\":");
  Serial.print(validHeartRate && fingerDetected ? heartRate : 0);
  Serial.print(",\"spo2\":");
  Serial.print(validSPO2 && fingerDetected ? spo2 : 0);
  Serial.print(",\"weight\":");
  Serial.print(weight_kg, 3);
  Serial.print(",\"envTemperature\":");
  Serial.print(envTemperature, 1);
  Serial.print(",\"humidity\":");
  Serial.print(humidity, 1);
  Serial.print(",\"status\":\"");
  Serial.print(status);
  Serial.print("\",\"measurements\":");
  Serial.print(measurementCount);
  Serial.println("}");

  // --- Display All Vitals ---
  Serial.println("╔═══════════════════════ VITAL SIGNS ════════════════════════╗");

  // Temperature
  if (mlxWorking) {
    Serial.print("🌡️  Temperature: ");
    Serial.print(temperature, 1);
    Serial.print(" °C");
    if (temperature < TEMP_LOW) {
      Serial.println(" ⚠️ LOW");
      alertBuzzer(1);
    } else if (temperature > TEMP_CRITICAL) {
      Serial.println(" 🚨 CRITICAL");
      alertBuzzer(3);
    } else if (temperature > TEMP_HIGH) {
      Serial.println(" ⚠️ HIGH");
      alertBuzzer(2);
    } else {
      Serial.println(" ✅");
    }
  }

  // Weight
  if (hx711Working && scale.is_ready()) {
    Serial.print("⚖️  Weight: ");
    Serial.print(weight_kg, 3);
    Serial.println(" kg");
  } else if (hx711Working) {
    Serial.println("⚖️  HX711 not found.");
  }

  // Environmental Data
  if (dhtWorking) {
    Serial.print("🌡️  Room Temperature: ");
    Serial.print(envTemperature, 1);
    Serial.println(" °C");
    
    Serial.print("💧  Humidity: ");
    Serial.print(humidity, 1);
    Serial.println(" %");
  }

  // Heart Rate & SpO2
  if (max30102Working && fingerDetected) {
    if (validHeartRate && heartRate > 30 && heartRate < 200) {
      Serial.print("❤️  Heart Rate: ");
      Serial.print(heartRate);
      Serial.print(" bpm");
     
      if (heartRate < HR_LOW) {
        Serial.println(" ⚠️ LOW");
        alertBuzzer(1);
      } else if (heartRate > HR_CRITICAL) {
        Serial.println(" 🚨 CRITICAL");
        alertBuzzer(3);
      } else if (heartRate > HR_HIGH) {
        Serial.println(" ⚠️ HIGH");
        alertBuzzer(2);
      } else {
        Serial.println(" ✅");
      }
    }
   
    if (validSPO2 && spo2 > 70 && spo2 <= 100) {
      Serial.print("🫁 SpO2: ");
      Serial.print(spo2);
      Serial.print(" %");
     
      if (spo2 < SPO2_CRITICAL) {
        Serial.println(" 🚨 CRITICAL");
        alertBuzzer(3);
      } else if (spo2 < SPO2_LOW) {
        Serial.println(" ⚠️ LOW");
        alertBuzzer(2);
      } else {
        Serial.println(" ✅");
      }
    }
  }

  Serial.print("📊 Measurements: ");
  Serial.println(measurementCount);
  Serial.println("╚════════════════════════════════════════════════════════════╝\n");
 
  // --- Check for Serial Commands - EXACTLY like your working code ---
  if (Serial.available()) {
    char cmd = Serial.read();
   
    if (cmd == 't' || cmd == 'T') {
      // Tare command
      Serial.println("⚖️  Taring...");
      scale.tare();
      Serial.println("✅ Tare complete\n");
    }
    else if (cmd == 'c' || cmd == 'C') {
      // Enter calibration mode
      Serial.println("⚖️  Enter calibration mode");
      Serial.println("Place known weight and enter weight in grams:");
     
      while (!Serial.available()) {
        delay(10);
      }
     
      float known_weight = Serial.parseFloat();
      Serial.print("Calibrating with ");
      Serial.print(known_weight);
      Serial.println(" g");
     
      long raw_value = scale.get_units(10);
      calibration_factor = raw_value / known_weight;
     
      Serial.print("✅ New calibration factor: ");
      Serial.println(calibration_factor);
      Serial.println("Calibration complete\n");
    }
  }
 
  delay(500);  // Match your working code's delay
}

void alertBuzzer(int beeps) {
  for (int i = 0; i < beeps; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    digitalWrite(LED_PIN, LOW);
    delay(200);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(LED_PIN, HIGH);
    delay(200);
  }
}