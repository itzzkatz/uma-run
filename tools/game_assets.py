"""Gameplay sprites for Uma Run sprite mode: an original runner, the demon-monkey chasers, the obstacles ported from
the game's builders (root, barrier, idol wall, root arch, flame jet, icicle arch, river rocks) in each biome's skin,
the carrot and the inner tube. Same voxel pipeline and 0.30 m per pixel as the scenery."""
from __future__ import annotations

import math
import random

import numpy as np

from assets import (GOLD, H_CHAR, H_DARK, H_GOLD, H_GROUT, H_WALL, HW, J_DARK, J_DARK_G, OUTLINE, S, T_ICE, T_IDOL,
                    T_SNOW, W, _hash, flame, speckle, stone)
from vox import (RX, RZ, T, Asset, Builder, between, box, compose, cone, cyl, hexrgb, ico, sphere, torus)

sin, cos, PI = math.sin, math.cos, math.pi
LANE = 2.2


def mk(key, title, biome, b, ground=0.0, bounds=None, scale=S, **kw):
    return Asset(key, title, biome, scale, b.parts, ground, OUTLINE.get(biome, (36, 26, 20)), bounds=bounds, **kw)


def apply(b: Builder, G: np.ndarray):
    """Apply a global transform to every part (used for the slide pose)."""
    for p in b.parts:
        p.M = G @ p.M


# ================================================================== the runner (original design)
HAIR, HAIR_D = (150, 82, 46), (112, 58, 32)
SKIN = (255, 214, 188)
SHIRT, TRIM = (250, 251, 255), (255, 106, 168)
SHORTS = (54, 66, 128)
SHOE = (255, 106, 168)
EAR_IN = (255, 170, 190)
R_BOUNDS = ((-1.25, 0.0, -2.3), (1.25, 3.75, 2.3))


def _limb(b, a, c, r, col):
    b.add(cyl(1, 1, 1, 6), col, M=between(a, c, r))


def runner(pose="run", phase=0.0):
    b = Builder()
    sw = sin(phase * 2 * PI)  # +1: left leg forward
    for sd in (-1, 1):
        hip = (sd * 0.22, 0.98, 0.0)
        if pose == "run":
            s = sw * (1 if sd < 0 else -1)
            foot = (sd * 0.24, max(0.0, 0.32 * -s) + 0.1, 0.42 * s)
            knee = (sd * 0.23, 0.55 + 0.12 * max(0, -s), 0.18 * s + 0.12)
        elif pose == "jump":
            foot = (sd * 0.26, 0.42, 0.05 + 0.12 * sd)
            knee = (sd * 0.25, 0.78, 0.38)
        else:  # idle
            foot = (sd * 0.24, 0.1, 0.0)
            knee = (sd * 0.23, 0.55, 0.03)
        _limb(b, hip, knee, 0.17, SKIN)
        _limb(b, knee, foot, 0.15, SKIN)
        b.box(0.3, 0.2, 0.46, SHOE, foot[0], foot[1] - 0.02, foot[2] + 0.06)
        # arms swing against the legs
        sh = (sd * 0.5, 1.78, 0.0)
        if pose == "run":
            s = sw * (1 if sd > 0 else -1)
            hand = (sd * 0.58, 1.3, 0.36 * s)
        elif pose == "jump":
            hand = (sd * 0.78, 2.25, 0.1)
        else:
            hand = (sd * 0.6, 1.2, 0.0)
        _limb(b, sh, hand, 0.14, SKIN)
        b.add(sphere(1), SKIN, hand, scale=0.15)
    b.box(0.82, 0.34, 0.52, SHORTS, 0, 1.02, 0)

    def shirt(w, l, idx):
        side = np.abs(l[:, 0]) > 0.3
        top = l[:, 1] > 0.26
        c = np.where((side | top)[:, None], np.asarray(TRIM), np.asarray(SHIRT))
        return c.astype(np.uint8)
    b.box(0.86, 0.74, 0.54, shirt, 0, 1.52, 0)
    b.add(sphere(1), SKIN, (0, 2.3, 0.05), scale=0.52)                     # head
    b.add(sphere(1), HAIR, (0, 2.4, -0.1), scale=(0.57, 0.55, 0.55))       # hair, back and top
    b.box(0.84, 0.2, 0.26, HAIR, 0, 2.66, 0.3)                             # bangs
    for sd in (-1, 1):                                                     # horse ears
        b.add(cone(1, 1, 5), HAIR, (sd * 0.3, 2.9, -0.02), (0, 0, -sd * 0.28), (0.14, 0.42, 0.12))
        b.add(cone(1, 1, 5), EAR_IN, (sd * 0.3, 2.86, 0.04), (0, 0, -sd * 0.28), (0.07, 0.26, 0.05))
    _limb(b, (0, 2.55, -0.45), (0, 2.05, -0.78), 0.2, HAIR)               # ponytail
    _limb(b, (0, 2.05, -0.78), (0, 1.7, -0.86), 0.15, HAIR_D)
    wag = 0.12 * sw if pose == "run" else 0.0
    _limb(b, (0, 1.1, -0.28), (wag, 0.8, -0.85), 0.17, HAIR)              # horse tail
    _limb(b, (wag, 0.8, -0.85), (wag * 1.5, 0.5, -1.05), 0.14, HAIR_D)
    if pose == "slide":  # lean right back, feet first, low to the ground
        apply(b, T(0, 0.55, 0) @ compose(rot=(-1.15, 0, 0)) @ T(0, -0.55, 0))
    apply(b, compose(scale=1.2))  # chibi: a little larger than life so she reads at 30 cm per pixel
    return b


