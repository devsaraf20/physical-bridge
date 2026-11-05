# TouchDesigner → Physical Bridge

Two ways in, both on by default in `config.yaml`:

| Transport | TouchDesigner operator | Bridge port |
|-----------|------------------------|-------------|
| OSC (UDP) | OSC Out DAT / OSC Out CHOP | 9000 |
| WebSocket | WebSocket DAT | 9001 |

## A. Script (grids, angles and values) – recommended

1. Create an **OSC Out DAT** named `oscout1`: *Network Address* `127.0.0.1`, *Network Port* `9000`.
2. Create an **Execute DAT**, paste in [`pb_touchdesigner.py`](pb_touchdesigner.py), switch on **Frame End**.
3. Edit the `SETTINGS` block so it names your operators:
   * **Grids**: any TOP. Put a **Resolution TOP** (e.g. 32×32, *Output Resolution: Custom*) and a
     **Null TOP** before it. The script converts to luminance (0..1) and sends `[w, h, v0, v1, …]`.
   * **Angles**: a CHOP whose channels are your motors (0..1 each, map to degrees in the bridge).
   * **Values**: a single channel of a CHOP.
4. Start the bridge and open <http://localhost:8080>. The OSC input card should say *receiving*.

Using WebSocket instead: set `TRANSPORT = 'websocket'` and add a **WebSocket DAT** named
`websocket1` with *Network Address* `127.0.0.1`, *Port* `9001`.

## B. No script: OSC Out CHOP (single values / angles)

An **OSC Out CHOP** sends your channels without any Python. How the addresses
look depends on the CHOP's settings (one message per channel named after the
channel, or all channels in one message). Point it at `127.0.0.1:9000`, then open
the dashboard: anything that does not match a stream is listed under
**Unrouted addresses** – copy that address into the stream's `source:`.

To combine several per-channel messages into one list of motor angles, give
the stream a list of sources:

```yaml
streams:
  arm:
    type: angles
    source: [/servo1, /servo2, /servo3]   # one address per motor, in order
    pipeline:
      - map: {in: [0, 1], out: [0, 180]}
```

## Tips

* Keep TOPs small (≤ 64×64). Resize in TouchDesigner, then let the bridge resize
  exactly to your matrix size with `resize` + `dither`.
* `numpyArray()` returns rows bottom-to-top; the script flips them so row 0 is the top.
