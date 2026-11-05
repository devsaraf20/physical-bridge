// Physical Bridge - steppers on an ESP32 with acceleration
//
// Receives ANGLES (degrees, absolute, multi-turn allowed) and drives up to 4
// STEP/DIR drivers with a trapezoidal speed profile.  No libraries needed.
// The power-up position is 0 degrees.
//
// Bridge stream type: angles.  Output: {type: serial, port: auto} or Wi-Fi
// {type: serial, port: "socket://<ip>:3333"} with USE_WIFI 1.
#include <PhysicalBridge.h>

#define USE_WIFI 0
#if USE_WIFI
#include <WiFi.h>
const char* WIFI_SSID = "your-network";
const char* WIFI_PASS = "your-password";
WiFiServer server(3333);
WiFiClient client;
#endif

struct Motor {
  uint8_t stepPin, dirPin;
  float position;    // steps (float for smooth speed integration)
  long target;       // steps
  float speed;       // steps/s, signed
  long emitted;      // steps actually pulsed
};

Motor motors[] = {
  {26, 25, 0, 0, 0, 0},
  {33, 32, 0, 0, 0, 0},
};
const uint8_t NUM_MOTORS = sizeof(motors) / sizeof(motors[0]);
const int ENABLE_PIN = 27;  // active LOW, -1 if unused

const float STEPS_PER_REV = 200 * 16;
const float MAX_SPEED = 8000;   // steps/s
const float ACCEL = 20000;      // steps/s^2
const float MIN_ANGLE = -36000, MAX_ANGLE = 36000;

pb::Device bridge(Serial, "pb_stepper_esp32");
unsigned long lastUs = 0;

void setup() {
  Serial.begin(115200);
  for (auto& m : motors) { pinMode(m.stepPin, OUTPUT); pinMode(m.dirPin, OUTPUT); }
  if (ENABLE_PIN >= 0) { pinMode(ENABLE_PIN, OUTPUT); digitalWrite(ENABLE_PIN, LOW); }
#if USE_WIFI
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);
  Serial.print("Physical Bridge: socket://"); Serial.print(WiFi.localIP()); Serial.println(":3333");
  server.begin();
#endif
  bridge.begin();
  lastUs = micros();
}

void updateMotor(Motor& m, float dt) {
  float remaining = m.target - m.position;
  // speed we may still have and stop in time: v^2 = 2 a d
  float vStop = sqrtf(2 * ACCEL * fabsf(remaining));
  float want = constrain(remaining > 0 ? vStop : -vStop, -MAX_SPEED, MAX_SPEED);
  float dv = constrain(want - m.speed, -ACCEL * dt, ACCEL * dt);
  m.speed += dv;
  m.position += m.speed * dt;
  if (fabsf(remaining) < 0.5f && fabsf(m.speed) < ACCEL * dt * 2) { m.position = m.target; m.speed = 0; }
  long whole = lroundf(m.position);
  while (m.emitted != whole) {
    bool fwd = whole > m.emitted;
    digitalWrite(m.dirPin, fwd);
    digitalWrite(m.stepPin, HIGH);
    delayMicroseconds(2);
    digitalWrite(m.stepPin, LOW);
    m.emitted += fwd ? 1 : -1;
  }
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
  }
#endif
  while (bridge.poll()) {
    const pb::Parser& msg = bridge.msg();
    if (msg.type != pb::ANGLES && msg.type != pb::VALUE) continue;
    uint16_t n = msg.type == pb::VALUE ? 1 : msg.angleCount();
    for (uint8_t i = 0; i < NUM_MOTORS && i < n; i++) {
      float deg = constrain(msg.type == pb::VALUE ? msg.value() : msg.angle(i), MIN_ANGLE, MAX_ANGLE);
      motors[i].target = lroundf(deg / 360.0f * STEPS_PER_REV);
    }
  }
  unsigned long now = micros();
  float dt = (now - lastUs) / 1e6f;
  if (dt >= 0.0002f) {  // ~5 kHz control loop
    lastUs = now;
    for (auto& m : motors) updateMotor(m, dt);
  }
}