def runner_frames():
    out = []
    for i in range(4):
        out.append(mk(f"runner_run{i}", f"Runner run {i}", "runner", runner("run", i / 4), bounds=R_BOUNDS, shading="soft"))
    for p in ("jump", "slide", "idle"):
        out.append(mk(f"runner_{p}", f"Runner {p}", "runner", runner(p), bounds=R_BOUNDS, shading="soft"))
    return out


# ================================================================== demon monkeys (the game's MK chasers)
FUR, FUR_D, FACE, HORN, EYE = hexrgb(0x7a4590), hexrgb(0x3e2248), hexrgb(0xf0b394), hexrgb(0xff4d6a), hexrgb(0xff2a3a)
M_BOUNDS = ((-1.1, 0.0, -1.5), (1.1, 2.1, 1.5))


def monkey(phase=0):
    b = Builder()
    s = 1 if phase == 0 else -1
    k = 1.25  # a little larger than life so they read at this scale
    b.add(sphere(1), speckle(FUR, 10, 18, 2), (0, 0.78 * k, 0), (0.25, 0, 0), (0.56 * k, 0.5 * k, 0.72 * k))
    for sd in (-1, 1):
        _limb(b, (sd * 0.42 * k, 1.0 * k, 0.32 * k), (sd * 0.5 * k, 0.08, (0.42 + 0.35 * s) * k), 0.16 * k, FUR_D)
        _limb(b, (sd * 0.3 * k, 0.6 * k, -0.35 * k), (sd * 0.36 * k, 0.08, (-0.4 - 0.32 * s) * k), 0.17 * k, FUR_D)
        b.add(cone(1, 1, 5), HORN, (sd * 0.2 * k, 1.66 * k, 0.32 * k), (0, 0, -sd * 0.45), (0.1 * k, 0.36 * k, 0.1 * k))
        b.add(sphere(1), FACE, (sd * 0.43 * k, 1.3 * k, 0.3 * k), scale=0.12 * k)
    b.add(sphere(1), FUR, (0, 1.27 * k, 0.36 * k), scale=0.42 * k)          # head
    b.add(sphere(1), FACE, (0, 1.2 * k, 0.6 * k), scale=(0.3 * k, 0.26 * k, 0.2 * k))
    for sd in (-1, 1):
        b.box(0.1, 0.1, 0.06, EYE, sd * 0.12 * k, 1.3 * k, 0.8 * k, emissive=True, keep=True)
    _limb(b, (0, 0.8 * k, -0.6 * k), (0, 1.2 * k, -1.0 * k), 0.1 * k, FUR_D)  # curled tail
    _limb(b, (0, 1.2 * k, -1.0 * k), (0, 1.55 * k, -0.85 * k), 0.09 * k, FUR_D)
    return mk(f"monkey{phase}", f"Demon monkey {phase}", "monkey", b, bounds=M_BOUNDS, shading="soft")


