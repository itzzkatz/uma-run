// Bake Uma Run background assets as ink-studio pixel splats and render a 32-direction view atlas for each.
// Usage: node bake.js [key ...]   (reads parts/<key>.json, writes atlas/<key>.rgba + atlas/<key>.json)
const fs = require('node:fs');
const path = require('node:path');
// ink-studio checkout: github.com/siliconjungle/shapeshift-labs-ink-studio
const INK = process.env.INK_STUDIO || path.resolve(__dirname, '../../../shapeshift-labs-ink-studio');
const studio = require(INK);
const { affineSolid, thicken, prim } = require('./affine.js');
const { makeBuilder, makeSculpt, KIT: K } = studio.load();

const PITCH = Math.asin(0.75);           // the game's camera: ground squashed to 0.75
const KV = 1 / Math.cos(PITCH);          // stretch heights so one pixel = 30 cm of height, like the sprite stacks
const TAN = 0.34432;                     // ink-studio's half-FOV tangent (unitsPerPixel = 2*TAN*dist/h), measured
const DIRS = +(process.env.DIRS || 32);

const here = __dirname;
fs.mkdirSync(path.join(here, 'atlas'), { recursive: true });

// ------------------------------------------------------------ colour ramps (dark -> light), hue-shifted like the stacks
function hsv(r, g, b) { r /= 255; g /= 255; b /= 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0; if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h = (h / 6 + 1) % 1;
  return [h, mx ? d / mx : 0, mx]; }
function rgb(h, s, v) { const i = Math.floor(h * 6), f = h * 6 - i, p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][((i % 6) + 6) % 6];
  return (Math.round(Math.min(1, r) * 255) << 16) | (Math.round(Math.min(1, g) * 255) << 8) | Math.round(Math.min(1, b) * 255); }
function shift(h, target, amt) { let d = ((target - h + 1.5) % 1) - .5; return (h + Math.max(-amt, Math.min(amt, d)) + 1) % 1; }
function ramp([r, g, b]) {
  const [h, s, v] = hsv(r, g, b), dark = v < 0.35;
  return [
    rgb(shift(h, .62, .05), Math.min(1, s * 1.15), v * (dark ? .7 : .52)),
    rgb(shift(h, .62, .025), Math.min(1, s * 1.08), v * (dark ? .95 : .74)),
    rgb(h, s, v),
    rgb(shift(h, .14, .02), s * .9, Math.min(1, dark ? v * 1.5 + .05 : v + (1 - v) * .3)),
  ];
}

// ------------------------------------------------------------ geometry helpers
const sub = (a, b) => a.map((v, i) => v - b[i]), add = (a, b) => a.map((v, i) => v + b[i]);
const mul = (A, v) => [0, 1, 2].map(i => A[i][0] * v[0] + A[i][1] * v[1] + A[i][2] * v[2]);
const col = (A, j) => [A[0][j], A[1][j], A[2][j]];
const len = v => Math.hypot(...v), norm = v => { const l = len(v) || 1; return v.map(x => x / l); };


