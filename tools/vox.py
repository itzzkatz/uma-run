"""Voxelize Uma Run scenery into sprite-stacking slice volumes.

The game builds its scenery from three.js primitives (n-sided cylinders and cones, icosahedron
blobs, boxes, tori). This module rebuilds those primitives with the same transforms
(position, Euler XYZ rotation, scale, plus geometry pre-transforms), samples them on a voxel
grid, applies a rotation-invariant toon ramp, and returns a volume [z, y, x, rgba] with z = 0
on the ground, ready to save as a horizontal slice strip.

Axes: three.js x -> volume x, three.js y (up) -> slice z, three.js z -> volume y (+z = toward
the camera, which is "front pointing down" in the strip's top view).
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

# ------------------------------------------------------------------ transforms (three.js rules)


def rot_xyz(rx: float, ry: float, rz: float) -> np.ndarray:
    """three.js Euler order 'XYZ': R = Rx * Ry * Rz."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rx @ Ry @ Rz


def compose(pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> np.ndarray:
    if np.isscalar(scale):
        scale = (scale, scale, scale)
    M = np.eye(4)
    M[:3, :3] = rot_xyz(*rot) @ np.diag(scale)
    M[:3, 3] = pos
    return M


def between(a, b, r_scale_x, r_scale_z=None, extra=0.0) -> np.ndarray:
    """Matrix for a unit cylinder (height 1, along +y) stretched from point a to point b (Object3D quaternion.setFromUnitVectors(UP, d))."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    L = float(np.linalg.norm(d)) + extra
    u = d / max(np.linalg.norm(d), 1e-9)
    up = np.array([0.0, 1.0, 0.0])
    v = np.cross(up, u)
    c = float(np.dot(up, u))
    if np.linalg.norm(v) < 1e-9:
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * (1 / (1 + c))
    M = np.eye(4)
    M[:3, :3] = R @ np.diag([r_scale_x, L, r_scale_z if r_scale_z is not None else r_scale_x])
    M[:3, 3] = (a + b) / 2
    return M


def T(x=0.0, y=0.0, z=0.0) -> np.ndarray:
    return compose((x, y, z))


def RX(a: float) -> np.ndarray:
    return compose(rot=(a, 0, 0))


def RY(a: float) -> np.ndarray:
    return compose(rot=(0, a, 0))


def RZ(a: float) -> np.ndarray:
    return compose(rot=(0, 0, a))


# ------------------------------------------------------------------ geometry


@dataclass
class Geo:
    """A unit primitive in its own geometry space, optionally pre-transformed (geometry.translate etc.)."""

    kind: str  # cyl | cone | sph | hemi | box | torus
    p: dict
    pre: np.ndarray = field(default_factory=lambda: np.eye(4))

    def local_bbox(self):
        k, p = self.kind, self.p
        if k in ("cyl", "cone"):
            r = max(p.get("rt", 0.0), p.get("rb", p.get("r", 0.0)), p.get("r", 0.0))
            h = p["h"] / 2
            return np.array([-r, -h, -r]), np.array([r, h, r])
        if k in ("sph", "hemi"):
            r = p["r"]
            return np.array([-r, 0 if k == "hemi" else -r, -r]), np.array([r, r, r])
        if k == "box":
            e = np.array([p["w"], p["h"], p["d"]]) / 2
            return -e, e
        if k == "torus":
            R, t = p["R"] + p["t"], p["t"]
            return np.array([-R, -t, -R]), np.array([R, t, R])
        raise ValueError(k)

    def inside(self, q: np.ndarray) -> np.ndarray:
        """q: (N, 3) points in geometry space (before `pre`). Returns a bool mask."""
        x, y, z = q[:, 0], q[:, 1], q[:, 2]
        k, p = self.kind, self.p
        if k in ("cyl", "cone"):
            h, n = p["h"], p["n"]
            if k == "cone":
                rt, rb = 0.0, p["r"]
            else:
                rt, rb = p["rt"], p["rb"]
            t = y / h + 0.5
            r = rb + (rt - rb) * t
            phis = (np.arange(n) + 0.5) * 2 * math.pi / n
            proj = x[:, None] * np.sin(phis)[None] + z[:, None] * np.cos(phis)[None]
            return (t >= 0) & (t <= 1) & (proj.max(1) <= r * math.cos(math.pi / n))
        if k == "sph":
            return x * x + y * y + z * z <= p["r"] ** 2
        if k == "hemi":
            return (y >= 0) & (x * x + y * y + z * z <= p["r"] ** 2)
        if k == "box":
            return (np.abs(x) <= p["w"] / 2) & (np.abs(y) <= p["h"] / 2) & (np.abs(z) <= p["d"] / 2)
        if k == "torus":
            d = np.sqrt(x * x + z * z) - p["R"]
            return d * d + y * y <= p["t"] ** 2
        raise ValueError(k)


# three.js primitives used by the game, with blob radii for the faceted solids:
# an icosahedron / dodecahedron of circumradius 1 averages ~0.87 (detail 0) or ~0.95 (detail 1).
def cyl(rt=1.0, rb=1.0, h=1.0, n=6, pre=None) -> Geo:
    return Geo("cyl", dict(rt=rt, rb=rb, h=h, n=n), np.eye(4) if pre is None else pre)


def cone(r=1.0, h=1.0, n=5, pre=None) -> Geo:
    return Geo("cone", dict(r=r, h=h, n=n), np.eye(4) if pre is None else pre)


def ico(r=1.0, detail=0, pre=None) -> Geo:
    return Geo("sph", dict(r=r * (0.87 if detail == 0 else 0.95)), np.eye(4) if pre is None else pre)


def sphere(r=1.0, pre=None) -> Geo:
    return Geo("sph", dict(r=r), np.eye(4) if pre is None else pre)


def hemi(r=1.0, pre=None) -> Geo:
    return Geo("hemi", dict(r=r), np.eye(4) if pre is None else pre)


def box(w, h, d, pre=None) -> Geo:
    return Geo("box", dict(w=w, h=h, d=d), np.eye(4) if pre is None else pre)


def torus(R, t, pre=None) -> Geo:
    return Geo("torus", dict(R=R, t=t), np.eye(4) if pre is None else pre)


# ------------------------------------------------------------------ colours


def hexrgb(h: int) -> tuple[int, int, int]:
    return ((h >> 16) & 255, (h >> 8) & 255, h & 255)


def tint(hexc: int, rng, h=0.03, l=0.08) -> tuple[int, int, int]:
    """Port of the game's tint(): offsetHSL(rand(-h,h), rand(-.08,.08), rand(-l,l))."""
    r, g, b = (c / 255 for c in hexrgb(hexc))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    hh = (hh + rng.uniform(-h, h)) % 1.0
    ss = min(1, max(0, ss + rng.uniform(-0.08, 0.08)))
    ll = min(1, max(0, ll + rng.uniform(-l, l)))
    return tuple(int(round(c * 255)) for c in colorsys.hls_to_rgb(hh, ll, ss))


def hsl(hh, ss, ll) -> tuple[int, int, int]:
    return tuple(int(round(c * 255)) for c in colorsys.hls_to_rgb(hh % 1.0, ll, ss))


def lerp_rgb(a, b, t):
    t = np.clip(np.asarray(t, float), 0, 1)[..., None]
    return (np.asarray(a, float) * (1 - t) + np.asarray(b, float) * t).astype(np.uint8)


# ------------------------------------------------------------------ parts and assets

ColourFn = Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray]


