#pragma once
#include "Arduino.h"
#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 3
#endif
inline void ledcAttach(uint8_t pin, uint32_t, uint8_t) { mock::event("ledc attach " + std::to_string(pin)); }
inline void ledcSetup(uint8_t, uint32_t, uint8_t) {}
inline void ledcAttachPin(uint8_t pin, uint8_t) { mock::event("ledc attach " + std::to_string(pin)); }
inline void ledcWrite(uint8_t ch, uint32_t duty) {
  mock::event("ledc " + std::to_string(ch) + " " + std::to_string(duty));
}
