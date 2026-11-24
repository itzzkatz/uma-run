"""Turn baked view atlases into PNGs and a review sheet (8 of the 32 views per asset)."""
import json
import sys
from pathlib import Path

from PIL import Image

D = Path(__file__).resolve().parent / "atlas"


def load(key):
    m = json.loads((D / f"{key}.json").read_text())
    im = Image.frombytes("RGBA", (m["width"], m["height"]), (D / f"{key}.rgba").read_bytes())
    return m, im


def main(keys, scale=3, every=4, out="/tmp/splat_review.png"):
    rows = []
    for k in keys:
        m, im = load(k)
        im.save(D / f"{k}.png")
        tw, th = m["tileW"], m["tileH"]
        cells = [im.crop((d * tw, 0, (d + 1) * tw, th)) for d in range(0, m["directions"], every)]
        row = Image.new("RGBA", (len(cells) * (tw + 4) * scale, (th + 4) * scale), (236, 240, 246, 255))
        for i, c in enumerate(cells):
            bg = Image.new("RGBA", c.size, (236, 240, 246, 255)); bg.alpha_composite(c)
            ax, ay = round(m["anchor"]["x"]), round(m["anchor"]["y"])
            if 0 <= ay < th:
                for x in range(max(0, ax - 2), min(tw, ax + 3)):
                    bg.putpixel((x, ay), (255, 0, 120, 255))
            row.paste(bg.resize((tw * scale, th * scale), Image.NEAREST), (i * (tw + 4) * scale, 2 * scale))
        rows.append(row)
    W = max(r.width for r in rows); H = sum(r.height for r in rows)
    sheet = Image.new("RGBA", (W, H), (255, 255, 255, 255)); y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height
    sheet.save(out); print(sheet.size, out)


if __name__ == "__main__":
    main(sys.argv[1:])
