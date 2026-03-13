#include <Arduino.h>
#include <HX711.h>

// ── Section 1: Pin Definitions ──────────────────────────────
// These match your wiring: DT on GPIO4, SCK on GPIO5
#define DOUT_PIN 4
#define SCK_PIN  5

// ── Section 2: HX711 Object ──────────────────────────────────
// Creates the HX711 instance we'll use throughout the sketch
HX711 scale;

// ── Section 3: Setup ─────────────────────────────────────────
// Runs once on boot — initializes serial and the HX711
void setup() {
    Serial.begin(115200);
    delay(1000); // Give serial monitor time to connect

    Serial.println("=== HX711 Scanner ===");
    Serial.println("Initializing HX711...");

    scale.begin(DOUT_PIN, SCK_PIN);

    // ── Section 4: Connection Check ──────────────────────────
    // is_ready() checks if DOUT is being pulled LOW by the HX711
    // If this fails, check your wiring or power supply (VCC/GND)
    if (scale.is_ready()) {
        Serial.println("✅ HX711 found and ready!");
    } else {
        Serial.println("❌ HX711 NOT detected. Check wiring:");
        Serial.println("   - VCC → 3.3V or 5V");
        Serial.println("   - GND → GND");
        Serial.println("   - DT  → GPIO4");
        Serial.println("   - SCK → GPIO5");
    }
}

// ── Section 5: Loop ───────────────────────────────────────────
// Continuously reads raw values every 500ms and prints them
// Raw values will be large numbers (not grams yet — no calibration)
void loop() {
    if (scale.is_ready()) {
        long rawValue = scale.read();
        Serial.print("Raw reading: ");
        Serial.println(rawValue);
    } else {
        Serial.println("HX711 not ready — waiting...");
    }
    delay(500);
}