# ================================================================== obstacles (ported from the obstacle meshes)
SKINS = {
    "jungle": dict(root=hexrgb(0xb27646), moss=hexrgb(0x7fd04a), moss_glow=False,
                   dark=stone(J_DARK, J_DARK_G, moss=True, seed=11), gold=GOLD,
                   idol=stone((150, 210, 194), (112, 170, 156), seed=12), cap=GOLD, eye=hexrgb(0xff5a2a)),
    "inferno": dict(root=H_CHAR, moss=hexrgb(0xff6a1a), moss_glow=True,
                    dark=stone(H_DARK, H_GROUT, glow=True, row=4, joint=5, seed=13, glow_share=45), gold=H_GOLD,
                    idol=stone((176, 82, 70), H_GROUT, glow=True, row=4, joint=5, seed=14, glow_share=40), cap=H_GOLD,
                    eye=hexrgb(0xffd060)),
    "tundra": dict(root=hexrgb(0x6e6470), moss=hexrgb(0xe4f6ff), moss_glow=False,
                   dark=speckle(T_ICE, 14, 22, 15), gold=speckle(T_SNOW, 8, 18, 16),
                   idol=speckle(T_IDOL, 14, 16, 17), cap=speckle(T_SNOW, 8, 18, 18), eye=hexrgb(0x7ff4ff)),
}


def root_chain(b, pts, r0, r1, col, moss, moss_glow, rng):
    for i in range(len(pts) - 1):
        a, c = pts[i], pts[i + 1]
        r = r0 + (r1 - r0) * (i / max(1, len(pts) - 2))
        L = float(np.linalg.norm(np.subtract(c, a)))
        b.add(cyl(1, 1, 1, 7), col, M=between(a, c, r, extra=r * 0.5) if L > 0 else None)
        mossy = rng.random() < 0.3
        b.add(ico(), moss if mossy else col, c, (rng.uniform(0, 3), rng.uniform(0, 3), 0), r * 1.2,
              emissive=bool(mossy and moss_glow))


def root_obstacle(skin, seed=31):
    r = random.Random(seed); b = Builder(); k = SKINS[skin]
    pts, x, i = [], -HW - 1.4, 0
    while x <= HW + 1.5:
        pts.append((x, 0.22 + 0.08 * sin(i * 2.1) + (-0.1 if abs(x) > HW else 0), 0.25 * sin(i * 1.7)))
        x += 1.3; i += 1
    root_chain(b, pts, 0.34, 0.26, k["root"], k["moss"], k["moss_glow"], r)
    p2 = [(p[0] + 0.4, 0.14, p[2] + 0.2 * cos(j * 2.3)) for j, p in enumerate(pts)][1:5]
    root_chain(b, p2, 0.16, 0.12, k["moss"], k["moss"], k["moss_glow"], r)
    return mk(f"root_{skin}", f"Root ({skin})", skin, b)


def barrier(skin, seed=32):
    r = random.Random(seed); b = Builder(); k = SKINS[skin]
    b.box(W, 0.75, 0.8, k["dark"], 0, 0.375, 0)
    x = -HW + 0.6
    while x < HW:
        b.box(0.5, 0.25, 0.9, k["gold"], x, 0.8, 0, rot=(0, r.uniform(-0.2, 0.2), 0))
        x += 1.25
    return mk(f"barrier_{skin}", f"Barrier ({skin})", skin, b)


def idol_wall(skin):
    b = Builder(); k = SKINS[skin]
    b.box(2.0, 2.9, 1.0, k["idol"], 0, 1.45, 0)
    b.box(2.3, 0.35, 1.2, k["cap"], 0, 3.05, 0)
    for e in (-0.45, 0.45):
        b.box(0.34, 0.2, 0.08, k["eye"], e, 2.1, 0.52, emissive=True, keep=True)
    b.box(1.0, 0.14, 0.08, k["eye"], 0, 1.45, 0.52, emissive=True, keep=True)
    return mk(f"idol_{skin}", f"Idol wall ({skin})", skin, b)


