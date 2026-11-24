// Exact versions of the game's three.js parts as ink-studio solids: any 3x3 matrix (rotation, non-uniform scale, shear) applied to the
// original primitive (n-sided flat-capped cylinder or cone, sphere, box, flat torus). Distances are corrected to world space to first order.
const TAU = Math.PI * 2;

function inv3(M) {
  const [a, b, c] = M[0], [d, e, f] = M[1], [g, h, i] = M[2];
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
  return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
    [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
    [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]];
}

// local primitive: { sd(x,y,z), sample(res, f), br }
function prim(kind, q) {
  if (kind === 'cyl' || kind === 'cone') {
    const n = q.n || 8, h = q.h, rt = kind === 'cone' ? 0 : q.rt, rb = kind === 'cone' ? q.r : q.rb;
    const cs = Math.cos(Math.PI / n), slope = (rb - rt) / h, kf = cs / Math.hypot(1, slope);
    const nrm = Array.from({ length: n }, (_, k) => [Math.sin((k + .5) * TAU / n), Math.cos((k + .5) * TAU / n)]);
    const vtx = Array.from({ length: n + 1 }, (_, k) => [Math.sin(k * TAU / n), Math.cos(k * TAU / n)]);
    const rAt = y => rb + (rt - rb) * (y / h + .5);
    const ring = (r, y, res, f, phase = 0) => {
      const per = n * 2 * r * Math.sin(Math.PI / n), cnt = Math.max(3, Math.ceil(per / res));
      for (let i = 0; i < cnt; i++) {
        const u = ((i + phase) / cnt) * n, e = Math.floor(u) % n, fr = u - Math.floor(u), A = vtx[e], B = vtx[e + 1];
        f((A[0] + (B[0] - A[0]) * fr) * r, y, (A[1] + (B[1] - A[1]) * fr) * r);
      }
    };
    return {
      br: Math.hypot(Math.max(rt, rb), h / 2),
      sd: (x, y, z) => {
        let pr = -1e9; for (const [s, c] of nrm) pr = Math.max(pr, x * s + z * c);
        const dr = (pr / cs - rAt(Math.max(-h / 2, Math.min(h / 2, y)))) * kf, dy = Math.abs(y) - h / 2;
        return Math.min(Math.max(dr, dy), 0) + Math.hypot(Math.max(dr, 0), Math.max(dy, 0));
      },
      sample: (res, f) => {
        const rows = Math.max(2, Math.ceil(h / res * 1.25));
        for (let j = 0; j < rows; j++) { const y = ((j + .5) / rows - .5) * h; ring(rAt(y), y, res, f, j * .5); }
        for (const [y, r0] of [[-h / 2, rb], [h / 2, rt]]) {
          for (let r = r0 - res * .5; r > 0; r -= res) ring(r, y, res, f);
          if (r0 > 0) f(0, y, 0);
        }
      },
    };
  }
  if (kind === 'sph') {
    const r = q.r;
    return {
      br: r, sd: (x, y, z) => Math.hypot(x, y, z) - r,
      sample: (res, f) => {
        const N = Math.max(12, Math.ceil(4 * Math.PI * r * r / (res * res) * 1.3)), ga = Math.PI * (3 - Math.sqrt(5));
        for (let i = 0; i < N; i++) { const y = 1 - (i + .5) / N * 2, s = Math.sqrt(1 - y * y), a = i * ga; f(Math.cos(a) * s * r, y * r, Math.sin(a) * s * r); }
      },
    };
  }
  if (kind === 'box') {
    const hs = [q.w / 2, q.h / 2, q.d / 2];
    return {
      br: Math.hypot(...hs),
      sd: (x, y, z) => {
        const dx = Math.abs(x) - hs[0], dy = Math.abs(y) - hs[1], dz = Math.abs(z) - hs[2];
        return Math.min(Math.max(dx, dy, dz), 0) + Math.hypot(Math.max(dx, 0), Math.max(dy, 0), Math.max(dz, 0));
      },
      sample: (res, f) => {
        for (let a = 0; a < 3; a++) {
          const b = (a + 1) % 3, c = (a + 2) % 3, nb = Math.max(1, Math.ceil(2 * hs[b] / res)), nc = Math.max(1, Math.ceil(2 * hs[c] / res)), p = [0, 0, 0];
          for (let i = 0; i < nb; i++) for (let j = 0; j < nc; j++) for (const sg of [-1, 1]) {
            p[a] = sg * hs[a]; p[b] = ((i + .5) / nb * 2 - 1) * hs[b]; p[c] = ((j + .5) / nc * 2 - 1) * hs[c]; f(p[0], p[1], p[2]);
          }
        }
      },
    };
  }
  if (kind === 'torus') {
    const R = q.R, t = q.t;
    return {
      br: R + t, sd: (x, y, z) => Math.hypot(Math.hypot(x, z) - R, y) - t,
      sample: (res, f) => {
        const nu = Math.ceil(TAU * (R + t) / res), nv = Math.max(4, Math.ceil(TAU * t / res));
        for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) {
          const a = i / nu * TAU, b = j / nv * TAU, w = R + Math.cos(b) * t; f(Math.cos(a) * w, Math.sin(b) * t, Math.sin(a) * w);
        }
      },
    };
  }
  throw Error('unknown part kind ' + kind);
}

