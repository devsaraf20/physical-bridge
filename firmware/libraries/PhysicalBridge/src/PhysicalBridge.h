// PhysicalBridge.h - receiver for the Physical Bridge Protocol (PBP v1).
//
// Header-only and dependency-free.  The parser is plain C++ (it is also
// compiled on the PC by the test-suite); the Device helper below needs Arduino.
//
// Frame:  'P' 'B' TYPE ADDR LEN_LO LEN_HI PAYLOAD[LEN] CRC8
// CRC-8 (poly 0x07, init 0) covers TYPE, ADDR, LEN and PAYLOAD.
//
//   VALUE  0x01  float32
//   ANGLES 0x02  N x float32 degrees
//   BITS   0x03  W H + packed bits, row-major, MSB first
//   GRID   0x04  W H + W*H bytes 0..255, row-major
//   PING   0x10  host -> device, answered with PONG
//   HELLO  0x20  device -> host, "name"
//   PONG   0x21  device -> host
//   LOG    0x22  device -> host, text shown in the dashboard
//
// All numbers are little endian (AVR, ESP32, ARM and x86 all are).
#pragma once

#include <stdint.h>
#include <string.h>

#ifndef PB_MAX_PAYLOAD
#if defined(__AVR__)
#define PB_MAX_PAYLOAD 300   // Uno/Nano: 2 KB RAM.  Enough for 16x16 bits, 16x16 grid, 64 angles
#else
#define PB_MAX_PAYLOAD 4096  // ESP32 etc: up to 64x64 grid
#endif
#endif

namespace pb {

enum MsgType : uint8_t {
  VALUE = 0x01,
  ANGLES = 0x02,
  BITS = 0x03,
  GRID = 0x04,
  PING = 0x10,
  HELLO = 0x20,
  PONG = 0x21,
  LOG = 0x22,
};

static const uint8_t BROADCAST = 0xFF;

inline uint8_t crc8Update(uint8_t crc, uint8_t data) {
  crc ^= data;
  for (uint8_t i = 0; i < 8; i++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  return crc;
}

// Write a complete frame into `out` (needs len + 7 bytes). Returns its size.
inline uint16_t encodeFrame(uint8_t* out, uint8_t type, uint8_t addr, const uint8_t* payload, uint16_t len) {
  out[0] = 'P';
  out[1] = 'B';
  out[2] = type;
  out[3] = addr;
  out[4] = (uint8_t)(len & 0xFF);
  out[5] = (uint8_t)(len >> 8);
  if (len) memcpy(out + 6, payload, len);
  uint8_t crc = 0;
  for (uint16_t i = 2; i < 6 + len; i++) crc = crc8Update(crc, out[i]);
  out[6 + len] = crc;
  return 7 + len;
}

class Parser {
 public:
  uint8_t type = 0;
  uint8_t addr = 0;
  uint16_t length = 0;
  uint8_t payload[PB_MAX_PAYLOAD];
  uint32_t crcErrors = 0;
  uint32_t tooLong = 0;

  // Feed one received byte. Returns true when a complete, valid packet is
  // available in type / addr / length / payload.
  bool feed(uint8_t b) {
    switch (state_) {
      case S_SYNC1:
        if (b == 'P') state_ = S_SYNC2;
        return false;
      case S_SYNC2:
        state_ = (b == 'B') ? S_TYPE : (b == 'P' ? S_SYNC2 : S_SYNC1);
        return false;
      case S_TYPE:
        if (!knownType(b)) {  // false sync inside other data
          state_ = (b == 'P') ? S_SYNC2 : S_SYNC1;
          return false;
        }
        type_ = b; crc_ = crc8Update(0, b); state_ = S_ADDR;
        return false;
      case S_ADDR:
        addr_ = b; crc_ = crc8Update(crc_, b); state_ = S_LEN1;
        return false;
      case S_LEN1:
        len_ = b; crc_ = crc8Update(crc_, b); state_ = S_LEN2;
        return false;
      case S_LEN2:
        len_ |= (uint16_t)b << 8; crc_ = crc8Update(crc_, b);
        if (len_ > PB_MAX_PAYLOAD) { tooLong++; state_ = S_SYNC1; return false; }
        pos_ = 0;
        state_ = len_ ? S_PAYLOAD : S_CRC;
        return false;
      case S_PAYLOAD:
        payload[pos_++] = b; crc_ = crc8Update(crc_, b);
        if (pos_ >= len_) state_ = S_CRC;
        return false;
      case S_CRC:
        state_ = S_SYNC1;
        if (b != crc_) { crcErrors++; return false; }
        type = type_; addr = addr_; length = len_;
        return true;
    }
    state_ = S_SYNC1;
    return false;
  }

  // ---- payload helpers ----------------------------------------------
  float value() const { return floatAt(0); }

  uint16_t angleCount() const { return type == ANGLES ? length / 4 : 0; }
  float angle(uint16_t i) const { return i < angleCount() ? floatAt(i * 4) : 0.0f; }

  uint8_t width() const { return (type == BITS || type == GRID) && length >= 2 ? payload[0] : 0; }
  uint8_t height() const { return (type == BITS || type == GRID) && length >= 2 ? payload[1] : 0; }

  // BITS: 1 if pixel on.  GRID: 1 if brightness >= 128.
  bool bit(uint8_t x, uint8_t y) const {
    if (x >= width() || y >= height()) return false;
    uint16_t i = (uint16_t)y * width() + x;
    if (type == GRID) return payload[2 + i] >= 128;
    if (2 + i / 8 >= length) return false;
    return (payload[2 + i / 8] >> (7 - (i % 8))) & 1;
  }

  // GRID: 0..255.  BITS: 0 or 255.
  uint8_t pixel(uint8_t x, uint8_t y) const {
    if (x >= width() || y >= height()) return 0;
    if (type == BITS) return bit(x, y) ? 255 : 0;
    uint16_t i = 2 + (uint16_t)y * width() + x;
    return i < length ? payload[i] : 0;
  }

  // Text payload of HELLO / LOG (not NUL terminated - copies into buf).
  void text(char* buf, uint16_t size) const {
    uint16_t n = length < size - 1 ? length : size - 1;
    memcpy(buf, payload, n);
    buf[n] = 0;
  }

 private:
  enum State : uint8_t { S_SYNC1, S_SYNC2, S_TYPE, S_ADDR, S_LEN1, S_LEN2, S_PAYLOAD, S_CRC };
  State state_ = S_SYNC1;
  uint8_t type_ = 0, addr_ = 0, crc_ = 0;
  uint16_t len_ = 0, pos_ = 0;

  static bool knownType(uint8_t t) {
    return (t >= VALUE && t <= GRID) || t == PING || (t >= HELLO && t <= LOG);
  }

  float floatAt(uint16_t off) const {
    float f = 0;
    if (off + 4 <= length) memcpy(&f, payload + off, 4);
    return f;
  }
};

}  // namespace pb

#ifdef ARDUINO
#include <Arduino.h>

namespace pb {

// Ties a Parser to a serial port (or any Arduino Stream: WiFiClient, Serial2,
// SoftwareSerial ...), answers PINGs and filters by address.
//
//   pb::Device bridge(Serial, "my-servos");      // USB serial, accepts everything
//   pb::Device bridge(Serial2, "bus-node", 3);   // RS485 node with address 3
//
//   void setup() { Serial.begin(115200); bridge.begin(); }
//   void loop()  { while (bridge.poll()) { ... bridge.msg() ... } }
class Device {
 public:
  Device(Stream& io, const char* name, uint8_t address = BROADCAST)
      : io_(&io), name_(name), address_(address) {}