def root_arch(seed=33):
    r = random.Random(seed); b = Builder(); k = SKINS["jungle"]
    pts = [(-5.4, -0.2), (-4.7, 0.8), (-3.7, 1.5), (-1.9, 1.85), (0, 1.95), (1.9, 1.85), (3.7, 1.5), (4.7, 0.8), (5.4, -0.2)]
    pts = [(x, y, 0.15 * sin(i * 2)) for i, (x, y) in enumerate(pts)]
    root_chain(b, pts, 0.36, 0.3, k["root"], k["moss"], False, r)
    leaf = [0x52c83a, 0x77d94a, 0x3db23a, 0x9ce35a]
    for i in range(4):
        b.add(ico(detail=1), speckle(hexrgb(leaf[i]), 10, 20, i), ((1 if i % 2 else -1) * (HW + r.uniform(1.4, 2.5)), 2.2,
                                                                  r.uniform(-0.3, 0.3)), scale=r.uniform(0.35, 0.6) * 1.4)
    for i in range(3):
        b.add(cyl(0.045, 0.045, 1, 5), hexrgb(0x55c23c), ((1 if i % 2 else -1) * (HW + 1.1), 1.55, 0.2), scale=(1, 0.5, 1))
    return mk("root_arch", "Root arch", "jungle", b)


def flame_sheet(frame, seed=40):
    """The fire jet between the two basalt pillars (FL_LEN 7.7 m wide, centred 1.95 m up), as flickering frames."""
    r = random.Random(seed + frame); b = Builder()
    fl = 2 * (HW + 0.15)
    n = 13
    for i in range(n):
        u = (i + 0.5) / n
        d = min(u, 1 - u) * 2  # 0 at each nozzle, 1 where the jets meet
        x = (u - 0.5) * fl
        rr = 0.38 + 0.55 * d + r.uniform(-0.12, 0.12)
        b.add(sphere(1), flame(1.95 - rr, 1.95 + rr), (x, 1.95 + r.uniform(-0.15, 0.25), r.uniform(-0.15, 0.15)),
              scale=(0.55, rr, 0.45 + 0.25 * d), emissive=True)
    return mk(f"flame_jet{frame}", f"Flame jet {frame}", "inferno", b, bounds=((-fl / 2 - 0.4, 0.6, -0.9), (fl / 2 + 0.4, 3.3, 0.9)))


def icicle_arch(seed=34):
    r = random.Random(seed); b = Builder()
    span = 2 * (HW + 1.9)
    for sd in (-1, 1):
        px = sd * (HW + 1.9)
        b.add(cyl(0.95, 1.2, 8.2, 6, pre=T(0, 3.1, 0)), speckle(T_ICE, 18, 14, 20 + sd), (px, -1, 0), (0, PI / 6, 0))
        b.add(cyl(1.2, 1.05, 0.5, 6), speckle(T_SNOW, 8, 18, 22), (px, 7.3, 0), (0, PI / 6, 0))
        b.add(cone(1, 1, 5), (244, 249, 255), (px, 7.95, 0), (0, PI / 6, 0), (1.0, 1.1, 1.0))
    b.add(cyl(0.3, 0.3, 1, 7, pre=RZ(PI / 2)), (110, 100, 112), (0, 2.1, 0), scale=(span, 1, 1))
    b.add(cyl(0.27, 0.3, 1, 7, pre=compose(scale=(1, 0.55, 1)) @ RZ(PI / 2)), T_SNOW, (0, 2.36, 0), scale=(span - 0.4, 1, 1))

    def icicles(x0, x1, y, lmin, lmax, step):
        x = x0
        while x <= x1:
            l = r.uniform(lmin, lmax)
            rr = r.uniform(0.07, 0.13) * (0.7 + l * 0.4)
            b.add(cone(1, 1, 5), (223, 244, 255), (x, y - l / 2, r.uniform(-0.12, 0.12)), (PI, r.uniform(0, 3), 0), (rr, l, rr))
            x += step * r.uniform(0.75, 1.2)
    icicles(-HW - 1.3, HW + 1.3, 1.85, 0.22, 0.42, 0.6)
    b.box(span + 2.2, 0.8, 1.4, speckle(T_IDOL, 14, 16, 23), 0, 7.75, 0)
    b.box(span + 2.6, 0.35, 1.7, speckle(T_SNOW, 8, 18, 24), 0, 8.3, 0)
    icicles(-HW - 2, HW + 2, 7.35, 0.4, 1.3, 0.9)
    return mk("icicle_arch", "Icicle arch", "tundra", b)


