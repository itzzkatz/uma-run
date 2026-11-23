"""Every Uma Run background asset, ported from the game's own builder code (uma-run.html).

Each function mirrors one builder (FLORA.palm, makeTree, hellDecorate, tunBuild.pine, islandGeo ...)
with the same primitives, sizes, colours and random ranges, using a seeded RNG so results are
repeatable. Gameplay obstacles and characters are not included.
"""
from __future__ import annotations

import math
import random

import numpy as np

from vox import (RX, RY, T, Asset, Builder, box, compose, cone, cyl, hemi, hexrgb, hsl, ico, lerp_rgb, sphere,
                 tint, torus)

S = 0.30  # metres per pixel for all ground scenery (jungle, Inferno, tundra, highway)
HW, W = 3.7, 7.4  # path half-width / width from the game (LANE = 2.2)
sin, cos, PI = math.sin, math.cos, math.pi

OUTLINE = {"jungle": (52, 36, 24), "inferno": (20, 6, 5), "tundra": (26, 44, 68), "highway": (36, 40, 52),
           "sky": (70, 92, 130)}

# ------------------------------------------------------------------ materials (texture x material colour)
GOLD = hexrgb(0xffc83a)
VINE = hexrgb(0x55c23c)
J_WALL, J_WALL_G = (242, 224, 184), (210, 182, 136)        # wallMat x sandstone tile / grout
J_DARK, J_DARK_G = (228, 194, 136), (194, 158, 104)        # darkMat x sandstone
MOSS = [(110, 196, 64), (160, 226, 96)]
H_WALL, H_DARK, H_GROUT = (100, 74, 70), (76, 55, 52), (255, 112, 28)
H_GROUT_DARK = (44, 28, 26)
H_GOLD, H_CHAR, H_GLOW = hexrgb(0xff8a2a), hexrgb(0x3a2622), hexrgb(0xff7a1e)
T_WALL, T_GROUT = (210, 228, 248), (156, 226, 252)
T_ICE, T_IDOL, T_SNOW, T_FLAKE = (170, 218, 250), (112, 182, 236), (244, 248, 255), hexrgb(0xbff8ff)
HW_GREY = hexrgb(0xa3abb8)


