"""Physical Bridge sender for Blender (2.9x / 3.x / 4.x)

Run it from Blender's *Scripting* workspace: open this file in the Text
Editor and press *Run Script*.  It streams over OSC (UDP, standard library
only) while you scrub, play the timeline or move things in the viewport.
Run it again to restart.  To stop, run this in the Python console:
``bpy.app.driver_namespace["pb_stop"]()``

What it sends (edit SETTINGS):

* ANGLES  rotation of objects or pose bones, in degrees      -> /pb/arm
* VALUES  any property, e.g. a custom property or a location -> /pb/dimmer
* GRIDS   an image's pixels, e.g. a render result saved as an image or a
          texture you paint on (keep it small: 16x16 .. 64x64) -> /pb/matrix

Matching bridge streams (degrees arrive as degrees, so no map step needed):

    arm:    {type: angles, source: /pb/arm, safety: {min: 0, max: 180, max_speed: 120}}
    dimmer: {type: value,  source: /pb/dimmer, input_range: [0, 1]}
    matrix: {type: grid,   source: /pb/matrix, input_range: [0, 1]}
"""
import math
import socket
import struct

import bpy

# ------------------------------------------------------------------ SETTINGS
HOST, PORT = "127.0.0.1", 9000
RATE_HZ = 30           # max send rate while interacting

# stream -> list of (object name, bone name or None, axis 'X'|'Y'|'Z')
ANGLES = {
    "arm": [
        ("Armature", "Bone", "Z"),
        ("Armature", "Bone.001", "Z"),
        ("Cube", None, "Z"),
    ],
}

# stream -> python expression evaluated with bpy available
VALUES = {
    "dimmer": 'bpy.data.objects["Cube"].location.z',
}

# stream -> image name in bpy.data.images (greyscale from RGB)
GRIDS = {
    # "matrix": "matrix_16x16",
}
# ---------------------------------------------------------------------------


def _pad(b):
    return b + b"\0" * (-len(b) % 4)


def osc(address, *args):
    tags, data = ",", b""
    for a in args:
        if isinstance(a, int):
            tags += "i"; data += struct.pack(">i", a)
        else:
            tags += "f"; data += struct.pack(">f", float(a))
    return _pad(address.encode() + b"\0") + _pad(tags.encode() + b"\0") + data


_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_last = {}


def _send(stream, *args):
    msg = osc("/pb/" + stream, *args)
    if _last.get(stream) == msg:
        return  # unchanged, save bandwidth
    _last[stream] = msg
    try:
        _sock.sendto(msg, (HOST, PORT))
    except OSError as exc:
        print("Physical Bridge send failed:", exc)


def _rotation(obj_name, bone_name, axis):
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        return 0.0
    if bone_name:
        bone = obj.pose.bones.get(bone_name) if obj.pose else None
        if bone is None:
            return 0.0
        euler = bone.matrix_basis.to_euler()
    else:
        euler = obj.matrix_world.to_euler()
    return math.degrees(getattr(euler, axis.lower()))


def _image_grid(name):
    img = bpy.data.images.get(name)
    if img is None or not img.size[0]:
        return None
    w, h = img.size
    px = list(img.pixels)  # RGBA floats, rows bottom-to-top
    rows = []
    for y in range(h - 1, -1, -1):
        base = y * w * 4
        rows.extend(round(0.299 * px[base + x * 4] + 0.587 * px[base + x * 4 + 1]
                          + 0.114 * px[base + x * 4 + 2], 3) for x in range(w))
    return w, h, rows


def send_all(*_args):
    for stream, specs in ANGLES.items():
        _send(stream, *[_rotation(*s) for s in specs])
    for stream, expr in VALUES.items():
        try:
            _send(stream, float(eval(expr, {"bpy": bpy})))
        except Exception as exc:  # noqa: BLE001
            print("Physical Bridge value", stream, "failed:", exc)
    for stream, image in GRIDS.items():
        g = _image_grid(image)
        if g:
            w, h, vals = g
            _send(stream, w, h, *vals)


def _timer():
    send_all()
    return 1.0 / RATE_HZ


def stop():
    for handlers in (bpy.app.handlers.frame_change_post, bpy.app.handlers.depsgraph_update_post):
        for h in [h for h in handlers if getattr(h, "__name__", "") == "send_all"]:
            handlers.remove(h)
    old = bpy.app.driver_namespace.get("pb_timer")  # survives re-running the script
    if old is not None and bpy.app.timers.is_registered(old):
        bpy.app.timers.unregister(old)
    print("Physical Bridge sender stopped")


def start():
    stop()
    bpy.app.handlers.frame_change_post.append(send_all)    # timeline playback / scrubbing
    bpy.app.timers.register(_timer, persistent=True)        # interactive edits
    bpy.app.driver_namespace["pb_timer"] = _timer
    print(f"Physical Bridge sender -> osc://{HOST}:{PORT} at up to {RATE_HZ} Hz")


# make stop() reachable from the Python console: bpy.app.driver_namespace["pb_stop"]()
bpy.app.driver_namespace["pb_stop"] = stop
start()