  // RS485: pin driving the transceiver's DE and /RE (HIGH = transmit).
  // Also makes the node quiet: it only speaks when PINGed by its address.
  void setTxEnablePin(int pin) {
    txPin_ = pin;
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
    quiet_ = true;
  }
  void setQuiet(bool quiet) { quiet_ = quiet; }
  void setStream(Stream& io) { io_ = &io; }

  void begin() {
    if (!quiet_) send(HELLO, (const uint8_t*)name_, strlen(name_));
  }

  // Read what is available. Returns true when a data packet (VALUE, ANGLES,
  // BITS or GRID) addressed to this device is ready in msg().
  bool poll() {
    while (io_->available() > 0) {
      if (!parser_.feed((uint8_t)io_->read())) continue;
      const Parser& p = parser_;
      bool forMe = address_ == BROADCAST || p.addr == address_ || p.addr == BROADCAST;
      if (!forMe) continue;
      lastMs_ = millis();
      if (p.type == PING) {
        // a broadcast PING is only answered on point-to-point links
        if (p.addr == address_ || !quiet_) {
          if (!helloSent_) { send(HELLO, (const uint8_t*)name_, strlen(name_)); helloSent_ = true; }
          send(PONG, nullptr, 0);
        }
        continue;
      }
      if (p.type >= VALUE && p.type <= GRID) return true;
    }
    return false;
  }

  const Parser& msg() const { return parser_; }

  // Milliseconds since the last packet for this device (for failsafes).
  uint32_t silenceMs() const { return lastMs_ ? millis() - lastMs_ : 0xFFFFFFFFUL; }

  void log(const char* text) { send(LOG, (const uint8_t*)text, strlen(text)); }

  void send(uint8_t type, const uint8_t* payload, uint16_t len) {
    uint8_t head[6] = {'P', 'B', type, address_, (uint8_t)(len & 0xFF), (uint8_t)(len >> 8)};
    uint8_t crc = 0;
    for (uint8_t i = 2; i < 6; i++) crc = crc8Update(crc, head[i]);
    for (uint16_t i = 0; i < len; i++) crc = crc8Update(crc, payload[i]);
    if (txPin_ >= 0) { digitalWrite(txPin_, HIGH); delayMicroseconds(50); }
    io_->write(head, 6);
    if (len) io_->write(payload, len);
    io_->write(crc);
    io_->flush();
    if (txPin_ >= 0) digitalWrite(txPin_, LOW);
  }

 private:
  Stream* io_;
  const char* name_;
  uint8_t address_;
  int txPin_ = -1;
  bool quiet_ = false;
  bool helloSent_ = false;
  uint32_t lastMs_ = 0;
  Parser parser_;
};

}  // namespace pb
#endif  // ARDUINO