@dataclass
class Part:
    geo: Geo
    M: np.ndarray
    color: tuple | ColourFn  # rgb, or fn(world_xyz, local_xyz, voxel_zyx) -> (N, 3) uint8
    emissive: bool = False  # skip shading (glow, flames, lamps)
    wob: Callable | None = None
    keep: bool = False  # never overwritten by later parts (painted details on faces)


@dataclass
class Asset:
    key: str
    title: str
    biome: str
    scale: float  # metres (world units) per voxel
    parts: list[Part]
    ground: float | None = 0.0  # world y of the ground; voxels below are cut
    outline: tuple = (36, 26, 20)
    shading: str = "toon"  # toon | soft (clouds)
    note: str = ""
    bounds: tuple | None = None  # fixed (lo, hi) world box so animation frames share size and pivot


class Builder:
    """Collects parts the way the game's addMesh / addBox / fPart calls do."""

    def __init__(self):
        self.parts: list[Part] = []

    def add(self, geo: Geo, color, pos=(0, 0, 0), rot=(0, 0, 0), scale=1.0, M=None, **kw) -> Part:
        Mw = compose(pos, rot, scale) if M is None else M
        part = Part(geo, Mw, color, **kw)
        self.parts.append(part)
        return part

    def box(self, w, h, d, color, x, y, z, rot=(0, 0, 0), **kw) -> Part:  # addBox / hwBox
        return self.add(box(w, h, d), color, (x, y, z), rot, **kw)

    def fpart(self, geo, color, x, y, z, sx, sy, sz, rx=0.0, ry=0.0, rz=0.0, **kw) -> Part:  # fPart
        return self.add(geo, color, (x, y, z), (rx, ry, rz), (sx, sy, sz), **kw)


