// Runs a sketch: setup(), then feeds stdin bytes and calls loop().
// Prints mock events and bytes the sketch wrote to Serial (hex).
#include "Arduino.h"
#ifdef MOCK_ESP32
#include "esp32-hal.h"
#endif
#include SKETCH

namespace mock {
unsigned long now_us = 1000;
std::vector<std::string> events;
}
HardwareSerial Serial;
void digitalWrite(uint8_t pin, uint8_t val) {
  if (pin != 255) mock::event("pin " + std::to_string(pin) + " " + std::to_string(val));
}

int main() {
  setup();
  int c;
  while ((c = getchar()) != EOF) Serial.rx.push_back((uint8_t)c);
  for (int i = 0; i < 20000; i++) { loop(); mock::now_us += 100; }
  for (auto& e : mock::events)
    if (e.rfind("pin ", 0) != 0 && e.rfind("shift ", 0) != 0) printf("%s\n", e.c_str());
  int steps = 0;
  for (auto& e : mock::events) if (e.rfind("pin ", 0) == 0 && e.back() == '1') steps++;
  printf("pin_high_events %d\n", steps);
  int shifts = 0;
  for (auto& e : mock::events) if (e.rfind("shift ", 0) == 0) shifts++;
  printf("shift_events %d\n", shifts);
  printf("serial_tx ");
  for (uint8_t b : Serial.tx) printf("%02x", b);
  printf("\n");
  return 0;
}
