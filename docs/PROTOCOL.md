# Physical Bridge Protocol (PBP v1)

One small binary format is used on every byte link the bridge drives: USB
serial, RS485 and TCP (`socket://`, e.g. ESP32 over Wi-Fi). The reference
implementations are [`physical_bridge/protocol.py`](../physical_bridge/protocol.py)
(host) and [`firmware/libraries/PhysicalBridge/src/PhysicalBridge.h`](../firmware/libraries/PhysicalBridge/src/PhysicalBridge.h)
(device). The test-suite compiles the C++ header and checks both against each other.

## Frame

```
 byte:   0     1     2      3      4        5        6 .. 6+LEN-1   6+LEN
       +-----+-----+------+------+--------+--------+--------------+------+
       | 'P' | 'B' | TYPE | ADDR | LEN lo | LEN hi |   PAYLOAD    | CRC8 |
       +-----+-----+------+------+--------+--------+--------------+------+
         0x50  0x42
```

| Field   | Meaning |
|---------|---------|
| `P B`   | Sync bytes. A receiver hunts for them to (re)synchronise. |
| `TYPE`  | Message type (table below). Unknown types are treated as a false sync and skipped. |
| `ADDR`  | Device address 0–254. **255 = broadcast** (every device accepts it). |
| `LEN`   | Payload length, little endian, 0–65535 (devices cap it: 300 B on AVR, 4 KiB on ESP32 by default — `PB_MAX_PAYLOAD`). |
| `CRC8`  | CRC-8, polynomial 0x07, init 0x00, no reflection, no final XOR, over `TYPE ADDR LEN PAYLOAD`. Check value for `"123456789"` is `0xF4`. |

All multi-byte numbers are **little endian**; floats are IEEE-754 binary32.

## Message types

| Type     | Code | Direction     | Payload |
|----------|------|---------------|---------|
| `VALUE`  | 0x01 | host → device | `float32` |
| `ANGLES` | 0x02 | host → device | `N × float32`, degrees (`N = LEN / 4`) |
| `BITS`   | 0x03 | host → device | `W:u8 H:u8` + `ceil(W·H/8)` bytes: row-major bits, MSB first, last byte zero-padded |
| `GRID`   | 0x04 | host → device | `W:u8 H:u8` + `W·H` bytes 0–255, row-major (row 0 = top) |
| `PING`   | 0x10 | host → device | empty |
| `HELLO`  | 0x20 | device → host | UTF-8 device name |
| `PONG`   | 0x21 | device → host | empty |
| `LOG`    | 0x22 | device → host | UTF-8 text (shown in the dashboard) |

## Behaviour

* **Addressing** – a device with an address accepts frames for its address and
  for 255. A device configured with address 255 (the default for USB sketches)
  accepts everything.
* **Heartbeat** – the host sends `PING` every `ping_interval` (1 s). A device
  answers with `PONG` (and the first time also with `HELLO`), which the
  dashboard shows as *device responding*.
* **Boot** – USB devices send `HELLO` at start-up. The host waits for it (up to
  `boot_wait`, 2 s) after opening the port, because most boards reset when the
  port opens.
* **RS485 (half duplex)** – nodes never talk spontaneously. They reply only to a
  `PING` carrying their own address; the host polls one address at a time.
  Frames echoed back by the adapter are ignored by type.
* **Flow control** – none. The host keeps only the newest frame per stream, so
  a slow link drops stale frames instead of adding latency. Use `rate_limit` /
  `max_fps` to stay within the link budget (the virtual device shows the load).

## Example

`ANGLES [90.0, 45.5]` to broadcast:

```
50 42 02 FF 08 00 | 00 00 B4 42 | 00 00 36 42 | CRC
 P  B  T  A  len=8   90.0f         45.5f
```

## Bandwidth cheat sheet (115200 baud ≈ 11.5 KB/s)

| Frame                         | Bytes | Max fps @115200 | Max fps @921600 |
|-------------------------------|------:|----------------:|----------------:|
| 6 servos (`ANGLES`)           | 31    | 370             | 2900            |
| 8×8 `BITS`                    | 17    | 670             | 5400            |
| 16×16 `BITS`                  | 41    | 280             | 2200            |
| 16×16 `GRID`                  | 265   | 43              | 340             |
| 32×32 `GRID`                  | 1033  | 11              | 89              |
