// Physical Bridge - servos on an ESP32 (USB serial or Wi-Fi)
//
// Receives ANGLES (degrees) for up to 8 servos using the ESP32's LEDC PWM.
// No servo library needed.  Works with ESP32 Arduino core 2.x and 3.x.
//
// Bridge output config:
//   USB:    {type: serial, port: auto, baud: 115200}
//   Wi-Fi:  {type: serial, port: "socket://<esp32-ip>:3333"}   (set USE_WIFI 1)
//
// Wiring: servo signal -> pins below, servo power from a separate 5-6 V supply,
// grounds joined.  Avoid GPIO 6-11 (flash) and 34-39 (input only).
#include <PhysicalBridge.h>

#define USE_WIFI 0
#if USE_WIFI
#include <WiFi.h>
const char* WIFI_SSID = "your-network";
const char* WIFI_PASS = "your-password";
WiFiServer server(3333);
WiFiClient client;
#endif

const uint8_t SERVO_PINS[] = {13, 12, 14, 27, 26, 25, 33, 32};
const uint8_t NUM_SERVOS = sizeof(SERVO_PINS);
const float MIN_ANGLE = 0, MAX_ANGLE = 180, START_ANGLE = 90;
const uint16_t MIN_US = 500, MAX_US = 2500;  // check your servo's datasheet
const uint32_t FAILSAFE_MS = 0;              // >0: stop pulses (limp) after silence

pb::Device bridge(Serial, "pb_servos_esp32");
bool pulsing = true;

void pwmAttach(uint8_t i) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(SERVO_PINS[i], 50, 16);
#else
  ledcSetup(i, 50, 16);
  ledcAttachPin(SERVO_PINS[i], i);
#endif
}

void pwmWrite(uint8_t i, uint32_t duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(SERVO_PINS[i], duty);
#else
  ledcWrite(i, duty);
#endif
}

void writeAngle(uint8_t i, float deg) {
  deg = constrain(deg, MIN_ANGLE, MAX_ANGLE);
  float us = MIN_US + (MAX_US - MIN_US) * (deg / 180.0f);
  pwmWrite(i, (uint32_t)(us / 20000.0f * 65535.0f));  // 20 ms period
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < NUM_SERVOS; i++) { pwmAttach(i); writeAngle(i, START_ANGLE); }
#if USE_WIFI
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);
  Serial.print("Physical Bridge: socket://"); Serial.print(WiFi.localIP()); Serial.println(":3333");
  server.begin();
  server.setNoDelay(true);
#endif
  bridge.begin();
}

void loop() {
#if USE_WIFI
  if (!client || !client.connected()) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    client = server.accept();
#else
    client = server.available();
#endif
    if (client) { client.setNoDelay(true); bridge.setStream(client); bridge.begin(); }
    else return;
  }
#endif
  while (bridge.poll()) {
    const pb::Parser& m = bridge.msg();
    if (m.type == pb::ANGLES) {
      for (uint8_t i = 0; i < NUM_SERVOS && i < m.angleCount(); i++) writeAngle(i, m.angle(i));
      pulsing = true;
    } else if (m.type == pb::VALUE) {
      writeAngle(0, m.value());
      pulsing = true;
    }
  }
  if (FAILSAFE_MS && pulsing && bridge.silenceMs() > FAILSAFE_MS) {
    for (uint8_t i = 0; i < NUM_SERVOS; i++) pwmWrite(i, 0);
    pulsing = false;
  }
}
