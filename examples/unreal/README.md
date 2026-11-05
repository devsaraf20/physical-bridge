# Unreal Engine → Physical Bridge (OSC plugin)

Unreal ships with an **OSC** plugin. Enable it under **Edit → Plugins → OSC**
and restart the editor. The bridge listens for OSC on UDP port **9000**.

## Blueprint only

In your actor's Event Graph:

1. **Event BeginPlay** → **Create OSC Client**
   (*IP Address* `127.0.0.1`, *Port* `9000`, *Client Name* `PhysicalBridge`) →
   **Promote to variable** `BridgeClient`.
2. On **Event Tick** (or a timer at 30 Hz):
   * **Construct OSC Message**
   * **Convert String to OSC Address** (`/pb/arm`) → **Set OSC Message Address**
   * one **Add Float** per motor (e.g. *Get Relative Rotation → Yaw*)
   * `BridgeClient` → **Send OSC Message**

```
BeginPlay ─► Create OSC Client(127.0.0.1, 9000) ─► Set BridgeClient

Tick ─► Construct OSC Message ─► Set OSC Message Address("/pb/arm")
                               ─► Add Float(Joint1.Yaw)
                               ─► Add Float(Joint2.Yaw)
                               ─► BridgeClient.Send OSC Message
```

Single values work the same way with one **Add Float** (address `/pb/dimmer`).
For grids send two **Add Int32** (width, height) followed by **Add Blob**
(an array of bytes 0..255, row-major) — the bridge recognises `[w, h, blob]`.

## C++ component

[`Source/PhysicalBridgeSender.h/.cpp`](Source) is a drop-in actor component:

* `SendValue`, `SendAngles`, `SendGrid`, `SendRenderTarget` are Blueprint callable.
* Or fill in **Angle Sources** (scene components whose rotation drives motors)
  and **Grid Source** (a small render target, e.g. 32×32 from a Scene Capture 2D)
  and it sends automatically at **Send Rate Hz**.

Setup: add `"OSC"` to `PublicDependencyModuleNames` in your `*.Build.cs`, copy the
two files to your project's `Source/<Project>/` folder, replace
`PHYSICALBRIDGE_API` with your module's API macro and rebuild.

## Matching bridge config

```yaml
streams:
  arm:
    type: angles
    source: /pb/arm
    pipeline:
      - map: {in: [-90, 90], out: [0, 180]}   # Unreal yaw -> servo range
      - smooth: {time: 0.05}
    safety: {min: 5, max: 175, max_speed: 180}
    outputs: [arduino]
  matrix:
    type: grid
    source: /pb/matrix                         # [w, h, blob] with bytes 0..255
    pipeline:
      - resize: {width: 16, height: 16}
      - dither: {method: bayer}
    outputs: [esp32]
```
