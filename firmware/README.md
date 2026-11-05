# Firmware

| Sketch | Board | Drives | Receives |
|--------|-------|--------|----------|
| [`arduino/pb_servos`](arduino/pb_servos) | Uno / Nano / Mega | up to 6 hobby servos (`Servo` lib) | `ANGLES`, `VALUE` |
| [`arduino/pb_stepper`](arduino/pb_stepper) | Uno / Nano + CNC shield | STEP/DIR drivers (A4988, DRV8825, TMC22xx) | `ANGLES` (absolute, multi-turn) |
| [`arduino/pb_led_matrix`](arduino/pb_led_matrix) | Uno / Nano | MAX7219 8×8 modules (chainable) | `BITS`, `GRID`, `VALUE` = brightness |
| [`esp32/pb_servos_esp32`](esp32/pb_servos_esp32) | ESP32 | up to 8 servos via LEDC PWM | `ANGLES`, `VALUE` |
| [`esp32/pb_stepper_esp32`](esp32/pb_stepper_esp32) | ESP32 | STEP/DIR with acceleration | `ANGLES` |
| [`esp32/pb_led_matrix_esp32`](esp32/pb_led_matrix_esp32) | ESP32 | WS2812/NeoPixel panel, serpentine | `GRID`, `BITS`, `VALUE` = brightness |

All of them use the shared library in [`libraries/PhysicalBridge`](libraries/PhysicalBridge).

## Install the library

Copy (or symlink) `firmware/libraries/PhysicalBridge` into your Arduino
libraries folder, then restart the Arduino IDE:

| OS | Folder |
|----|--------|
| Windows | `Documents\Arduino\libraries\` |
| macOS | `~/Documents/Arduino/libraries/` |
| Linux | `~/Arduino/libraries/` |

With `arduino-cli`: `arduino-cli compile --libraries firmware/libraries -b arduino:avr:uno firmware/arduino/pb_servos`.

The ESP32 matrix sketch also needs **Adafruit NeoPixel** (Library Manager).
ESP32 sketches support Arduino-ESP32 core 2.x and 3.x.

## Writing your own

```cpp
#include <PhysicalBridge.h>
pb::Device bridge(Serial, "my-device");          // add an address for RS485

void setup() { Serial.begin(115200); bridge.begin(); }

void loop() {
  while (bridge.poll()) {                        // answers PINGs for you
    const pb::Parser& m = bridge.msg();
    switch (m.type) {
      case pb::VALUE:  /* m.value() */ break;
      case pb::ANGLES: /* m.angleCount(), m.angle(i) */ break;
      case pb::BITS:   /* m.width(), m.height(), m.bit(x, y) */ break;
      case pb::GRID:   /* m.pixel(x, y) -> 0..255 */ break;
    }
  }
  // bridge.silenceMs() -> time since the last packet, for failsafes
  // bridge.log("text")  -> appears in the dashboard
}
```

### RS485

Wire a MAX485 (or similar) to the board's UART: `RO → RX`, `DI → TX`,
`DE` + `/RE` tied together to a GPIO. In the sketch:

```cpp
pb::Device bridge(Serial, "node-3", 3);   // unique address 1..254
bridge.setTxEnablePin(2);                 // DE/RE pin; also makes the node quiet
```

On the PC side use an `rs485` output with `devices: [3, ...]` and send to it
with `outputs: [{name: bus, address: 3}]`.

### Safety on the device

Every example clamps to its own limits (`MIN_ANGLE`/`MAX_ANGLE`, max step rate,
`MAX_BRIGHTNESS`) even though the bridge already enforces `safety:` — a second
line of defence if something else talks to the port. LED sketches blank and
servo sketches can detach (`FAILSAFE_MS`) when the bridge goes silent.
