// Minimal host-side Arduino mock used only by the test-suite to compile and
// run the example sketches with g++.  Not a real Arduino core.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <string>
#include <vector>
#include <algorithm>

#ifndef ARDUINO
#define ARDUINO 100
#endif
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define MSBFIRST 1
#define LSBFIRST 0
#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))
using std::min;
using std::max;

namespace mock {
extern unsigned long now_us;
extern std::vector<std::string> events;
inline void event(const std::string& s) { events.push_back(s); }
}  // namespace mock

inline unsigned long millis() { return mock::now_us / 1000; }
inline unsigned long micros() { return mock::now_us; }
inline void delay(unsigned long ms) { mock::now_us += ms * 1000; }
inline void delayMicroseconds(unsigned int us) { mock::now_us += us; }
inline void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t pin, uint8_t val);
inline void shiftOut(uint8_t, uint8_t, uint8_t, uint8_t val) { mock::event("shift " + std::to_string(val)); }
inline long map(long x, long in_min, long in_max, long out_min, long out_max) {
  return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}

class Stream {
 public:
  std::deque<uint8_t> rx;
  std::vector<uint8_t> tx;
  virtual ~Stream() {}
  int available() { return (int)rx.size(); }
  int read() { if (rx.empty()) return -1; int b = rx.front(); rx.pop_front(); return b; }
  size_t write(uint8_t b) { tx.push_back(b); return 1; }
  size_t write(const uint8_t* b, size_t n) { tx.insert(tx.end(), b, b + n); return n; }
  void flush() {}
  template <typename T> void print(const T&) {}
  template <typename T> void println(const T&) {}
  void println() {}
};

class HardwareSerial : public Stream {
 public:
  void begin(long) {}
  void setRxBufferSize(size_t) {}
};
extern HardwareSerial Serial;
