#pragma once
#include "Arduino.h"
class Servo {
 public:
  void attach(int pin) { pin_ = pin; mock::event("attach " + std::to_string(pin)); }
  void detach() { mock::event("detach " + std::to_string(pin_)); }
  void write(int deg) { mock::event("servo " + std::to_string(pin_) + " deg " + std::to_string(deg)); }
  void writeMicroseconds(int us) { mock::event("servo " + std::to_string(pin_) + " us " + std::to_string(us)); }
 private:
  int pin_ = -1;
};
