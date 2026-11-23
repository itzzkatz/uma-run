"""Build the gameplay sprites (runner, monkeys, obstacles, pickups) into out/game/."""
import json
from pathlib import Path

from PIL import Image

from build import review_row
from game_assets import game_assets
from vox import build_volume, to_strip

OUT = Path(__file__).resolve().parent / "out" / "game"


def main():
    (OUT / "strips").mkdir(parents=True, exist_ok=True)
    manifest, rows = [], []
    for a in game_assets():
        vol = build_volume(a)
        n, h, w = vol.shape[:3]
        Image.fromarray(to_strip(vol)).save(OUT / "strips" / f"{a.key}.png")
        manifest.append(dict(key=a.key, title=a.title, biome=a.biome, file=f"strips/{a.key}.png", slices=n,
                             sliceWidth=w, sliceHeight=h, metresPerPixel=a.scale, outline="#%02x%02x%02x" % a.outline))
        rows.append(review_row(vol, f"{a.title} [{a.key}] {n} slices of {w}x{h}", max(2, min(6, round(120 / max(w, h, n))))))
        print(f"{a.key:16s} {n:3d} slices {w:3d}x{h:<3d}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    Wd = max(r.width for r in rows)
    sheet = Image.new("RGB", (Wd, sum(r.height for r in rows)), (238, 242, 247))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height
    sheet.save(OUT / "review.png")


if __name__ == "__main__":
    main()
