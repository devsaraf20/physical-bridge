// Physical Bridge - WS2812 / NeoPixel LED matrix on an ESP32
//
// Receives GRID (0..255 brightness per pixel) or BITS (on/off) and shows them
// on an addressable LED matrix.  Handles serpentine ("zig-zag") wiring.
//
// Needs: PhysicalBridge library + "Adafruit NeoPixel" (Library Manager).
//
// Bridge stream example (16x16 panel):
//   pipeline: [resize: {width: 16, height: 16}, gamma: {value: 2.2}]
//   safety:   {max_mean: 64}          # keep total current within your PSU
//   outputs:  [{name: esp32}]         # {type: serial, port: auto, baud: 921600}
//
// Wiring: DIN -> DATA_PIN through a ~330 ohm resistor, 5 V PSU sized for the
// panel (60 mA per LED at full white!), grounds joined, 1000 uF across 5 V.
#include <Adafruit_NeoPixel.h>
#include <PhysicalBridge.h>

#define USE_WIFI 0
#if USE_WIFI
#include <WiFi.h>
const char* WIFI_SSID = "your-network";
const char* WIFI_PASS = "your-password";
WiFiServer server(3333);
WiFiClient client;
#endif

const uint8_t DATA_PIN = 16;
const uint8_t WIDTH = 16, HEIGHT = 16;
const bool SERPENTINE = true;          // every other row runs backwards
const uint8_t MAX_BRIGHTNESS = 80;     // device-side cap, 0..255
const uint8_t COLOR_R = 255, COLOR_G = 77, COLOR_B = 46;  // colour of "on"
const uint32_t BLANK_AFTER_MS = 3000;
const long BAUD = 921600;              // match `baud:` in the bridge config

Adafruit_NeoPixel strip(WIDTH * HEIGHT, DATA_PIN, NEO_GRB + NEO_KHZ800);
pb::Device bridge(Serial, "pb_led_matrix_esp32");
bool blank = true;

uint16_t indexOf(uint8_t x, uint8_t y) {
  if (SERPENTINE && (y & 1)) x = WIDTH - 1 - x;
  return (uint16_t)y * WIDTH + x;
}

void setup() {
  Serial.setRxBufferSize(4096);
  Serial.begin(BAUD);
  strip.begin();
  strip.setBrightness(MAX_BRIGHTNESS);
  strip.clear();
  strip.show();
#if USE_WIFI
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);
  Serial.print("Physical Bridge: socket://"); Serial.print(WiFi.localIP()); Serial.println(":3333");
  server.begin();
#endif
  bridge.begin();
}

void loop() {
#if USE_WIFI
  if (!client || !client.connected()) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    client = server.accept();
#else
    client = server.available();
#endif
    if (client) { client.setNoDelay(true); bridge.setStream(client); bridge.begin(); }
  }
#endif
  bool dirty = false;
  while (bridge.poll()) {
    const pb::Parser& m = bridge.msg();
    if (m.type == pb::VALUE) {
      strip.setBrightness(min((int)m.value(), (int)MAX_BRIGHTNESS));
      dirty = true;
      continue;
    }
    if (m.type != pb::GRID && m.type != pb::BITS) continue;
    for (uint8_t y = 0; y < HEIGHT; y++)
      for (uint8_t x = 0; x < WIDTH; x++) {
        uint16_t v = m.pixel(x, y);  // 0 outside the received frame
        strip.setPixelColor(indexOf(x, y), COLOR_R * v / 255, COLOR_G * v / 255, COLOR_B * v / 255);
      }
    dirty = true;
  }
  if (dirty) { strip.show(); blank = false; }  // show once per batch: keeps up with fast input
  if (!blank && BLANK_AFTER_MS && bridge.silenceMs() > BLANK_AFTER_MS) {
    strip.clear(); strip.show(); blank = true;
  }
}
