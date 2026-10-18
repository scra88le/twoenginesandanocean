"""Export the catalogue's colour scales as 256-entry RGB tables for the front end.

Run once (needs the `tools` extra) and commit the output:
    python pipeline/scripts/export_colormaps.py web/src/colormap-tables.json
"""

import json
import sys

import cmocean
import matplotlib
import numpy as np

from pipeline.layers import LAYERS


def table(name: str) -> str:
    cmap = getattr(cmocean.cm, name, None) or matplotlib.colormaps[name]
    rgb = np.rint(cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype(int)
    return "".join(f"{r:02x}{g:02x}{b:02x}" for r, g, b in rgb)


def main(out: str) -> None:
    names = sorted({s.colour for s in LAYERS.values()})
    with open(out, "w") as f:
        json.dump({n: table(n) for n in names}, f, indent=1)
        f.write("\n")
    print(f"wrote {len(names)} colour maps to {out}: {', '.join(names)}")


if __name__ == "__main__":
    main(sys.argv[1])
