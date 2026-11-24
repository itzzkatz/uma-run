"""Export the game's background assets as primitive lists (kind, size, frame, colour) for ink-studio.

Each part keeps the game's exact transform. Colour functions (stone tiles, speckle, bands, gradients) are sampled
to a base colour, plus a style hint so the splat build can add its own texture.
"""
import json
import random
import sys
from pathlib import Path

import numpy as np

import assets as A
import game_assets as G

BACKGROUND = [
    A.palm, A.broadleaf, A.bamboo, A.vine_tree, A.canopy, A.round_tree, A.fern, A.shrub,
    lambda: A.temple_pillar("jungle"), A.broken_pillar, lambda: A.temple_arch("jungle"), A.end_wall, A.inner_tubes,
    A.spike, A.crust_rock, A.fire_vent, A.inferno_gate, lambda: A.temple_pillar("inferno"),
    lambda: A.temple_arch("inferno"), lambda: G.end_wall_skin("inferno"),
    A.pine, A.ice_spire, A.ice_floe, A.tundra_gate, lambda: A.temple_pillar("tundra"),
    lambda: A.temple_arch("tundra"), lambda: G.end_wall_skin("tundra"),
    *[(lambda k=k: A.island(k)) for k in range(7)],
]

# tag the colour factories so exported parts carry a texture hint
for mod in (A, G):
    for name in ("stone", "speckle", "bands", "flame"):
        orig = getattr(A, name)

        def tagged(*a, _orig=orig, _name=name, **k):
            fn = _orig(*a, **k)
            fn.style = _name
            fn.base = tuple(int(c) for c in a[0]) if _name != "flame" else (255, 160, 40)
            if _name == "stone":
                fn.grout = tuple(int(c) for c in a[1])
                fn.glow = bool(k.get("glow", False))
            if _name == "bands":
                fn.alt = tuple(int(c) for c in a[1])
            return fn
        setattr(mod, name, tagged)


def sample_colour(part):
    """Median colour of a colour function sampled inside the part."""
    rng = np.random.default_rng(1)
    lo, hi = part.geo.local_bbox()
    q = rng.uniform(lo, hi, size=(200, 3))
    inside = part.geo.inside(q)
    q = q[inside] if inside.sum() > 8 else q
    Mw = part.M @ part.geo.pre
    w = (Mw[:3, :3] @ q.T).T + Mw[:3, 3]
    idx = rng.integers(0, 50, size=(len(q), 3))
    c = np.asarray(part.color(w, q, idx), float).reshape(len(q), -1)
    em = c.shape[1] == 4 and (c[:, 3] > 0).mean() > 0.5
    # gradients (island rock, water, vines): keep the top and bottom colours too
    order = np.argsort(w[:, 1])
    lo_c, hi_c = c[order[: max(1, len(q) // 5)], :3].mean(0), c[order[-max(1, len(q) // 5):], :3].mean(0)
    return np.median(c[:, :3], 0), em, lo_c, hi_c


def export(asset):
    parts = []
    for p in asset.parts:
        Mw = p.M @ p.geo.pre
        entry = dict(kind=p.geo.kind, p=p.geo.p, A=Mw[:3, :3].round(6).tolist(), t=Mw[:3, 3].round(6).tolist(),
                     emissive=bool(p.emissive))
        if callable(p.color):
            base, em, lo_c, hi_c = sample_colour(p)
            entry["color"] = [int(round(v)) for v in base]
            entry["style"] = getattr(p.color, "style", "sampled")
            entry["emissive"] = entry["emissive"] or bool(em)
            if getattr(p.color, "style", None) == "stone":
                entry["color"] = list(p.color.base)
                entry["grout"] = list(p.color.grout)
                entry["glow"] = p.color.glow
            elif getattr(p.color, "style", None) == "bands":
                entry["color"] = list(p.color.base)
                entry["alt"] = list(p.color.alt)
            if np.abs(lo_c - hi_c).max() > 24:
                entry["grad"] = [[int(v) for v in lo_c], [int(v) for v in hi_c]]
        else:
            entry["color"] = [int(c) for c in p.color]
        parts.append(entry)
    return dict(key=asset.key, title=asset.title, biome=asset.biome, scale=asset.scale, ground=asset.ground,
                outline="#%02x%02x%02x" % asset.outline, parts=parts)


def main():
    out = Path(__file__).resolve().parent / "splat" / "parts"
    out.mkdir(parents=True, exist_ok=True)
    keys = []
    for f in BACKGROUND:
        a = f()
        (out / f"{a.key}.json").write_text(json.dumps(export(a)))
        keys.append(a.key)
    print(len(keys), "assets:", " ".join(keys))


if __name__ == "__main__":
    main()
