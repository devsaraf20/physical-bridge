#pragma once
#include "Arduino.h"
#define NEO_GRB 0
#define NEO_KHZ800 0
class Adafruit_NeoPixel {
 public:
  Adafruit_NeoPixel(uint16_t n, uint8_t, int) : px(n * 3) {}
  void begin() {}
  void setBrightness(uint8_t b) { mock::event("brightness " + std::to_string(b)); }
  void clear() { std::fill(px.begin(), px.end(), 0); }
  void show() {
    std::string s = "show";
    for (size_t i = 0; i < px.size(); i += 3) s += " " + std::to_string(px[i]);
    mock::event(s);
  }
  void setPixelColor(uint16_t i, uint8_t r, uint8_t g, uint8_t b) {
    px[i * 3] = r; px[i * 3 + 1] = g; px[i * 3 + 2] = b;
  }
  std::vector<uint8_t> px;
};
