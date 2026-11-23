"""Build every Uma Run background sprite: slice strips, manifest and review sheets."""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path.home() / ".cache/sprite-stacking/skills/sprite-stacking/scripts"))
try:  # review sheets use the sprite-stacking skill's renderer when it is installed
    from views_to_slices import render_stack_image, thin_runs  # noqa: E402
except ImportError:
    render_stack_image = None
    def thin_runs(vol):
        return []

from assets import all_assets  # noqa: E402
from vox import build_volume, to_strip  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
BIOMES = ["jungle", "inferno", "tundra", "highway", "sky"]


def review_row(vol, title, scale):
    frames = [render_stack_image(vol, a, squash=0.75, spacing=1.0) for a in (20, 110, 200, 290)]
    frames.append(render_stack_image(vol, 20, squash=0.75, spacing=2.4, shadow=False))
    frames = [f.resize((f.width * scale, f.height * scale), Image.NEAREST) for f in frames]
    w = sum(f.width for f in frames) + 12 * (len(frames) + 1)
    h = max(f.height for f in frames) + 30
    row = Image.new("RGB", (w, h), (238, 242, 247))
    d = ImageDraw.Draw(row)
    d.text((10, 6), title, fill=(40, 48, 60))
    x = 12
    for f in frames:
        row.paste(f, (x, 24), f)
        x += f.width + 12
    return row


def main(only=None):
    OUT.mkdir(exist_ok=True)
    (OUT / "strips").mkdir(exist_ok=True)
    (OUT / "review").mkdir(exist_ok=True)
    manifest, rows = [], {b: [] for b in BIOMES}
    for a in all_assets():
        if only and a.key not in only:
            continue
        t0 = time.time()
        vol = build_volume(a)
        n, h, w = vol.shape[:3]
        Image.fromarray(to_strip(vol)).save(OUT / "strips" / f"{a.key}.png")
        thin = thin_runs(vol)
        manifest.append(dict(key=a.key, title=a.title, biome=a.biome, file=f"strips/{a.key}.png", slices=n,
                             sliceWidth=w, sliceHeight=h, metresPerPixel=a.scale,
                             outline="#%02x%02x%02x" % a.outline))
        scale = max(2, min(5, round(150 / max(w, h, n))))
        if render_stack_image:
                rows[a.biome].append(review_row(vol, f"{a.title}  [{a.key}]  {n} slices of {w}x{h}"
                                            + (f"  THIN {thin}" if thin else ""), scale))
        print(f"{a.key:24s} {n:3d} slices {w:3d}x{h:<3d} {time.time() - t0:5.2f}s" + (f"  thin {thin}" if thin else ""))
    for b, rs in rows.items():
        if not rs:
            continue
        W = max(r.width for r in rs)
        H = sum(r.height for r in rs)
        sheet = Image.new("RGB", (W, H), (238, 242, 247))
        y = 0
        for r in rs:
            sheet.paste(r, (0, y))
            y += r.height
        sheet.save(OUT / "review" / f"{b}.png")
    if not only:
        (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
