# Blender → Physical Bridge

[`pb_blender.py`](pb_blender.py) streams rotations, values and image pixels from
Blender over OSC. It uses only the Python standard library, so nothing has to be
installed into Blender.

1. Start the bridge (`physical-bridge -c config.yaml`).
2. In Blender open the **Scripting** workspace → **Text → Open** → `pb_blender.py`.
3. Edit the `SETTINGS` block (object names, bone names, axes, images).
4. Press **Run Script**. Play the timeline, scrub, or rotate objects — the
   dashboard at <http://localhost:8080> updates live.

Rotations are sent in **degrees**, so a servo stream only needs safety limits:

```yaml
streams:
  arm:
    type: angles
    source: /pb/arm
    pipeline:
      - map: {in: [-90, 90], out: [0, 180]}   # Blender -90..90 -> servo 0..180
      - smooth: {time: 0.05}
    safety: {min: 5, max: 175, max_speed: 180}
    outputs: [arduino]
```

**Animating a matrix from Blender:** create a small image (e.g. 16×16) in the
Image Editor, paint on it or bake to it, and list it under `GRIDS`. Large images
are slow to read from Python; keep them small.

To stop sending, run `bpy.app.driver_namespace["pb_stop"]()` in the Python console.
