// Physical Bridge - servos (Arduino Uno / Nano / Mega)
//
// Receives ANGLES (one float per servo, degrees) and moves up to 6 servos.
// Bridge stream type: angles.  Output: type serial, baud 115200.
//
// Wiring: servo signal -> pins below, servo V+ -> external 5-6 V supply
// (NOT the Arduino 5 V pin for more than one small servo), all grounds joined.
//
// Needs the PhysicalBridge library (copy firmware/libraries/PhysicalBridge to
// your Arduino/libraries folder) and the built-in Servo library.
//
// RS485 instead of USB? Set RS485_DE_PIN and ADDRESS below and connect a
// MAX485: RO->RX(0), DI->TX(1), DE+RE->RS485_DE_PIN.
#include <Servo.h>
#include <PhysicalBridge.h>

const uint8_t SERVO_PINS[] = {3, 5, 6, 9, 10, 11};
const uint8_t NUM_SERVOS = sizeof(SERVO_PINS);

// Device-side safety limits (second line of defence after the bridge's own).
const float MIN_ANGLE = 0;
const float MAX_ANGLE = 180;
const float START_ANGLE = 90;
// If nothing arrives for this long, detach servos (they go limp). 0 = hold forever.
const uint32_t FAILSAFE_MS = 0;

const uint8_t ADDRESS = pb::BROADCAST;  // RS485: give each board 1..254
const int RS485_DE_PIN = -1;            // RS485: e.g. 2

Servo servos[NUM_SERVOS];
pb::Device bridge(Serial, "pb_servos", ADDRESS);
bool attached = false;

void attachAll() {
  if (attached) return;
  for (uint8_t i = 0; i < NUM_SERVOS; i++) servos[i].attach(SERVO_PINS[i]);
  attached = true;
}

void setup() {
  Serial.begin(115200);
  if (RS485_DE_PIN >= 0) bridge.setTxEnablePin(RS485_DE_PIN);
  for (uint8_t i = 0; i < NUM_SERVOS; i++) servos[i].write(START_ANGLE);
  attachAll();
  bridge.begin();
}

void loop() {
  while (bridge.poll()) {
    const pb::Parser& m = bridge.msg();
    if (m.type == pb::ANGLES) {
      attachAll();
      for (uint8_t i = 0; i < NUM_SERVOS && i < m.angleCount(); i++) {
        float a = constrain(m.angle(i), MIN_ANGLE, MAX_ANGLE);
        servos[i].writeMicroseconds(map((long)(a * 10), 0, 1800, 544, 2400));
      }
    } else if (m.type == pb::VALUE) {
      // a single value moves servo 0
      servos[0].write(constrain(m.value(), MIN_ANGLE, MAX_ANGLE));
    }
  }
  if (FAILSAFE_MS && attached && bridge.silenceMs() > FAILSAFE_MS) {
    for (uint8_t i = 0; i < NUM_SERVOS; i++) servos[i].detach();
    attached = false;
  }
}
