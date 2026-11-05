// Physical Bridge - 8x8 LED matrix with a MAX7219 (Arduino Uno / Nano)
//
// Receives BITS (on/off pixels) or GRID (brightness, thresholded at 128) and
// shows the top-left 8x8 pixels.  Chain several modules by raising MODULES:
// module n shows columns n*8 .. n*8+7.
//
// Bridge stream example:   resize 8x8 (or 32x8 for 4 modules) -> dither -> serial
// Wiring: DIN -> 11, CLK -> 13, CS -> 10, VCC -> 5 V, GND -> GND.
// No extra libraries needed (bit-banged).
#include <PhysicalBridge.h>

const uint8_t PIN_DIN = 11, PIN_CLK = 13, PIN_CS = 10;
const uint8_t MODULES = 1;
const uint8_t INTENSITY = 4;           // 0..15
const uint32_t BLANK_AFTER_MS = 3000;  // clear the display if the bridge goes quiet

pb::Device bridge(Serial, "pb_led_matrix");
bool blank = true;

void sendAll(uint8_t reg, uint8_t data) {
  digitalWrite(PIN_CS, LOW);
  for (uint8_t m = 0; m < MODULES; m++) {
    shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, reg);
    shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, data);
  }
  digitalWrite(PIN_CS, HIGH);
}

void sendRow(uint8_t row, const uint8_t* perModule) {
  digitalWrite(PIN_CS, LOW);
  for (int8_t m = MODULES - 1; m >= 0; m--) {  // last module first in the chain
    shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, row + 1);
    shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, perModule[m]);
  }
  digitalWrite(PIN_CS, HIGH);
}

void clearDisplay() {
  for (uint8_t r = 0; r < 8; r++) sendAll(r + 1, 0);
  blank = true;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_DIN, OUTPUT); pinMode(PIN_CLK, OUTPUT); pinMode(PIN_CS, OUTPUT);
  sendAll(0x0F, 0);          // display test off
  sendAll(0x09, 0);          // no decode
  sendAll(0x0B, 7);          // scan all 8 rows
  sendAll(0x0A, INTENSITY);
  sendAll(0x0C, 1);          // normal operation
  clearDisplay();
  bridge.begin();
}

void loop() {
  while (bridge.poll()) {
    const pb::Parser& m = bridge.msg();
    if (m.type == pb::VALUE) {           // a single value sets the brightness 0..255
      sendAll(0x0A, constrain((int)m.value(), 0, 255) / 16);
      continue;
    }
    if (m.type != pb::BITS && m.type != pb::GRID) continue;
    uint8_t rowBytes[MODULES];
    for (uint8_t y = 0; y < 8; y++) {
      for (uint8_t mod = 0; mod < MODULES; mod++) {
        uint8_t b = 0;
        for (uint8_t x = 0; x < 8; x++)
          if (m.bit(mod * 8 + x, y)) b |= 0x80 >> x;
        rowBytes[mod] = b;
      }
      sendRow(y, rowBytes);
    }
    blank = false;
  }
  if (!blank && BLANK_AFTER_MS && bridge.silenceMs() > BLANK_AFTER_MS) clearDisplay();
}