// singular values (sqrt of eigenvalues of A^T A) via column norms is enough for sampling density and bounds
const colLen = (A, j) => Math.hypot(A[0][j], A[1][j], A[2][j]);

/** Add part `kind`/`q`, transformed by 3x3 `A` and moved to `t`, to sculptor S. */
function affineSolid(S, kind, q, A, t, mat, o, clipY = null) {
  const P = prim(kind, q), Ai = inv3(A), smax = Math.max(colLen(A, 0), colLen(A, 1), colLen(A, 2));
  const E = 1e-3;
  const sd0 = (x, y, z) => {
    const lx = Ai[0][0] * x + Ai[0][1] * y + Ai[0][2] * z, ly = Ai[1][0] * x + Ai[1][1] * y + Ai[1][2] * z, lz = Ai[2][0] * x + Ai[2][1] * y + Ai[2][2] * z;
    const d = P.sd(lx, ly, lz);
    const gx = P.sd(lx + E, ly, lz) - P.sd(lx - E, ly, lz), gy = P.sd(lx, ly + E, lz) - P.sd(lx, ly - E, lz), gz = P.sd(lx, ly, lz + E) - P.sd(lx, ly, lz - E);
    // world gradient = Ai^T g
    const wx = Ai[0][0] * gx + Ai[1][0] * gy + Ai[2][0] * gz, wy = Ai[0][1] * gx + Ai[1][1] * gy + Ai[2][1] * gz, wz = Ai[0][2] * gx + Ai[1][2] * gy + Ai[2][2] * gz;
    const gl = Math.hypot(wx, wy, wz) / (2 * E);
    const dw = gl > 1e-6 ? d / gl : d * smax;
    return clipY === null ? dw : Math.max(dw, clipY - (y + t[1]));   // cut off below the ground, keeping the part's own colours
  };
  // sample in the part's own space at the finest spacing any axis needs, then keep one point per world cell so stretched parts aren't oversampled
  const sm0 = (res, f) => {
    const cell = res * 0.7, seen = new Set();
    P.sample(res / smax, (x, y, z) => {
      const wx = A[0][0] * x + A[0][1] * y + A[0][2] * z, wy = A[1][0] * x + A[1][1] * y + A[1][2] * z, wz = A[2][0] * x + A[2][1] * y + A[2][2] * z;
      const key = Math.floor(wx / cell) * 73856093 ^ Math.floor(wy / cell) * 19349663 ^ Math.floor(wz / cell) * 83492791;
      if (clipY !== null && wy + t[1] < clipY) return;
      if (seen.has(key)) return; seen.add(key); f(wx, wy, wz);
    });
  };
  return S.solid(t, P.br * smax, sd0, sm0, mat, o);
}

/** Thicken parts thinner than minR (in world units) along each local axis so they don't blink between views. */
function thicken(kind, q, A, minR) {
  const ext = kind === 'box' ? [q.w / 2, q.h / 2, q.d / 2]
    : kind === 'cyl' || kind === 'cone' ? [Math.max(kind === 'cone' ? q.r : Math.max(q.rt, q.rb)), q.h / 2, Math.max(kind === 'cone' ? q.r : Math.max(q.rt, q.rb))]
      : kind === 'torus' ? [q.R + q.t, q.t, q.R + q.t] : [q.r, q.r, q.r];
  const B = A.map(r => r.slice());
  for (let j = 0; j < 3; j++) {
    if (kind === 'torus' && j !== 1) continue;
    if ((kind === 'cyl' || kind === 'cone') && j === 1) continue;
    const w = ext[j] * colLen(A, j);
    if (w > 0 && w < minR) { const k = minR / w; for (let i = 0; i < 3; i++) B[i][j] *= k; }
  }
  if (kind === 'torus') { const w = q.t * colLen(A, 1); if (w < minR) q = { ...q, t: q.t * minR / w }; return { A: A, q }; }
  return { A: B, q };
}

module.exports = { affineSolid, thicken, prim, inv3 };