def _hash(*a):
    h = np.int64(1469598103)
    for v in a:
        h = (h ^ (np.asarray(v, np.int64) * 2654435761)) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def stone(base, grout, glow=False, moss=False, row=3, joint=4, seed=1, glow_share=100):
    """Block masonry: grout rows every `row` voxels, staggered joints, per-block brightness, moss tufts.
    With glow, `glow_share` % of the grout glows (hot cracks); the rest is dark grout."""
    def fn(w, l, idx):
        z, y, x = idx[:, 0], idx[:, 1], idx[:, 2]
        brow = z // row
        jt = ((x + y + brow * (joint // 2)) % joint) == 0
        g = ((z % row) == 0) | jt
        c = np.zeros((len(idx), 4), np.int32)
        var = (_hash(brow, (x + y + brow * (joint // 2)) // joint, seed) % 13) - 6
        c[:, :3] = np.asarray(base) + var[:, None]
        c[g, :3] = grout
        if glow:
            hot = g & ((_hash(x // 2, y // 2, z, seed + 3) % 100) < glow_share)
            c[g & ~hot, :3] = H_GROUT_DARK
            c[hot, 3] = 1
        if moss:
            m = (_hash(x, y, z, seed + 7) % 100) < 9
            c[m & ~g, :3] = MOSS[0]
            m2 = m & ((_hash(x, y, z, seed + 9) % 3) == 0)
            c[m2 & ~g, :3] = MOSS[1]
        return np.clip(c, 0, 255).astype(np.uint8)
    return fn


def speckle(base, amt=14, frac=22, seed=3):
    """Foliage / grass texture: a share of voxels nudged lighter or darker."""
    def fn(w, l, idx):
        z, y, x = idx[:, 0], idx[:, 1], idx[:, 2]
        h = _hash(x, y, z, seed) % 100
        c = np.tile(np.asarray(base, np.int32), (len(idx), 1))
        c[h < frac // 2] += amt
        c[(h >= frac // 2) & (h < frac)] -= amt
        return np.clip(c, 0, 255).astype(np.uint8)
    return fn


def bands(a, b, every=2, seed=0):
    """Alternating rings by voxel height (palm trunks, bamboo)."""
    def fn(w, l, idx):
        z = idx[:, 0]
        return np.where(((z // every) % 2 == 0)[:, None], np.asarray(a), np.asarray(b)).astype(np.uint8)
    return fn


def flame(h0, h1):
    """Flame colour by world height: white-yellow core at the base, orange, red-orange tips. Emissive."""
    def fn(w, l, idx):
        t = np.clip((w[:, 1] - h0) / max(h1 - h0, 1e-6), 0, 1)
        flick = (_hash(idx[:, 1], idx[:, 2], idx[:, 0] // 2) % 100) / 100.0
        t = np.clip(t + (flick - 0.5) * 0.18, 0, 1)
        c = np.where((t < 0.28)[:, None], [255, 236, 150],
                     np.where((t < 0.62)[:, None], [255, 160, 40], [236, 70, 20]))
        out = np.zeros((len(idx), 4), np.uint8)
        out[:, :3] = c
        out[:, 3] = 1
        return out
    return fn


def mk(key, title, biome, b, ground=0.0, scale=S, **kw):
    return Asset(key, title, biome, scale, b.parts, ground, OUTLINE[biome], **kw)


# ================================================================== JUNGLE TEMPLE  (FLORA, makeTree, temple pieces)

def palm(seed=11, k=1.0):
    r = random.Random(seed); b = Builder()
    h, lean = r.uniform(8, 13) * k, r.uniform(-0.5, 0.5)
    bark, fr = tint(0x9a7448, r), tint(0x58c23c, r)
    bark2 = tuple(max(0, c - 22) for c in bark)
    cx, cy, seg = 0.0, -6.0, 6
    for i in range(seg):
        sh = (h if i else h + 6) / seg
        b.fpart(cyl(), bands(bark, bark2, 2), cx, cy + sh / 2, 0, 0.32 * k, sh, 0.32 * k)
        cy += sh; cx += lean * 0.08
    for i in range(7):
        a = i / 7 * 6.283 + r.uniform(-0.2, 0.2)
        b.fpart(cone(), speckle(fr, 12, 20, i), cx + sin(a) * 1.7 * k, cy - 0.3, cos(a) * 1.7 * k,
                0.45 * k, 3.6 * k, 0.12 * k, cos(a) * 1.9, 0, -sin(a) * 1.9)
    b.fpart(ico(), tint(0x6b4a2a, r), cx, cy, 0, 0.5 * k, 0.5 * k, 0.5 * k)
    return mk("palm", "Palm", "jungle", b)


def broadleaf(seed=4, k=1.0):
    r = random.Random(seed); b = Builder()
    h, lf = r.uniform(5.5, 8) * k, tint(0x3fae36, r, 0.04)
    b.fpart(cyl(), tint(0x8e5e36, r), 0, (h - 8) / 2, 0, 0.5 * k, h + 8, 0.5 * k)
    for i in range(4):
        c = lf if i else tint(0x2f9a32, r)
        b.fpart(ico(detail=1), speckle(c, 12, 22, i), r.uniform(-1.6, 1.6) * k, h + r.uniform(-0.4, 1.2),
                r.uniform(-1.6, 1.6) * k, r.uniform(2, 2.4) * k, r.uniform(1.1, 1.5) * k, r.uniform(2, 2.4) * k,
                0, r.uniform(0, 3), 0)
    return mk("broadleaf", "Broadleaf tree", "jungle", b)


def bamboo(seed=5, k=1.0):
    r = random.Random(seed); b = Builder()
    g = tint(0x8fc04a, r, 0.04, 0.1)
    g2 = tuple(max(0, c - 26) for c in g)
    for i in range(5 + int(r.random() * 5)):
        bx, bz, h = r.uniform(-0.8, 0.8) * 1.7, r.uniform(-0.8, 0.8) * 1.7, r.uniform(6, 11) * k
        b.fpart(cyl(), bands(g, g2, 3), bx, (h - 4) / 2, bz, 0.11, h + 4, 0.11, r.uniform(-0.05, 0.05), 0,
                r.uniform(-0.05, 0.05))
        b.fpart(ico(), tint(0x6cc23e, r), bx, h - 1, bz, 0.45, 0.9, 0.45)
    return mk("bamboo", "Bamboo clump", "jungle", b)


def vine_tree(seed=7, k=1.0):
    r = random.Random(seed); b = Builder()
    h, lf = r.uniform(6, 9) * k, tint(0x2e8f34, r, 0.03)
    b.fpart(cyl(), tint(0x7a5232, r), 0, (h - 8) / 2, 0, 0.42 * k, h + 8, 0.42 * k)
    for i in range(3):
        b.fpart(ico(detail=1), speckle(lf, 12, 22, i), r.uniform(-1, 1) * k, h + r.uniform(0, 1),
                r.uniform(-1, 1) * k, 2.2 * k, 1.3 * k, 2.2 * k)
    for _ in range(6):
        a, rr, vl = r.uniform(0, 6.3), r.uniform(1, 2.3) * k, r.uniform(2, 4.5)
        b.fpart(cyl(), tint(0x4c9a2c, r), sin(a) * rr, h - 0.8 - vl / 2, cos(a) * rr, 0.05, vl, 0.05)
    return mk("vine_tree", "Vine tree", "jungle", b)


def fern(seed=8, k=1.0):
    r = random.Random(seed); b = Builder()
    g = tint(0x4cb83a, r, 0.05, 0.1)
    for i in range(6):  # the fan variant (the other variant is a single blob, see Shrub)
        a = i / 6 * 6.283 + r.uniform(-0.3, 0.3)
        b.fpart(cone(), g, sin(a) * 0.55 * k, 0.35 * k, cos(a) * 0.55 * k, 0.2 * k, 1.4 * k, 0.06 * k,
                cos(a) * 1.2, 0, -sin(a) * 1.2)
    return mk("fern", "Fern", "jungle", b)


def shrub(seed=9, k=1.0):
    r = random.Random(seed); b = Builder()
    g = tint(0x4aa832, r, 0.05, 0.1)
    for i in range(3):
        b.fpart(ico(), speckle(g, 12, 22, i), r.uniform(-0.8, 0.8) * k, 0.45 * k + r.uniform(0, 0.35),
                r.uniform(-0.8, 0.8) * k, r.uniform(1.1, 1.7) * k, r.uniform(0.65, 1.05) * k,
                r.uniform(1.1, 1.7) * k, 0, r.uniform(0, 3), 0)
    return mk("shrub", "Shrub", "jungle", b)


def canopy(seed=2, k=1.0):
    r = random.Random(seed); b = Builder()
    h, lf = r.uniform(11, 17) * k, tint(0x2a6b28, r, 0.04, 0.12)
    b.fpart(cyl(), tint(0x5a3e28, r, 0.02, 0.05), 0, (h - 12) / 2, 0, 0.75 * k, h + 12, 0.75 * k)
    for i in range(3):
        c = lf if i else tint(0x245a24, r, 0.03, 0.1)
        b.fpart(ico(detail=1), speckle(c, 10, 22, i), r.uniform(-2.2, 2.2) * k, h + r.uniform(-0.6, 2.2),
                r.uniform(-2.2, 2.2) * k, r.uniform(3.2, 4.8) * k, r.uniform(1.8, 2.8) * k, r.uniform(3.2, 4.8) * k,
                0, r.uniform(0, 3), 0)
    return mk("canopy", "Canopy tree", "jungle", b)


def round_tree(seed=21):
    """makeTree: tapered 8-sided trunk + 2-3 round leaf crowns (leafMats)."""
    r = random.Random(seed); b = Builder()
    leaf_cols = [0x52c83a, 0x77d94a, 0x3db23a, 0x9ce35a]
    top = r.uniform(5, 9)
    n = 2 + int(r.random() * 2)
    lv = []
    for _ in range(n):
        lx, ls, sc = r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(1.6, 2.6)
        rr = sc * 1.07
        ly = top + r.uniform(-0.5, 1.5)
        lv.append((lx, ly, ls, sc)); top = max(top, ly - rr * 0.35)
    h = top + 26
    b.add(cyl(0.35, 0.55, 1, 8), hexrgb(0xa86e40), (0, top - h / 2, 0), scale=(1, h, 1))
    for i, (lx, ly, ls, sc) in enumerate(lv):
        b.add(ico(detail=1), speckle(hexrgb(leaf_cols[int(r.random() * 4)]), 12, 22, i), (lx, ly, ls), scale=sc)
    return mk("round_tree", "Round tree", "jungle", b)


def _pillar(b, h, wall, cap, vine=True, x=0.0):
    b.box(1, h, 1, wall, x, h / 2, 0)
    if cap is not None:
        b.box(1.4, 0.35, 1.4, cap, x, h + 0.17, 0)
    if vine:
        b.add(cyl(0.045, 0.045, 1, 5), VINE, (x - 0.52, h - 0.9, 0.0), scale=(1, 1.8, 1))


def temple_pillar(skin="jungle"):
    b = Builder()
    wall, cap = _skin(skin)["wall"], _skin(skin)["gold"]
    _pillar(b, 4.4, wall, cap, vine=(skin == "jungle"))
    name = {"jungle": ("temple_pillar", "Temple pillar"), "inferno": ("inferno_pillar", "Inferno pillar"),
            "tundra": ("ice_pillar", "Frozen pillar")}[skin]
    return mk(*name, skin, b)


def broken_pillar(seed=6):
    r = random.Random(seed); b = Builder()
    h = 2.2
    b.box(1, h, 1, stone(J_WALL, J_WALL_G, moss=True), 0, h / 2, 0, rot=(0, 0, 0.1))
    for _ in range(3):
        b.add(ico(), J_DARK, (r.uniform(0.4, 2.2), 0.15, r.uniform(-1.5, 1.5)),
              (r.uniform(0, 3), r.uniform(0, 3), 0), r.uniform(0.2, 0.45) * 1.6)
    return mk("broken_pillar", "Broken pillar", "jungle", b)


def _skin(skin):
    if skin == "inferno":
        return dict(wall=stone(H_WALL, H_GROUT, glow=True, row=4, joint=5, glow_share=45), dark=stone(H_DARK, H_GROUT, glow=True, row=4, joint=5, seed=2, glow_share=45),
                    gold=H_GOLD)
    if skin == "tundra":
        return dict(wall=stone(T_WALL, T_GROUT), dark=speckle(T_ICE, 14, 24, 5), gold=speckle(T_SNOW, 8, 18, 6))
    return dict(wall=stone(J_WALL, J_WALL_G, moss=True), dark=stone(J_DARK, J_DARK_G, moss=True, seed=2), gold=GOLD)


def temple_arch(skin="jungle", seed=12):
    r = random.Random(seed); b = Builder(); sk = _skin(skin)
    px = HW + 1.3
    for s in (-1, 1):
        b.box(1.1, 5.6, 1.1, sk["wall"], s * px, 2.8, 0)
    b.box(W + 4, 0.9, 1.4, sk["dark"], 0, 6.0, 0)
    b.box(W + 4.4, 0.22, 1.6, sk["gold"], 0, 6.5, 0)
    if skin == "jungle":
        for i in range(4):
            sy = r.uniform(0.4, 0.85)
            b.add(cyl(0.045, 0.045, 1, 5), VINE, ((1 if i % 2 else -1) * (HW + 1.1), 5.55 - sy / 2,
                                                 r.uniform(-0.4, 0.4) + 0.62 * (1 if i < 2 else -1)), scale=(1, sy, 1))
    name = {"jungle": ("temple_arch", "Temple arch"), "inferno": ("inferno_arch", "Inferno arch"),
            "tundra": ("frozen_arch", "Frozen arch")}[skin]
    return mk(*name, skin, b)


def curb_post():
    b = Builder()
    b.box(0.7, 0.55, 3.0, stone(J_DARK, J_DARK_G, moss=True), 0, 0.275, 0)
    b.box(0.7, 0.8, 0.7, J_DARK, 0, 0.4, 1.85)
    b.box(0.86, 0.12, 0.86, GOLD, 0, 0.86, 1.85)
    return mk("curb_post", "Curb and corner post", "jungle", b)


def end_wall():
    b = Builder()
    b.box(W + 1.4, 5, 1.2, stone(J_WALL, J_WALL_G, moss=True), 0, 2.5, 0)
    b.box(W + 2, 0.5, 1.6, GOLD, 0, 5.2, 0)
    return mk("end_wall", "Turn wall", "jungle", b)


def inner_tubes():
    b = Builder()

    def stripes(w, l, idx):
        ang = np.arctan2(l[:, 2], l[:, 0])
        k = np.floor((ang + PI) / (2 * PI) * 8).astype(int) % 2
        return np.where(k[:, None] == 0, [255, 92, 154], [255, 255, 255]).astype(np.uint8)
    for i in range(2):
        b.add(torus(0.5, 0.21), stripes, (0.25 * i, 0.12 + 0.36 * i, 0), (0, 0, 0.1 * i))
    return mk("inner_tubes", "Inner tube pile", "jungle", b, ground=-0.1)


# ================================================================== MAMBO'S INFERNO  (hellDecorate, buildFlameGate)

def spike():
    b = Builder()
    b.add(cone(1, 1, 6, pre=T(0, 0.5, 0)), H_CHAR, (0, -0.9, 0), (0.08, 0.5, -0.06), (1.0, 5.5, 1.0))
    return mk("obsidian_spike", "Obsidian spike", "inferno", b, ground=-0.75)


def crust_rock():
    b = Builder()
    b.add(ico(), stone(H_DARK, H_GROUT, glow=True, row=2, joint=4, seed=4, glow_share=40), (0, -0.75, 0), (0, 0.6, 0), (2.0, 0.6, 1.7))
    return mk("crust_rock", "Crusted lava rock", "inferno", b, ground=-0.75)


def fire_vent():
    b = Builder()
    b.add(cyl(0.6, 1.5, 1.1, 7, pre=T(0, 0.3, 0)), stone(H_DARK, H_GROUT, glow=True, row=3, joint=5, seed=5, glow_share=50), (0, -0.75, 0))
    hgt = 0.25 + 0.5 * 8 * 0.95  # mid-eruption (the jet runs 0.25-8.25 m)
    w = 0.6 + 0.5 * 0.5
    b.add(cone(0.7, 1, 10, pre=T(0, 0.5, 0)), flame(0.05, 0.05 + hgt), (0, 0.05, 0), scale=(w, hgt, w), emissive=True)
    for dx, dz, rz, rx, hh in ((0.35, 0.15, -0.3, 0.1, 0.62), (-0.3, -0.2, 0.28, -0.12, 0.5), (0.05, 0.4, 0.05, 0.32, 0.42)):
        b.add(cone(0.7, 1, 8, pre=T(0, 0.5, 0)), flame(0.05, 0.05 + hgt), (dx, 0.05, dz), (rx, 0, rz),
              (w * 0.55, hgt * hh, w * 0.55), emissive=True)
    return mk("fire_vent", "Fire vent (erupting)", "inferno", b, ground=-0.75)


def inferno_gate():
    b = Builder()
    for s in (-1, 1):
        px = s * (HW + 2.1)
        b.box(1.9, 12, 1.9, stone(H_WALL, H_GROUT, glow=True, row=4, joint=5, glow_share=45), px, 6, 0)
        b.box(2.6, 0.7, 2.6, H_GOLD, px, 0.35, 0)
        b.add(cone(1, 1, 6, pre=T(0, 0.5, 0)), H_CHAR, (px + s * 1.2, 11.6, 0), (0, 0, -s * 0.7), (0.7, 4.2, 0.7))
        hg = 0.25 + 0.6 * 2.6
        b.add(cone(0.7, 1, 10, pre=T(0, 0.5, 0)), flame(12.05, 12.05 + hg), (px, 12.05, 0), scale=(0.9, hg, 0.9),
              emissive=True)
    b.box(W + 7, 1.6, 2.4, stone(H_DARK, H_GROUT, glow=True, row=4, joint=5, seed=3, glow_share=45), 0, 11.2, 0)
    b.box(W + 6, 0.45, 2.5, H_GLOW, 0, 10.2, 0, emissive=True)
    x = -HW - 1
    while x <= HW + 1.01:
        b.add(cone(1, 1, 6, pre=T(0, 0.5, 0)), H_CHAR, (x, 10.1, 0), (PI, 0, 0), (0.32, 1.3, 0.32))
        x += 1.35
    return mk("inferno_gate", "Inferno gate", "inferno", b)


def flame_pillar():
    b = Builder(); side = -1
    b.add(cyl(0.95, 1.2, 8.2, 6, pre=T(0, 3.1, 0)), stone(H_DARK, H_GROUT, glow=True, row=4, joint=5, seed=6, glow_share=40), (0, -1, 0), (0, PI / 6, 0))
    for y in (0.55, 4.4):
        b.add(cyl(1.02, 1.02, 0.12, 6), H_GLOW, (0, y, 0), (0, PI / 6, 0), emissive=True,
              M=compose((0, y, 0), (0, PI / 6, 0), (1.18, 1.6, 1.18)))
    b.add(cyl(1.2, 1.05, 0.5, 6), H_GOLD, (0, 7.3, 0), (0, PI / 6, 0))
    for kk in (-1, 1):
        b.add(cone(0.32, 2.3, 6, pre=T(0, 1.15, 0)), H_CHAR, (side * 0.25, 7.45, kk * 0.45), (kk * 0.45, 0, -side * 0.55))
    b.add(cyl(0.42, 0.66, 1.0, 8, pre=compose(rot=(0, 0, PI / 2))), H_CHAR, (-side * 1.25, 1.95, 0), scale=(1, 1, 1))
    b.add(cyl(1.2, 1.05, 0.5, 6), H_GOLD, (-side * 0.85, 1.95, 0), (0, 0, PI / 2))
    b.box(0.12, 0.8, 0.8, H_GLOW, -side * 1.78, 1.95, 0, emissive=True)
    return mk("flame_pillar", "Flame-jet pillar", "inferno", b)


# ================================================================== FROZEN TUNDRA  (tunBuild, tundraGate)

def pine(seed=14, k=1.0):
    r = random.Random(seed); b = Builder()
    h, tiers = r.uniform(7, 11) * k, 3 + int(r.random() * 2)
    gc, sc = tint(0x2f6e58, r, 0.03, 0.06), (244, 249, 255)
    b.fpart(ico(detail=1), speckle((240, 246, 255), 8, 18, 1), 0, -0.85, 0, 1.7 * k, 0.55, 1.7 * k)
    b.fpart(cyl(), tint(0x5a463c, r), 0, (h * 0.3 - 6) / 2, 0, 0.22 * k, h * 0.3 + 6, 0.22 * k)
    for i in range(tiers):
        u = i / tiers
        rr, th, yc, ry = (2.1 - 1.3 * u) * k, h * 0.42, h * (0.25 + 0.65 * u), r.uniform(0, 6.3)
        b.fpart(cone(), speckle(gc, 10, 20, i), 0, yc, 0, rr, th, rr, 0, ry, 0)
        b.fpart(cone(), sc, 0, yc + th * 0.2, 0, rr * 0.64, th * 0.6, rr * 0.64, 0, ry, 0)
    return mk("snowy_pine", "Snowy pine", "tundra", b, ground=-0.85)


def ice_spire(seed=15, k=1.0):
    r = random.Random(seed); b = Builder()
    n = 2 + int(r.random() * 3)
    b.fpart(ico(), speckle((234, 246, 255), 8, 18, 2), 0, -0.8, 0, 2.2 * k, 0.5, 2.2 * k, 0, r.uniform(0, 3), 0)
    for i in range(n):
        hh = (r.uniform(3, 8) if i else r.uniform(8, 15)) * k
        rr = (r.uniform(0.4, 0.8) if i else r.uniform(0.8, 1.3)) * k
        c = tint(0xbfeaff if i else 0x9fdcff, r, 0.02, 0.06)
        x = r.uniform(-1.1, 1.1) * k if i else 0
        z = r.uniform(-1.1, 1.1) * k if i else 0
        b.fpart(cone(), speckle(c, 16, 16, i + 3), x, hh / 2 - 0.9, z, rr, hh, rr, r.uniform(-0.12, 0.12),
                r.uniform(0, 6), r.uniform(-0.12, 0.12))
    return mk("ice_spire", "Ice spires", "tundra", b, ground=-0.8)


def ice_floe(seed=16, k=1.0):
    r = random.Random(seed); b = Builder()
    b.fpart(ico(), tint(0xe2f2ff, r, 0.02, 0.05), 0, -0.78, 0, r.uniform(1.2, 2.5) * k, r.uniform(0.2, 0.35),
            r.uniform(1.2, 2.5) * k, 0, r.uniform(0, 3), 0)
    b.fpart(ico(), tint(0xc4e6fa, r), r.uniform(-0.5, 0.5), -0.3, r.uniform(-0.5, 0.5), r.uniform(0.5, 0.9) * k,
            r.uniform(0.5, 1.0) * k, r.uniform(0.5, 0.9) * k, r.uniform(0, 3), r.uniform(0, 3), 0)
    return mk("ice_floe", "Ice floe", "tundra", b, ground=-0.78)


def _icicles(b, r, x0, x1, y, z, lmin, lmax, step):
    x = x0
    while x <= x1 + 1e-6:
        l = r.uniform(lmin, lmax)
        rr = r.uniform(0.07, 0.13) * (0.7 + l * 0.4)
        b.fpart(cone(), tint(0xdff4ff, r, 0.02, 0.05), x, y - l / 2, z + r.uniform(-0.12, 0.12), rr, l, rr,
                PI, r.uniform(0, 3), 0)
        x += step * r.uniform(0.75, 1.2)


def tundra_gate(seed=17):
    r = random.Random(seed); b = Builder()
    for s in (-1, 1):
        px = s * (HW + 2.1)
        b.add(cyl(0.95, 1.15, 12, 6, pre=T(0, 6, 0)), speckle(T_ICE, 18, 14, 4 + s), (px, 0, 0), (0, PI / 6, 0))
        b.box(2.6, 0.7, 2.6, speckle(T_SNOW, 8, 18, 6), px, 0.35, 0)
        _icicles(b, r, px - 0.8, px + 0.8, 10.2, 1.05, 0.5, 1.6, 0.84)  # every other icicle so each one reads
    b.box(W + 7, 2.0, 2.4, speckle(T_IDOL, 14, 16, 7), 0, 11.4, 0)
    b.box(W + 7.6, 0.55, 2.8, speckle(T_SNOW, 8, 18, 8), 0, 12.6, 0)
    for a in (0, PI / 3, -PI / 3):
        b.add(box(1.7, 0.16, 0.08), T_FLAKE, (0, 11.4, 1.26), (0, 0, a), emissive=True, keep=True)
    _icicles(b, r, -HW - 3, HW + 3, 10.4, 0.9, 0.5, 2.0, 1.1)
    return mk("tundra_gate", "Tundra gate", "tundra", b)


# ================================================================== HIGHWAY DASH  (hwSegment scenery)

def _sign_face(bg=(31, 122, 74), seed=0, back=(20, 83, 47)):
    """The hwSignTex board at pixel scale: white border, a white line of 'letters', a yellow second line.
    Painted on the front half of a two-voxel board; the back half is the plain green backing."""
    def fn(w, l, idx):
        lx, ly = l[:, 0], l[:, 1]
        x = idx[:, 2]
        c = np.tile(np.asarray(bg, np.int32), (len(idx), 1))
        border = (np.abs(lx) > 3.3 - 0.32) | (np.abs(ly) > 1.135 - 0.3)
        line1 = (ly > 0.05) & (ly < 0.7) & (np.abs(lx) < 2.4) & ((_hash(x // 1, seed) % 5) != 0)
        line2 = (ly < -0.3) & (ly > -0.68) & (np.abs(lx) < 1.8) & ((x % 3) != 0)
        c[line1] = (255, 255, 255)
        c[line2] = (255, 226, 122)
        c[border] = (255, 255, 255)
        c[l[:, 2] < 0] = back
        return c.astype(np.uint8)
    return fn


def road_sign():
    b = Builder()
    for dx in (-2.4, 2.4):
        b.box(0.24, 6.0, 0.24, HW_GREY, dx, 3.0, 0)
    b.box(6.8, 2.45, 2 * S, _sign_face(seed=1), 0, 4.9, 0)
    return mk("road_sign", "Road sign", "highway", b)


def lamp_post():
    b = Builder()
    b.box(0.22, 7.6, 0.22, HW_GREY, 0, 3.8, 0)
    b.box(2.8, 0.16, 0.16, HW_GREY, -1.35, 7.5, 0)
    b.box(0.7, 0.18, 0.5, hexrgb(0xfff6c8), -2.45, 7.36, 0, emissive=True)
    return mk("lamp_post", "Lamp post", "highway", b)


def gantry():
    b = Builder(); px = HW + 1.25
    for x in (-px, px):
        b.box(0.5, 8.1, 0.5, hexrgb(0x8d99ad), x, 4.05, 0)
        b.box(0.9, 0.3, 0.9, hexrgb(0x6b7689), x, 0.15, 0)
    b.box(px * 2 + 0.5, 0.5, 0.5, hexrgb(0x8d99ad), 0, 7.85, 0)
    b.box(7.0, 2.4, 2 * S, _sign_face(seed=2), 0, 6.2, 0.05 + S)
    return mk("sign_gantry", "Sign gantry", "highway", b)


def guardrail(length=9.0):
    b = Builder(); rail = hexrgb(0xc8cfda)
    b.box(0.1, 0.32, length, rail, 0, 0.62, 0)
    b.box(0.12, 0.06, length, (176, 184, 198), 0.02, 0.44, 0)
    p = -length / 2 + 0.2
    while p < length / 2 - 0.1:
        b.box(0.14, 0.78, 0.14, (150, 158, 172), 0.09, 0.39, p)
        p += 3
    for e in (-1, 1):
        b.box(0.16, 0.4, 0.5, rail, 0.05, 0.55, e * (length / 2 - 0.25))
    return mk("guardrail", "Guardrail", "highway", b)


def hill():
    b = Builder()
    b.add(hemi(1), speckle(hexrgb(0x82d65a), 12, 18, 9), (0, -0.2, 0), scale=(8, 4.5, 13))
    return mk("rolling_hill", "Rolling hill", "highway", b)


def bush():
    b = Builder(); rr = 1.2
    b.add(sphere(1), speckle(hexrgb(0x6cc04f), 14, 24, 10), (0, rr * 0.45, 0), scale=(rr, rr * 0.8, rr))
    return mk("bush", "Bush", "highway", b)


# ================================================================== SKY  (cel clouds, floating islands)

def cloud(seed=19):
    r = random.Random(seed); b = Builder()
    n, sc = 5 + int(r.random() * 4), r.uniform(9, 16)
    for kk in range(n):
        x = (kk - n / 2) * sc * 0.75 + r.uniform(-3, 3)
        s = sc * r.uniform(0.7, 1.25) * (1 - abs(kk - n / 2) / n * 0.8)
        y = s * 0.35 + r.uniform(-1, 2)
        zd = r.uniform(-0.45, 0.45) * sc  # depth spread (sprite only) so it reads round from every side
        b.add(sphere(1), hexrgb(0xc6defa), (x + s * 0.08, y - s * 0.22, zd + 1.5), scale=(s * 1.02, s * 0.7, s * 0.6))
        b.add(sphere(1), (255, 255, 255), (x, y, zd), scale=(s, s * 0.85, s * 0.85))
    return Asset("cloud", "Cel cloud", "sky", 1.6, b.parts, None, OUTLINE["sky"], shading="soft")


ISLAND_NAMES = ["Floating island", "Waterfall island", "Torii island", "Ruins island", "Vine island",
                "Waterfall vine island", "Ruined vine island"]


def island(kind, seed=None):
    r = random.Random(100 + kind if seed is None else seed); b = Builder()
    ph = [r.uniform(0, 6.3), r.uniform(0, 6.3)]
    n = 7 + int(r.random() * 5)

    def wob(x, z):
        a = np.arctan2(z, x)
        return 1 + 0.13 * np.sin(a * 3 + ph[0]) + 0.07 * np.sin(a * 5 + ph[1])

    def wobs(a):
        return float(wob(np.array([cos(a)]), np.array([sin(a)]))[0])

    grass = hsl(r.uniform(0.22, 0.3), r.uniform(0.45, 0.6), r.uniform(0.42, 0.5))
    dirt, rockA, rockB = hexrgb(0x8a6a48), hexrgb(0xa88a6a), hexrgb(0x6a5a66)
    depth = r.uniform(1.1, 1.9)
    gtex = speckle(grass, 12, 20, kind)

    def top_col(w, l, idx):
        g = gtex(w, l, idx)
        return np.where((w[:, 1] > 0.1)[:, None], g, np.asarray(dirt)).astype(np.uint8)

    def rock_col(w, l, idx):
        t = np.clip(1 + w[:, 1] / depth, 0, 1)
        c = lerp_rgb(rockB, rockA, t).astype(np.int32)
        h = _hash(idx[:, 0], idx[:, 1], idx[:, 2], kind) % 100
        c[h < 10] += 12
        c[(h >= 10) & (h < 20)] -= 12
        return np.clip(c, 0, 255).astype(np.uint8)

    b.add(cyl(1, 0.94, 0.3, n, pre=T(0, 0.12, 0)), top_col, wob=wob)
    b.add(cone(0.95, depth, n, pre=T(0, -depth / 2, 0) @ RX(PI)), rock_col, wob=wob)
    if kind != 3:
        for _ in range(2 + int(r.random() * 4)):
            a, rr = r.uniform(0, 6.3), r.uniform(0, 0.62)
            x, z, h = cos(a) * rr, sin(a) * rr, r.uniform(0.16, 0.3)
            leaf = hsl(r.uniform(0.25, 0.36), 0.5, r.uniform(0.26, 0.36))
            b.add(cyl(0.018, 0.026, h, 4), hexrgb(0x6b4a30), (x, 0.24 + h / 2, z))
            b.add(cone(r.uniform(0.08, 0.13), r.uniform(0.2, 0.34), 5), speckle(leaf, 10, 20, 1), (x, 0.24 + h + 0.08, z))
    if kind in (1, 5):
        a = r.uniform(0, 6.3); rr = 0.9 * wobs(a)

        def water(w, l, idx):
            return lerp_rgb(hexrgb(0xd8f0ff), hexrgb(0x8cc8f0), np.clip(-w[:, 1] / depth, 0, 1))
        b.add(box(0.16, depth * 1.2, 0.02), water,
              M=compose((cos(a) * (rr + 0.04), 0.2 - depth * 0.6, sin(a) * (rr + 0.04)), (0, -a + PI / 2, 0)))
        b.add(cyl(0.1, 0.1, 0.04, 6), hexrgb(0x7cc4ee), (cos(a) * rr * 0.75, 0.27, sin(a) * rr * 0.75), keep=True)
    if kind == 2:
        red = hexrgb(0xd8402a)
        for s in (-1, 1):
            b.add(cyl(0.025, 0.03, 0.42, 5), red, (s * 0.16, 0.45, 0.1))
        b.box(0.5, 0.05, 0.06, hexrgb(0x2a2220), 0, 0.68, 0.1)
        b.box(0.42, 0.035, 0.045, red, 0, 0.6, 0.1)
    if kind in (3, 6):
        for i in range(4):
            a, h = i / 4 * 6.3 + r.uniform(-0.3, 0.3), r.uniform(0.12, 0.42)
            b.add(cyl(0.045, 0.05, h, 6), hexrgb(0xcfc6b8), (cos(a) * 0.4, 0.24 + h / 2, sin(a) * 0.4))
    if kind == 3:
        b.add(box(0.5, 0.06, 0.3), hexrgb(0xb8ae9e), M=compose((0, 0.28, 0), (0, 0.4, 0)))
    if kind in (4, 5, 6):
        for _ in range(5 + int(r.random() * 5)):
            a = r.uniform(0, 6.3); rr = 0.86 * wobs(a); L = r.uniform(0.3, 0.9)

            def vcol(w, l, idx):
                return lerp_rgb(hexrgb(0x3f7a34), hexrgb(0x6aa84a), np.clip(-w[:, 1], 0, 1))
            b.add(box(0.03, L, 0.03), vcol, M=compose((cos(a) * rr, 0.02 - L / 2, sin(a) * rr), (0, -a, 0)))
    keys = ["island_plain", "island_waterfall", "island_torii", "island_ruins", "island_vines",
            "island_waterfall_vines", "island_ruins_vines"]
    return Asset(keys[kind], ISLAND_NAMES[kind], "sky", 0.06, b.parts, None, OUTLINE["sky"])


# ================================================================== registry

def all_assets():
    return [
        palm(), broadleaf(), bamboo(), vine_tree(), canopy(), round_tree(), fern(), shrub(),
        temple_pillar("jungle"), broken_pillar(), temple_arch("jungle"), end_wall(), curb_post(), inner_tubes(),
        spike(), crust_rock(), fire_vent(), flame_pillar(), inferno_gate(), temple_pillar("inferno"),
        temple_arch("inferno"),
        pine(), ice_spire(), ice_floe(), tundra_gate(), temple_pillar("tundra"), temple_arch("tundra"),
        road_sign(), lamp_post(), gantry(), guardrail(), hill(), bush(),
        cloud(), *[island(k) for k in range(7)],
    ]
