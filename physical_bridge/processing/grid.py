"""Pure numpy image operations for 2D grids (values in 0..255)."""
from __future__ import annotations

import numpy as np

# ------------------------------------------------------------------ resize


def _area_weights(n_in: int, n_out: int) -> np.ndarray:
    """(n_out, n_in) matrix; row i averages the source span covered by output i."""
    scale = n_in / n_out
    starts = np.arange(n_out)[:, None] * scale
    ends = starts + scale
    src = np.arange(n_in)[None, :]
    overlap = np.clip(np.minimum(ends, src + 1) - np.maximum(starts, src), 0, None)
    return overlap / overlap.sum(axis=1, keepdims=True)


def _linear_weights(n_in: int, n_out: int) -> np.ndarray:
    scale = n_in / n_out
    x = np.clip((np.arange(n_out) + 0.5) * scale - 0.5, 0, n_in - 1)
    j0 = np.floor(x).astype(int)
    j1 = np.minimum(j0 + 1, n_in - 1)
    frac = x - j0
    w = np.zeros((n_out, n_in))
    rows = np.arange(n_out)
    np.add.at(w, (rows, j0), 1 - frac)
    np.add.at(w, (rows, j1), frac)
    return w


def resize(grid: np.ndarray, width: int, height: int, mode: str = "area") -> np.ndarray:
    """Resize a 2D array.  ``mode`` is ``nearest``, ``area`` (box filter, best
    for shrinking video to a small LED matrix) or ``bilinear``."""
    g = np.asarray(grid, dtype=np.float32)
    h, w = g.shape
    if (w, h) == (width, height):
        return g
    if mode == "nearest":
        ys = np.minimum((np.arange(height) + 0.5) * h / height, h - 1).astype(int)
        xs = np.minimum((np.arange(width) + 0.5) * w / width, w - 1).astype(int)
        return g[ys][:, xs]
    if mode == "area":
        wy, wx = _area_weights(h, height), _area_weights(w, width)
    elif mode == "bilinear":
        wy, wx = _linear_weights(h, height), _linear_weights(w, width)
    else:
        raise ValueError(f"unknown resize mode {mode!r}")
    return (wy @ g @ wx.T).astype(np.float32)


# --------------------------------------------------------------- dithering

_BAYER2 = np.array([[0, 2], [3, 1]])


def bayer_matrix(n: int) -> np.ndarray:
    """Normalised (0..1) Bayer threshold matrix of size n x n (n power of 2)."""
    m = _BAYER2
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return (m + 0.5) / m.size


def quantize(grid: np.ndarray, levels: int) -> np.ndarray:
    step = 255.0 / (levels - 1)
    return np.clip(np.rint(np.asarray(grid, np.float32) / step), 0, levels - 1) * step


def dither_ordered(grid: np.ndarray, levels: int = 2, size: int = 4) -> np.ndarray:
    g = np.asarray(grid, dtype=np.float32)
    h, w = g.shape
    m = bayer_matrix(size)
    tiled = np.tile(m, (h // size + 1, w // size + 1))[:h, :w]
    step = 255.0 / (levels - 1)
    scaled = g / step
    out = np.floor(scaled) + (scaled - np.floor(scaled) > tiled)
    return np.clip(out, 0, levels - 1) * step


_KERNELS = {
    # (dy, dx, weight) relative to current pixel, weights already normalised
    "floyd_steinberg": [(0, 1, 7 / 16), (1, -1, 3 / 16), (1, 0, 5 / 16), (1, 1, 1 / 16)],
    "atkinson": [(0, 1, 1 / 8), (0, 2, 1 / 8), (1, -1, 1 / 8), (1, 0, 1 / 8),
                 (1, 1, 1 / 8), (2, 0, 1 / 8)],
}


def dither_error_diffusion(grid: np.ndarray, method: str = "floyd_steinberg",
                           levels: int = 2, serpentine: bool = True) -> np.ndarray:
    kernel = _KERNELS[method]
    g = np.asarray(grid, dtype=np.float64).copy()
    h, w = g.shape
    step = 255.0 / (levels - 1)
    for y in range(h):
        reverse = serpentine and y % 2 == 1
        xs = range(w - 1, -1, -1) if reverse else range(w)
        row = g[y]
        for x in xs:
            old = row[x]
            new = min(max(round(old / step), 0), levels - 1) * step
            row[x] = new
            err = old - new
            if err == 0:
                continue
            for dy, dx, k in kernel:
                if reverse:
                    dx = -dx
                yy, xx = y + dy, x + dx
                if yy < h and 0 <= xx < w:
                    g[yy, xx] += err * k
    return g.astype(np.float32)


DITHER_METHODS = ("floyd_steinberg", "atkinson", "bayer")


def dither(grid: np.ndarray, method: str = "floyd_steinberg", levels: int = 2,
           size: int = 4) -> np.ndarray:
    if method == "bayer":
        return dither_ordered(grid, levels, size)
    if method in _KERNELS:
        return dither_error_diffusion(grid, method, levels)
    raise ValueError(f"unknown dither method {method!r}; use one of {DITHER_METHODS}")