WY = -0.55  # river water level


def river_rock(kind):
    b = Builder()
    rock, dark, moss = (180, 188, 192), (142, 154, 162), hexrgb(0x7fd04a)
    if kind == "tall":  # one lane, too tall to hop: dodge it
        hh, hw = 1.25, 0.95
        b.add(sphere(1), speckle(rock, 12, 18, 30), (0, WY + hh * 0.22, 0), (0, 0.4, 0), (hw, hh * 0.78, 0.7))
        b.add(ico(), moss, (0.05, WY + hh * 0.95, 0), scale=(hw * 0.55, 0.12, 0.4))
    else:  # low and wide: two lanes, hop over it
        hh = 0.55
        for i, x in enumerate((-1.5, 0.0, 1.5)):
            b.add(sphere(1), speckle(dark if i % 2 else rock, 12, 18, 31 + i), (x, WY + hh * 0.22, 0), (0, i, 0),
                  (0.92, hh * 0.78, 0.85))
    return mk(f"rock_{kind}", f"River rock ({kind})", "jungle", b, ground=WY)


def carrot():
    b = Builder(); k = 1.7
    tilt = compose(rot=(0, 0, 0.3))
    b.add(cone(1, 1, 8), (255, 138, 30), M=tilt @ compose((0, 0, 0), (PI, 0, 0), (0.22 * k, 0.84 * k, 0.22 * k)))
    b.add(cone(1, 1, 5), (82, 200, 58), M=tilt @ compose((0, 0.6 * k, 0), (0, 0, 0), (0.07 * k, 0.42 * k, 0.07 * k)))
    for a in (0, 2.1, 4.2):
        b.add(cone(1, 1, 5), (82, 200, 58), M=tilt @ compose((0, 0.5 * k, 0), (0, a, 0)) @ compose((0, 0, 0), (0, 0, 0.6))
              @ compose((0, 0.17 * k, 0), scale=(0.065 * k, 0.34 * k, 0.065 * k)))
    return Asset("carrot", "Carrot", "pickup", S, b.parts, None, (168, 66, 10))


def tube():
    b = Builder()

    def stripes(w, l, idx):
        ang = np.arctan2(l[:, 2], l[:, 0])
        kk = np.floor((ang + PI) / (2 * PI) * 8).astype(int) % 2
        return np.where(kk[:, None] == 0, [255, 92, 154], [255, 255, 255]).astype(np.uint8)
    b.add(torus(0.55, 0.24), stripes, (0, 0, 0))
    return Asset("tube", "Inner tube", "pickup", S, b.parts, None, (160, 40, 90))


def game_assets():
    out = runner_frames() + [monkey(0), monkey(1)]
    for sk in ("jungle", "inferno", "tundra"):
        out += [root_obstacle(sk), barrier(sk), idol_wall(sk)]
    out += [root_arch(), icicle_arch(), flame_sheet(0), flame_sheet(1), flame_sheet(2),
            river_rock("tall"), river_rock("low"), carrot(), tube()]
    return out


def end_wall_skin(skin):
    """The turn wall at each corner, re-skinned like the game's HMAP / ICEMAP."""
    from assets import _skin
    b = Builder(); sk = _skin(skin)
    b.box(W + 1.4, 5, 1.2, sk["wall"], 0, 2.5, 0)
    b.box(W + 2, 0.5, 1.6, sk["gold"], 0, 5.2, 0)
    return mk(f"end_wall_{skin}", f"Turn wall ({skin})", skin, b)


_base_game_assets = game_assets


def game_assets():  # noqa: F811
    return _base_game_assets() + [end_wall_skin("inferno"), end_wall_skin("tundra")]
