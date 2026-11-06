"""Point and series chunks: the same codes as the PNGs, cut into 10 x 10 degree tiles.

The grid (720 x 360 cells, row 0 at the north) splits into 36 x 18 tiles of 20 x 20 cells;
tile (tx, ty) covers columns 20 tx .. 20 tx + 19 and rows 20 ty .. 20 ty + 19. All values
are little-endian uint16 codes with the per-field packing and reserved codes of the PNGs.

- Point chunk `points/{date}/{tx}_{ty}.bin`: every point field (`POINT_FIELDS`: the layers,
  then the readout extras, then the layers added later, `LATE_POINT_LAYERS`) for one date,
  field-major, each field 20 x 20 row-major. Layers not built yet are all code 0 (no data).
  A chunk written before a later layer was added is a prefix of the current layout
  (`LEGACY_POINT_FIELDS`), and readers treat its missing fields as no data.
- Series chunk `series/{layer}/{tx}_{ty}.bin`: one layer for the published dates. A header
  says which dates, because they can have gaps: b"EHS1", uint32 n, n uint32 dates as
  YYYYMMDD, then n x 400 codes, date-major. Being self-describing, a series file never
  disagrees with itself, whatever the manifest says at that moment.
"""

from __future__ import annotations

import json
import os
import struct
from datetime import date
from pathlib import Path

import numpy as np

from .encode import NODATA, SHAPE, png_to_ints
from .layers import EXTRAS, LATE_POINT_LAYERS, LAYERS

TILE = 20
NTY, NTX = SHAPE[0] // TILE, SHAPE[1] // TILE  # 18 x 36 = 648 tiles
POINT_FIELDS: tuple[str, ...] = (
    *(lid for lid in LAYERS if lid not in LATE_POINT_LAYERS),
    *EXTRAS,
    *LATE_POINT_LAYERS,
)
# The layout of the chunks published before milestone 25: a prefix of POINT_FIELDS.
LEGACY_POINT_FIELDS: tuple[str, ...] = POINT_FIELDS[: len(POINT_FIELDS) - len(LATE_POINT_LAYERS)]
SERIES_MAGIC = b"EHS1"


def tile_name(tx: int, ty: int) -> str:
    return f"{tx}_{ty}.bin"


def _tiles(stack: np.ndarray):
    """(k, 360, 720) codes -> ((tx, ty), (k, 20, 20) codes) for every tile."""
    for ty in range(NTY):
        for tx in range(NTX):
            yield (tx, ty), stack[:, ty * TILE : (ty + 1) * TILE, tx * TILE : (tx + 1) * TILE]


def point_tiles(codes: dict[str, np.ndarray]) -> dict[str, bytes]:
    """{field: (360, 720) uint16 codes} -> {tile filename: bytes} for one date."""
    unknown = set(codes) - set(POINT_FIELDS)
    if unknown:
        raise ValueError(f"not point fields: {sorted(unknown)}")
    stack = np.full((len(POINT_FIELDS), *SHAPE), NODATA, dtype="<u2")
    for k, fid in enumerate(POINT_FIELDS):
        if fid in codes:
            stack[k] = codes[fid]
    return {tile_name(tx, ty): t.tobytes() for (tx, ty), t in _tiles(stack)}


def series_header(dates: list[str]) -> bytes:
    stamps = [int(date.fromisoformat(d).strftime("%Y%m%d")) for d in dates]
    return SERIES_MAGIC + struct.pack(f"<I{len(stamps)}I", len(stamps), *stamps)


def series_tiles(dates: list[str], stack: np.ndarray) -> dict[str, bytes]:
    """Dates and their (n, 360, 720) codes for one layer -> {tile filename: bytes}."""
    if stack.shape != (len(dates), *SHAPE):
        raise ValueError(f"expected {len(dates)} x {SHAPE} codes, got {stack.shape}")
    head = series_header(dates)
    stack = stack.astype("<u2", copy=False)
    return {tile_name(tx, ty): head + t.tobytes() for (tx, ty), t in _tiles(stack)}