// ------------------------------------------------------------ materials with texture hooks (tex returns a palette index)
function hash(a, b, c) { let h = Math.imul(a | 0, 374761393) ^ Math.imul(b | 0, 668265263) ^ Math.imul(c | 0, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
const BRICK_W = 1.2, BRICK_H = 0.9 * KV;   // the game's stone: rows every 0.9 m, joints every 1.2 m
function stoneMat(base, grout, glow, moss) {
  return { ...base, tex: (x, y, z, ny, t) => {
    const row = Math.floor(y / BRICK_H), fy = y / BRICK_H - row;
    const ua = (Math.abs(ny) > 0.7 ? x + z * 0.37 : x + z) / BRICK_W + (row & 1) * 0.5, col = Math.floor(ua), fu = ua - col;
    const mortar = fy < 0.17 || (Math.abs(ny) < 0.7 && fu < 0.2) || (Math.abs(ny) > 0.7 && (fu < 0.14 || Math.abs(z / BRICK_W - Math.round(z / BRICK_W)) < 0.07));
    if (mortar) { if (glow) return hash(col, row, 3) < 0.5 ? grout.r[grout.r.length - 1] : base.r[0]; return grout.r[Math.min(grout.r.length - 1, Math.floor(t * grout.r.length))]; }
    if (moss && hash(Math.floor(x / 0.3), Math.floor(y / 0.3), Math.floor(z / 0.3)) < (ny > 0.6 ? 0.22 : 0.05)) return moss.r[Math.min(3, 1 + Math.floor(t * 3))];
    const v = hash(col, row, 9) - 0.5;   // per-block brightness
    return base.r[Math.max(0, Math.min(base.r.length - 1, Math.floor((t + v * 0.22) * base.r.length)))];
  } };
}
function gradMat(lo, hi, [y0, y1], em) {
  return { r: hi.r, em, tex: (x, y, z, ny, t) => {
    const f = (y - y0) / Math.max(1e-6, y1 - y0) + (hash(Math.floor(x / .3), Math.floor(y / .3), Math.floor(z / .3)) - .5) * .25;
    const r = f < 0.5 ? lo.r : hi.r; return r[Math.max(0, Math.min(r.length - 1, Math.floor(t * r.length)))];
  } };
}
let FLAME = null;
function flameMat([y0, y1]) {
  return { r: FLAME, em: true, tex: (x, y, z) => {
    const f = (y - y0) / Math.max(1e-6, y1 - y0) + (hash(Math.floor(x / .3), Math.floor(y / .45), Math.floor(z / .3)) - .5) * .25;
    return FLAME[f < 0.3 ? 2 : f < 0.65 ? 1 : 0];
  } };
}
function partYRange(p) {
  const A = p.A, t = p.t, k = p.kind, q = p.p;
  const ext = k === 'box' ? [q.w / 2, q.h / 2, q.d / 2] : k === 'cyl' || k === 'cone' ? [Math.max(q.rt ?? q.r, q.rb ?? q.r), q.h / 2, Math.max(q.rt ?? q.r, q.rb ?? q.r)]
    : k === 'torus' ? [q.R + q.t, q.t, q.R + q.t] : [q.r, q.r, q.r];
  const dy = Math.abs(A[1][0]) * ext[0] + Math.abs(A[1][1]) * ext[1] + Math.abs(A[1][2]) * ext[2];
  return [t[1] - dy, t[1] + dy];
}

function bake(def) {
  const UPP = def.scale || 0.3, MIN_R = 0.2 * UPP / 0.3;
  const g0 = def.ground ?? 0;
  // stretch about the ground and move the ground to y = 0
  const parts = def.parts.map(p => {
    const A = p.A.map((row, i) => i === 1 ? row.map(v => v * KV) : row.slice());
    const t = [p.t[0], (p.t[1] - g0) * KV, p.t[2]];
    return { ...p, A, t };
  });
  // palette: 0 = black, then a 4-tone ramp per distinct colour (+ grout and band colours)
  const pal = [0x000000], rampOf = new Map();
  const mat = (c, em) => { const k = c.join(',') + (em ? 'e' : ''); if (!rampOf.has(k)) { const i = pal.length; pal.push(...ramp(c)); rampOf.set(k, [i, i + 1, i + 2, i + 3]); }
    const r = rampOf.get(k); return em ? { r: r.slice(1), em: true } : { r }; };
  FLAME = [pal.length, pal.length + 1, pal.length + 2]; pal.push(0xec4614, 0xffa028, 0xffec96);
  const MOSS = def.biome === 'jungle' ? mat([110, 196, 64], false) : null;
  mat([255, 255, 255], false);
  for (const p of parts) { mat(p.color, p.emissive); if (p.grout) mat(p.grout, !!p.glow); if (p.alt) mat(p.alt, false); if (p.grad) p.grad.forEach(c => mat(c, p.emissive)); }

  const B = makeBuilder(7, pal);
  const S = K.sculpt(makeSculpt(B));
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  let RX = 0;
  const grow = (pt, r = 0) => { RX = Math.max(RX, Math.hypot(pt[0], pt[2]) + r); for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], pt[i] - r); hi[i] = Math.max(hi[i], pt[i] + r); } };

  for (const p of parts) {
    const A = p.A, t = p.t, k = p.kind, q = p.p;
    const sx = len(col(A, 0)), sy = len(col(A, 1)), sz = len(col(A, 2));
    const ax = [norm(col(A, 0)), norm(col(A, 1)), norm(col(A, 2))];
    // material: stone gets the game's block grout (glowing in the Inferno), bands alternate, gradients run bottom to top
    const yr = partYRange(p);
    let m = mat(p.color, p.emissive);
    if (p.grout) m = stoneMat(m, mat(p.grout, !!p.glow), !!p.glow, MOSS);
    else if (p.alt) m = { ...m, mod: (x, y) => (Math.floor(y / 0.55) & 1 ? -0.16 : 0) };
    else if (p.style === 'flame') m = flameMat(yr);
    else if (p.grad) m = gradMat(mat(p.grad[0], p.emissive), mat(p.grad[1], p.emissive), yr, p.emissive);
    if (def.key === 'inner_tubes') { const pk = m, wh = mat([255, 255, 255], false), c0 = t;
      m = { ...pk, tex: (x, y, z, ny, tt) => { const r = (Math.floor((Math.atan2(z - c0[2], x - c0[0]) + Math.PI) / (2 * Math.PI) * 8) & 1) ? wh.r : pk.r; return r[Math.max(0, Math.min(3, Math.floor(tt * 4)))]; } }; }
    const opt = { res: 0.09 * UPP / 0.3 };
    const th = thicken(k, { ...q }, A, MIN_R);
    const clip = def.ground !== null ? 0 : null;
    if (clip !== null && partYRange({ ...p, A: th.A, p: th.q })[1] <= 0) continue;
    affineSolid(S, k, th.q, th.A, t, m, opt, clip);
    const Ab = th.A, sc = Math.max(...[0, 1, 2].map(j => len(col(Ab, j))));
    prim(k, th.q).sample(UPP / sc, (x, y, z) => (clip !== null && Ab[1][0] * x + Ab[1][1] * y + Ab[1][2] * z + t[1] < clip) ? 0 : grow([Ab[0][0] * x + Ab[0][1] * y + Ab[0][2] * z + t[0], Ab[1][0] * x + Ab[1][1] * y + Ab[1][2] * z + t[1], Ab[2][0] * x + Ab[2][1] * y + Ab[2][2] * z + t[2]]));
  }
  // cut everything below the ground plane
  const BRK = null;
  S.bake();
  lo[1] = Math.max(lo[1], def.ground !== null ? 0 : lo[1]);
  const cx = 0, cz = 0, top = hi[1], bottom = lo[1];
  const R = RX;
  const Hs = top - bottom, pivot = [cx, bottom + Hs / 2, cz];
  const W = Math.ceil(2 * R / UPP) + 6, H = Math.ceil((2 * R * Math.sin(PITCH) + Hs * Math.cos(PITCH)) / UPP) + 6;
  const dist = UPP * H / (2 * TAN);
  const world = B.finish({ cam: { target: pivot, dist, pitch: PITCH, yaw: 0 }, detail: 14 });
  const t0 = Date.now();
  const at = studio.spriteAtlas(world, { width: W, height: H, directions: DIRS, columns: DIRS, pivot, view: { pitch: PITCH, yaw: 0, dist } });
  const md = at.metadata, f0 = md.frames[0];
  // ground anchor (asset origin at y = 0) inside each tile, in art pixels
  const anchor = { x: f0.pivot.x + 0, y: f0.pivot.y + (Hs / 2) * Math.cos(PITCH) / f0.unitsPerPixel };
  const meta = { key: def.key, title: def.title, biome: def.biome, outline: def.outline, tileW: md.tileWidth, tileH: md.tileHeight,
    width: md.width, height: md.height, directions: DIRS, yaws: md.frames.map(f => +f.yaw.toFixed(4)), upp: f0.unitsPerPixel, anchor, pivot, splats: world.count, ms: Date.now() - t0,
    center: [cx, cz] };
  fs.writeFileSync(path.join(here, 'atlas', def.key + '.rgba'), Buffer.from(at.images.color));
  fs.writeFileSync(path.join(here, 'atlas', def.key + '.json'), JSON.stringify(meta));
  return meta;
}

const keys = process.argv.slice(2).length ? process.argv.slice(2) : fs.readdirSync(path.join(here, 'parts')).map(f => f.replace('.json', ''));
for (const key of keys) {
  const def = JSON.parse(fs.readFileSync(path.join(here, 'parts', key + '.json'), 'utf8'));
  const t = Date.now();
  try { const m = bake(def); console.log(key.padEnd(24), `${m.tileW}x${m.tileH}`, 'upp', m.upp.toFixed(3), 'splats', m.splats, 'atlas', m.ms + 'ms', 'total', (Date.now() - t) + 'ms'); }
  catch (e) { console.log(key, 'FAILED', e.message.split('\n')[0]); }
}
