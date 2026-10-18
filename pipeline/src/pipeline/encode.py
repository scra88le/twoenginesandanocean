"""Pack layer values into uint16 codes and PNGs.

Codes: 0 = no data, 1 = masked, 2..65535 = valid. Linear layers decode as
value = offset + scale * (int - 2); log layers as log10(value) = offset + scale * (int - 2).
`scale` is a fixed per-layer resolution (`step`), not the range divided by 65533: a step
finer than the data means anything leaves the low byte as noise, which PNG can't compress.
Scalar PNGs are RGB with R = high byte, G = low byte, B = 0. Vector PNGs are RGBA with u in
R+G and v in B+A, so the front end must upload them without premultiplying alpha.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

NODATA, MASKED, FIRST_VALID, MAX_INT = 0, 1, 2, 65535
_LEVELS = MAX_INT - FIRST_VALID
SHAPE = (360, 720)


def _space(lo: float, hi: float, log: bool) -> tuple[float, float]:
    return (float(np.log10(lo)), float(np.log10(hi))) if log else (float(lo), float(hi))


def scale_offset(
    lo: float, hi: float, log: bool = False, step: float | None = None
) -> tuple[float, float]:
    """(scale, offset) for the manifest, in log10 units for log layers.

    Without `step` the range is spread over all 65533 levels.
    """
    a, b = _space(lo, hi, log)
    if step is None:
        return (b - a) / _LEVELS, a
    if (b - a) / step > _LEVELS + 1e-9:
        raise ValueError(f"range {lo}..{hi} needs more than 65533 steps of {step}")
    return step, a


def quantise(
    values, masked, lo: float, hi: float, log: bool = False, step: float | None = None
) -> tuple[np.ndarray, int]:
    """Values -> uint16 codes. Returns (codes, number of valid values clipped to the range).

    Masked cells get code 1 whatever their value; NaN elsewhere gets 0. For log layers,
    values <= 0 can't be shown and are coded as masked.
    """
    scale, _ = scale_offset(lo, hi, log, step)
    x = np.asarray(values, dtype="float64")
    masked = np.asarray(masked, dtype=bool)
    if log:
        masked = masked | (x <= 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            x = np.log10(np.where(masked, np.nan, x))
    a, b = _space(lo, hi, log)
    valid = np.isfinite(x) & ~masked
    clipped = int((valid & ((x < a) | (x > b))).sum())
    t = np.clip(np.where(valid, x, a), a, b) - a
    codes = (FIRST_VALID + np.rint(t / scale)).astype(np.uint16)
    codes[~valid] = NODATA
    codes[masked] = MASKED
    return codes, clipped


def decode(
    codes, lo: float, hi: float, log: bool = False, step: float | None = None
) -> np.ndarray:
    """uint16 codes -> values, NaN for no data and masked."""
    q = np.asarray(codes).astype("float64")
    scale, offset = scale_offset(lo, hi, log, step)
    x = offset + scale * (q - FIRST_VALID)
    if log:
        x = 10**x
    return np.where(q >= FIRST_VALID, x, np.nan)


def _png(pixels: np.ndarray, mode: str) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(pixels, mode=mode).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _check(codes: np.ndarray) -> np.ndarray:
    codes = np.asarray(codes)
    if codes.shape != SHAPE or codes.dtype != np.uint16:
        raise ValueError(f"expected uint16 codes of shape {SHAPE}, got {codes.dtype} {codes.shape}")
    return codes


def scalar_png(codes: np.ndarray) -> bytes:
    q = _check(codes)
    px = np.zeros((*SHAPE, 3), dtype=np.uint8)
    px[..., 0], px[..., 1] = q >> 8, q & 0xFF
    return _png(px, "RGB")


def vector_png(u_codes: np.ndarray, v_codes: np.ndarray) -> bytes:
    u, v = _check(u_codes), _check(v_codes)
    px = np.stack([u >> 8, u & 0xFF, v >> 8, v & 0xFF], axis=-1).astype(np.uint8)
    return _png(px, "RGBA")


def png_to_ints(data: bytes):
    """Decode a scalar PNG to codes, or a vector PNG to (u codes, v codes)."""
    img = Image.open(io.BytesIO(data))
    px = np.asarray(img).astype(np.uint16)
    if img.mode == "RGB":
        return (px[..., 0] << 8) | px[..., 1]
    if img.mode == "RGBA":
        return (px[..., 0] << 8) | px[..., 1], (px[..., 2] << 8) | px[..., 3]
    raise ValueError(f"unexpected PNG mode {img.mode}")
