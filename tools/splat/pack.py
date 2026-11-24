"""Pack baked splat atlases into the game: splats/<key>.png (one row of view tiles) and splats.json.

Usage: python3 pack.py <game_dir> [--drop-strips]   (game_dir is the repo root: ../..)
--drop-strips removes the replaced scenery strips from the game's manifest.json so they are not downloaded.
"""
import json
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ATLAS = HERE / "atlas"


def main(game: Path, drop: bool):
    out = game / "splats"
    out.mkdir(exist_ok=True)
    entries = []
    for meta_path in sorted(ATLAS.glob("*.json")):
        m = json.loads(meta_path.read_text())
        raw = (ATLAS / f"{m['key']}.rgba").read_bytes()
        im = Image.frombytes("RGBA", (m["width"], m["height"]), raw)
        # straight alpha; snap soft edges to hard pixels so the outline pass sees a clean silhouette
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = px[x, y]
                px[x, y] = (r, g, b, 255) if a >= 128 else (0, 0, 0, 0)
        im.save(out / f"{m['key']}.png", optimize=True)
        entries.append({
            "key": m["key"], "file": f"splats/{m['key']}.png", "tileW": m["tileW"], "tileH": m["tileH"],
            "directions": m["directions"], "ax": round(m["anchor"]["x"], 2), "ay": round(m["anchor"]["y"], 2),
            "outline": m["outline"], "splats": m["splats"],
        })
    (game / "splats.json").write_text(json.dumps(entries, indent=1))
    keys = {e["key"] for e in entries}
    if drop:
        man = json.loads((game / "manifest.json").read_text())
        keep = [e for e in man if e["key"] not in keys]
        (game / "manifest.json").write_text(json.dumps(keep, indent=1))
        for e in man:
            if e["key"] in keys:
                p = game / e["file"]
                if p.exists():
                    p.unlink()
        print("manifest", len(man), "->", len(keep))
    total = sum((out / f"{k}.png").stat().st_size for k in keys)
    print(len(entries), "atlases,", round(total / 1024), "KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]), "--drop-strips" in sys.argv)