def read_series(data: bytes) -> tuple[list[str], np.ndarray]:
    """Series bytes -> (dates, (n, 20, 20) codes). The inverse of one `series_tiles` entry."""
    if data[:4] != SERIES_MAGIC:
        raise ValueError("not a series chunk")
    (n,) = struct.unpack_from("<I", data, 4)
    stamps = struct.unpack_from(f"<{n}I", data, 8)
    dates = [f"{s // 10000:04d}-{s // 100 % 100:02d}-{s % 100:02d}" for s in stamps]
    codes = np.frombuffer(data, dtype="<u2", offset=8 + 4 * n).reshape(n, TILE, TILE)
    return dates, codes


def _replace(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def tile_fields(data: bytes) -> tuple[str, ...]:
    """The field layout of a point chunk, from its length (current or legacy)."""
    n = len(data) // (TILE * TILE * 2)
    for layout in (POINT_FIELDS, LEGACY_POINT_FIELDS):
        if n == len(layout) and len(data) == n * TILE * TILE * 2:
            return layout
    raise ValueError(f"a point chunk of {len(data)} bytes matches no known layout")


def read_tile(data: bytes) -> dict[str, np.ndarray]:
    """Point chunk bytes -> {field: (20, 20) codes}, in whichever layout it was written."""
    layout = tile_fields(data)
    codes = np.frombuffer(data, dtype="<u2").reshape(len(layout), TILE, TILE)
    return {f: codes[k] for k, f in enumerate(layout)}


def upgrade_tile(data: bytes, codes: dict[str, np.ndarray] | None = None) -> bytes:
    """A point chunk in the current layout, with `codes` ({field: (20, 20)}) put in. Fields
    an older chunk doesn't have are no data unless given."""
    have = read_tile(data)
    stack = np.full((len(POINT_FIELDS), TILE, TILE), NODATA, dtype="<u2")
    for k, f in enumerate(POINT_FIELDS):
        if codes and f in codes:
            stack[k] = codes[f]
        elif f in have:
            stack[k] = have[f]
    return stack.tobytes()


def read_point_field(folder: Path, field: str) -> np.ndarray:
    """One field of a date's (or climate frame's) point chunks -> (360, 720) codes; no data
    where a tile is missing or doesn't have the field."""
    out = np.full(SHAPE, NODATA, dtype="<u2")
    for ty in range(NTY):
        for tx in range(NTX):
            path = folder / tile_name(tx, ty)
            if path.is_file():
                tile = read_tile(path.read_bytes())
                if field in tile:
                    out[ty * TILE : (ty + 1) * TILE, tx * TILE : (tx + 1) * TILE] = tile[field]
    return out


def patch_point_fields(folder: Path, codes: dict[str, np.ndarray]) -> int:
    """Put {field: (360, 720) codes} into every point chunk in `folder`, upgrading each to
    the current layout; each file is replaced atomically. Returns the files written."""
    unknown = set(codes) - set(POINT_FIELDS)
    if unknown:
        raise ValueError(f"not point fields: {sorted(unknown)}")
    stack = np.stack([np.asarray(codes[f], dtype="<u2") for f in codes])
    written = 0
    for (tx, ty), tile in _tiles(stack):
        path = folder / tile_name(tx, ty)
        if not path.is_file():
            continue
        _replace(path, upgrade_tile(path.read_bytes(), dict(zip(codes, tile, strict=True))))
        written += 1
    return written


def build_series(out: Path, layers: list[str] | None = None) -> int:
    """Rebuild the series of every built layer (or of `layers`) from the published PNGs.
    Returns files written.

    Each file is replaced atomically, so a reader sees either the old or the new series.
    """
    path = out / "manifest.json"
    if not path.is_file():
        return 0
    manifest = json.loads(path.read_text())
    dates: list[str] = manifest["dates"]
    written = 0
    for layer in layers if layers is not None else manifest["built_layers"]:
        stack = np.full((len(dates), *SHAPE), NODATA, dtype="<u2")
        for k, d in enumerate(dates):
            png = out / "fields" / d / f"{layer}.png"
            if png.is_file():
                stack[k] = png_to_ints(png.read_bytes())
        folder = out / "series" / layer
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in series_tiles(dates, stack).items():
            _replace(folder / name, data)
            written += 1
    return written