# ------------------------------------------------------------------ voxelization

_SUB = np.array([[dx, dy, dz] for dx in (-0.25, 0.25) for dy in (-0.25, 0.25) for dz in (-0.25, 0.25)])


def _part_world(part: Part) -> np.ndarray:
    return part.M @ part.geo.pre


def _part_aabb(part: Part):
    lo, hi = part.geo.local_bbox()
    corners = np.array([[x, y, z, 1] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    w = (_part_world(part) @ corners.T).T[:, :3]
    return w.min(0), w.max(0)


def _thin(part: Part, s: float) -> bool:
    lo, hi = part.geo.local_bbox()
    Mw = _part_world(part)
    ext = (hi - lo) * np.linalg.norm(Mw[:3, :3], axis=0)
    return bool(ext.min() < 2.2 * s)


def voxelize(asset: Asset) -> tuple[np.ndarray, np.ndarray]:
    """Return (rgb volume [z,y,x,3] uint8, flags [z,y,x] int8: 0 empty, 1 solid, 2 emissive)."""
    s = asset.scale
    boxes = [_part_aabb(p) for p in asset.parts]
    lo = np.min([b[0] for b in boxes], 0)
    hi = np.max([b[1] for b in boxes], 0)
    if asset.bounds is not None:
        lo, hi = np.array(asset.bounds[0], float), np.array(asset.bounds[1], float)
    if asset.ground is not None:
        lo[1] = max(lo[1], asset.ground)
    # grid: world x -> ix, world z -> iy, world y -> iz
    nx = int(math.ceil((hi[0] - lo[0]) / s)) + 2
    ny = int(math.ceil((hi[2] - lo[2]) / s)) + 2
    nz = int(math.ceil((hi[1] - lo[1]) / s)) + 1
    ox, oy, oz = lo[0] - s, lo[2] - s, lo[1]
    col = np.zeros((nz, ny, nx, 3), np.uint8)
    flag = np.zeros((nz, ny, nx), np.int8)
    keep = np.zeros((nz, ny, nx), bool)
    pid = np.full((nz, ny, nx), -1, np.int16)

    for pi, part in enumerate(asset.parts):
        plo, phi = _part_aabb(part)
        x0, x1 = max(0, int((plo[0] - ox) / s) - 1), min(nx, int((phi[0] - ox) / s) + 2)
        y0, y1 = max(0, int((plo[2] - oy) / s) - 1), min(ny, int((phi[2] - oy) / s) + 2)
        z0, z1 = max(0, int((plo[1] - oz) / s) - 1), min(nz, int((phi[1] - oz) / s) + 2)
        if x0 >= x1 or y0 >= y1 or z0 >= z1:
            continue
        iz, iy, ix = np.meshgrid(np.arange(z0, z1), np.arange(y0, y1), np.arange(x0, x1), indexing="ij")
        idx = np.stack([iz.ravel(), iy.ravel(), ix.ravel()], 1)
        centre = np.stack([ox + (idx[:, 2] + 0.5) * s, oz + (idx[:, 0] + 0.5) * s, oy + (idx[:, 1] + 0.5) * s], 1)
        inv = np.linalg.inv(_part_world(part))
        thin = _thin(part, s)
        cover = np.zeros(len(centre))
        for off in _SUB:
            pts = centre + off * s
            if part.wob is not None:  # island rim jitter, applied in asset space like the game's add(..., jitter)
                f = part.wob(pts[:, 0], pts[:, 2])
                pts = pts.copy()
                pts[:, 0] /= f
                pts[:, 2] /= f
            q = (inv[:3, :3] @ pts.T).T + inv[:3, 3]
            cover += part.geo.inside(q)
        solid = cover > 0 if thin else cover >= 4
        if asset.ground is not None:
            solid &= centre[:, 1] >= asset.ground
        if not solid.any():
            continue
        sel = idx[solid]
        free = ~keep[sel[:, 0], sel[:, 1], sel[:, 2]]
        sel = sel[free]
        if not len(sel):
            continue
        wc = centre[solid][free]
        if callable(part.color):
            Mi = inv
            lq = (Mi[:3, :3] @ wc.T).T + Mi[:3, 3]
            c = np.asarray(part.color(wc, lq, sel), np.uint8)
            c = c.reshape(len(sel), -1)
        else:
            c = np.broadcast_to(np.asarray(part.color, np.uint8), (len(sel), 3))
        col[sel[:, 0], sel[:, 1], sel[:, 2]] = c[:, :3]
        f = np.full(len(sel), 2 if part.emissive else 1, np.int8)
        if c.shape[1] == 4:  # 4th channel marks glowing voxels (hot grout, lamp glass)
            f[c[:, 3] > 0] = 2
        flag[sel[:, 0], sel[:, 1], sel[:, 2]] = f
        pid[sel[:, 0], sel[:, 1], sel[:, 2]] = pi
        if part.keep:
            keep[sel[:, 0], sel[:, 1], sel[:, 2]] = True

    if asset.bounds is not None:
        return col, flag, pid
    return _crop(col, flag, pid)


def _crop(col, flag, pid):
    occ = flag > 0
    zs, ys, xs = np.nonzero(occ)
    if not len(zs):
        raise ValueError("empty asset")
    z0, z1 = zs.min(), zs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    c = (slice(z0, z1), slice(y0, y1), slice(x0, x1))
    return col[c].copy(), flag[c].copy(), pid[c].copy()


def ensure_2px(col: np.ndarray, flag: np.ndarray, pid: np.ndarray, rounds: int = 2) -> None:
    """Lesson: 1px parts blink as the stack turns. Grow any pixel not inside a solid 2x2 block."""
    for _ in range(rounds):
        changed = False
        for z in range(flag.shape[0]):
            s = flag[z] > 0
            if not s.any():
                continue
            b = s[:-1, :-1] & s[1:, :-1] & s[:-1, 1:] & s[1:, 1:]
            cov = np.zeros_like(s)
            for dy in (0, 1):
                for dx in (0, 1):
                    cov[dy : dy + b.shape[0], dx : dx + b.shape[1]] |= b
            thin = s & ~cov
            if not thin.any():
                continue
            H, W = s.shape
            for y, x in zip(*np.nonzero(thin)):
                # grow toward whichever side has more room, keeping the shape centred
                dx = 1 if x + 1 < W else -1
                dy = 1 if y + 1 < H else -1
                for yy, xx in ((y, x + dx), (y + dy, x), (y + dy, x + dx)):
                    if 0 <= yy < H and 0 <= xx < W and flag[z, yy, xx] == 0:
                        flag[z, yy, xx] = flag[z, y, x]
                        col[z, yy, xx] = col[z, y, x]
                        pid[z, yy, xx] = pid[z, y, x]
                        changed = True
        if not changed:
            break


def pad_xy(col, flag, pid, p=1):
    """Pad x/y so the grown pixels and the outline never touch the slice edge."""
    return (np.pad(col, ((0, 0), (p, p), (p, p), (0, 0))), np.pad(flag, ((0, 0), (p, p), (p, p))),
            np.pad(pid, ((0, 0), (p, p), (p, p)), constant_values=-1))


# ------------------------------------------------------------------ toon shading


def _normals_up(occ: np.ndarray) -> np.ndarray:
    """Up-component of a smoothed occupancy gradient (Sobel-style, like the skill's compute_normals)."""
    o = occ.astype(np.float32)
    p = np.pad(o, 2)
    # 5x5 box blur in x/y, then central difference in z
    k = p.copy()
    for ax in (1, 2):
        k = sum(np.roll(k, d, axis=ax) for d in (-2, -1, 0, 1, 2)) / 5
    gz = k[1:-3, 2:-2, 2:-2] - k[3:-1, 2:-2, 2:-2]  # (below - above) -> positive when open above
    gy = k[2:-2, 1:-3, 2:-2] - k[2:-2, 3:-1, 2:-2]
    gx = k[2:-2, 2:-2, 1:-3] - k[2:-2, 2:-2, 3:-1]
    mag = np.sqrt(gx * gx + gy * gy + gz * gz) + 1e-6
    return gz / mag


def shade(col: np.ndarray, flag: np.ndarray, pid: np.ndarray, style: str = "toon") -> np.ndarray:
    """Rotation-invariant 3-band toon ramp with hue shifting; returns RGBA volume.

    Band = surface normal (up component) + height within the voxel's own part (lower = darker)
    + open sky above (lit) - another part directly above within 6 voxels (canopy / lintel shadow).
    """
    occ = flag > 0
    H = occ.shape[0]
    up = np.zeros_like(occ)
    up[:-1] = occ[1:]
    open_above = occ & ~up
    nz = _normals_up(occ)
    zz = np.broadcast_to(np.arange(H)[:, None, None], occ.shape)
    rel = np.ones(occ.shape, np.float32)
    for p in np.unique(pid[occ]):
        m = pid == p
        zs = zz[m]
        lo, hi = zs.min(), zs.max()
        if hi - lo >= 3:
            rel[m] = (zs - lo) / (hi - lo)
    other = np.zeros_like(occ)
    for d in range(1, 7):
        sh_occ = np.zeros_like(occ)
        sh_pid = np.full(pid.shape, -1, pid.dtype)
        sh_occ[:-d] = occ[d:]
        sh_pid[:-d] = pid[d:]
        other |= sh_occ & (sh_pid != pid)
    score = 0.45 * nz + 0.28 * (2 * rel - 1) + 0.4 * open_above - 0.45 * other
    band = np.ones(occ.shape, np.int8)  # 0 shadow, 1 mid, 2 lit
    band[score > 0.3] = 2
    band[score < -0.28] = 0
    zfrac = zz / max(H - 1, 1)

    out = np.zeros(occ.shape + (4,), np.uint8)
    solid = occ & (flag == 1)
    keys = col[solid].astype(np.int64)
    keys = (keys[:, 0] << 16) | (keys[:, 1] << 8) | keys[:, 2]
    bands = band[solid].astype(np.int64)
    lows = (zfrac[solid] < 0.35).astype(np.int64)
    combo = keys * 8 + bands * 2 + lows
    uniq, inv = np.unique(combo, return_inverse=True)
    lut = np.zeros((len(uniq), 3), np.uint8)
    for i, c in enumerate(uniq):
        rgb, b, low = int(c) >> 3, (int(c) >> 1) & 3, int(c) & 1
        lut[i] = _ramp(((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255), b, low, style)
    out[solid, :3] = lut[inv.ravel()]
    out[solid, 3] = 255
    em = flag == 2
    out[em, :3] = col[em]
    out[em, 3] = 255
    return out


def _ramp(rgb, band, low, style):
    r, g, b = (c / 255 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if style == "soft":
        v_f, s_f, hshift = ((0.80, 1.15, 0.03), (0.93, 1.05, 0.015), (1.0, 1.0, 0.0))[band]
    elif v < 0.35:  # near-black materials (obsidian, char): lift the lit band so the form still reads
        v_f, s_f, hshift = ((0.72, 1.1, 0.03), (1.08, 1.0, 0.01), (1.55, 0.95, -0.01))[band]
    else:
        v_f, s_f, hshift = ((0.62, 1.12, 0.035), (0.84, 1.02, 0.012), (1.0, 0.94, -0.012))[band]
    if low and band < 2:
        v_f *= 0.93
    # hue shift: shadows drift toward blue (h ~ 0.62), highlights toward yellow (h ~ 0.14)
    target = 0.62 if hshift > 0 else 0.14
    d = ((target - h + 0.5) % 1.0) - 0.5
    h = (h + max(-abs(hshift), min(abs(hshift), d))) % 1.0
    if band == 2:
        v = v + (1 - v) * 0.08
    rr, gg, bb = colorsys.hsv_to_rgb(h, min(1, s * s_f), min(1, v * v_f))
    return int(rr * 255 + 0.5), int(gg * 255 + 0.5), int(bb * 255 + 0.5)


def build_volume(asset: Asset) -> np.ndarray:
    col, flag, pid = voxelize(asset)
    col, flag, pid = pad_xy(col, flag, pid, 0 if asset.bounds is not None else 1)
    ensure_2px(col, flag, pid)
    return shade(col, flag, pid, asset.shading)


def to_strip(vol: np.ndarray) -> np.ndarray:
    return np.concatenate(list(vol), axis=1)
