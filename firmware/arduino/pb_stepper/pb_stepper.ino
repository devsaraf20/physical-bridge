// Physical Bridge - stepper motors (Arduino Uno / Nano / Mega)
//
// Receives ANGLES (degrees, one per motor) and moves STEP/DIR stepper drivers
// (A4988, DRV8825, TMC2208, ...) to those absolute positions.  Angles may be
// negative or above 360 for multi-turn moves.  No extra libraries needed.
//
// Bridge stream type: angles  (tip: add `limits: {max_speed: ...}` so the host
// never asks for more than the motor can do).
//
// Wiring per motor: STEP, DIR (and optional shared EN, active LOW).
// The position at power-up is treated as 0 degrees - home your mechanism first.
#include <PhysicalBridge.h>

struct Motor {
  uint8_t stepPin, dirPin;
  long position;  // steps
  long target;    // steps
  unsigned long lastStepUs;
};

Motor motors[] = {
  {2, 5, 0, 0, 0},   // CNC shield X
  {3, 6, 0, 0, 0},   // CNC shield Y
};
const uint8_t NUM_MOTORS = sizeof(motors) / sizeof(motors[0]);
const int ENABLE_PIN = 8;              // CNC shield EN, -1 if unused

const float STEPS_PER_REV = 200 * 16;  // 1.8 deg motor, 1/16 microstepping
const float MAX_STEPS_PER_SEC = 4000;  // device-side speed cap
const float MIN_ANGLE = -3600, MAX_ANGLE = 3600;  // device-side travel limits

pb::Device bridge(Serial, "pb_stepper");
const unsigned long STEP_INTERVAL_US = 1000000UL / MAX_STEPS_PER_SEC;

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < NUM_MOTORS; i++) {
    pinMode(motors[i].stepPin, OUTPUT);
    pinMode(motors[i].dirPin, OUTPUT);
  }
  if (ENABLE_PIN >= 0) { pinMode(ENABLE_PIN, OUTPUT); digitalWrite(ENABLE_PIN, LOW); }
  bridge.begin();
}

void stepMotors() {
  unsigned long now = micros();
  for (uint8_t i = 0; i < NUM_MOTORS; i++) {
    Motor& m = motors[i];
    if (m.position == m.target || now - m.lastStepUs < STEP_INTERVAL_US) continue;
    bool forward = m.target > m.position;
    digitalWrite(m.dirPin, forward ? HIGH : LOW);
    digitalWrite(m.stepPin, HIGH);
    delayMicroseconds(2);
    digitalWrite(m.stepPin, LOW);
    m.position += forward ? 1 : -1;
    m.lastStepUs = now;
  }
}

void loop() {
  while (bridge.poll()) {
    const pb::Parser& msg = bridge.msg();
    if (msg.type != pb::ANGLES && msg.type != pb::VALUE) continue;
    uint16_t n = msg.type == pb::VALUE ? 1 : msg.angleCount();
    for (uint8_t i = 0; i < NUM_MOTORS && i < n; i++) {
      float deg = msg.type == pb::VALUE ? msg.value() : msg.angle(i);
      deg = constrain(deg, MIN_ANGLE, MAX_ANGLE);
      motors[i].target = lround(deg / 360.0 * STEPS_PER_REV);
    }
  }
  stepMotors();
}
