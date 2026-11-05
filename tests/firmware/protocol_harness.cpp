// Host-side harness for firmware/libraries/PhysicalBridge/src/PhysicalBridge.h
// Reads raw bytes on stdin, prints one line per decoded packet.  With the
// argument "encode TYPE ADDR HEXPAYLOAD" it prints an encoded frame as hex.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define PB_MAX_PAYLOAD 8192
#include "PhysicalBridge.h"

int main(int argc, char** argv) {
  if (argc == 5 && strcmp(argv[1], "encode") == 0) {
    std::vector<uint8_t> payload;
    for (const char* p = argv[4]; p[0] && p[1]; p += 2) {
      char b[3] = {p[0], p[1], 0};
      payload.push_back((uint8_t)strtol(b, nullptr, 16));
    }
    std::vector<uint8_t> out(payload.size() + 7);
    uint16_t n = pb::encodeFrame(out.data(), (uint8_t)atoi(argv[2]), (uint8_t)atoi(argv[3]),
                                 payload.data(), (uint16_t)payload.size());
    for (uint16_t i = 0; i < n; i++) printf("%02x", out[i]);
    printf("\n");
    return 0;
  }
  static pb::Parser p;
  int c;
  while ((c = getchar()) != EOF) {
    if (!p.feed((uint8_t)c)) continue;
    printf("type=%d addr=%d len=%d", p.type, p.addr, p.length);
    if (p.type == pb::VALUE) printf(" value=%.4f", p.value());
    if (p.type == pb::ANGLES) {
      printf(" angles=");
      for (uint16_t i = 0; i < p.angleCount(); i++) printf("%s%.3f", i ? "," : "", p.angle(i));
    }
    if (p.type == pb::BITS || p.type == pb::GRID) {
      printf(" w=%d h=%d bits=", p.width(), p.height());
      for (uint8_t y = 0; y < p.height(); y++)
        for (uint8_t x = 0; x < p.width(); x++) putchar(p.bit(x, y) ? '1' : '0');
      printf(" px=");
      for (uint8_t y = 0; y < p.height(); y++)
        for (uint8_t x = 0; x < p.width(); x++) printf("%02x", p.pixel(x, y));
    }
    printf("\n");
  }
  printf("crc_errors=%u too_long=%u\n", (unsigned)p.crcErrors, (unsigned)p.tooLong);
  return 0;
}
