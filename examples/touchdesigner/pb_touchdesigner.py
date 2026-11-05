# Physical Bridge sender for TouchDesigner
# ===========================================================================
# 1. Add an "Execute DAT" to your network and paste this whole file into it
#    (or point the DAT's File parameter at this file).
# 2. Turn on the DAT's "Frame End" toggle.
# 3. Edit the SETTINGS block below to point at your TOPs / CHOPs.
#
# Transport: by default this creates nothing - it sends with an "OSC Out DAT"
# named oscout1 (Network Address 127.0.0.1, Port 9000).  Create one, or set
# TRANSPORT = 'websocket' and add a "WebSocket DAT" named websocket1 with
# Network Address ws://127.0.0.1:9001  (Active = On).
#
# Matching bridge config (config.yaml):
#   streams:
#     matrix: {type: grid,   source: /pb/matrix, input_range: [0, 1], ...}
#     arm:    {type: angles, source: /pb/arm,    input_range: [0, 1], ...}
#     dimmer: {type: value,  source: /pb/dimmer, input_range: [0, 1], ...}
# ===========================================================================
import json

# ------------------------------------------------------------------ SETTINGS
TRANSPORT = 'osc'          # 'osc' or 'websocket'
OSC_DAT = 'oscout1'
WS_DAT = 'websocket1'

# TOPs to send as 2D grids. Put a Resolution TOP in front so they are SMALL
# (e.g. 32x32): every pixel is a number on the wire.
GRIDS = {
    # 'stream name': 'TOP path'
    'matrix': 'null_matrix',
}

# CHOPs whose channels are sent as a list (motor angles) - one message per CHOP
ANGLE_CHOPS = {
    'arm': 'null_servos',
}

# Single values: 'stream name': ('CHOP path', 'channel name')
VALUES = {
    'dimmer': ('null_controls', 'dimmer'),
}

SEND_EVERY_N_FRAMES = 1    # 2 = 30 fps at a 60 fps timeline
# ---------------------------------------------------------------------------


def _send(stream, data):
    if TRANSPORT == 'websocket':
        op(WS_DAT).sendText(json.dumps({'stream': stream, 'data': data}))
    else:
        op(OSC_DAT).sendOSC('/pb/' + stream, data)


def _top_to_grid(top):
    # numpyArray(): float32 [height, width, RGBA], rows bottom-to-top
    arr = top.numpyArray(delayed=True)
    if arr is None:
        return None
    h, w = arr.shape[0], arr.shape[1]
    lum = arr[::-1, :, 0] * 0.299 + arr[::-1, :, 1] * 0.587 + arr[::-1, :, 2] * 0.114
    values = [round(float(v), 3) for v in lum.clip(0, 1).ravel()]
    return [w, h] + values


def onFrameEnd(frame):
    if frame % SEND_EVERY_N_FRAMES:
        return
    for stream, path in GRIDS.items():
        top = op(path)
        if top is not None:
            grid = _top_to_grid(top)
            if grid:
                if TRANSPORT == 'websocket':
                    _send(stream, {'w': grid[0], 'h': grid[1], 'data': grid[2:]})
                else:
                    _send(stream, grid)
    for stream, path in ANGLE_CHOPS.items():
        chop = op(path)
        if chop is not None:
            _send(stream, [float(c.eval()) for c in chop.chans()])
    for stream, (path, chan) in VALUES.items():
        chop = op(path)
        if chop is not None and chop[chan] is not None:
            _send(stream, [float(chop[chan].eval())])
    return
