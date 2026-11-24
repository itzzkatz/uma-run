"""Make the pixel-splat edition of Uma Run from the original game file.

Only the art changes: the camera, gameplay, UI, audio and data are the original's, byte for byte.
  - the scene renders at a low internal resolution and is scaled up with hard pixels
  - one post pass draws 1 px ink outlines from depth (replacing the scenery's hull outlines)
  - every non-character toon material is shaded like ink-studio pixel splats: a 4-tone hue-shifted ramp
    per colour (cool shadows, warm highlights) with world-locked splat speckle
  - the sky becomes dithered bands, the ground below gets camo blotches, the floating islands get the splat ramp

Usage: python3 make_pixel.py <original.html> <out.html> [--test]
--test keeps a hook so the headless tests can pass dev params (the published build has them off).
"""
import sys
from pathlib import Path

src_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
TEST = "--test" in sys.argv
s = src_path.read_text()


def sub(old, new, count=1):
    global s
    n = s.count(old)
    if n < count or (count == 1 and n != 1):
        raise SystemExit(f"patch anchor found {n}x (wanted {count}): {old[:90]!r}")
    s = s.replace(old, new)


SPLAT_GLSL = r"""
#ifndef SPLAT_CELL
#define SPLAT_CELL 0.02
#endif
#ifndef SPLAT_K
#define SPLAT_K 0.86
#endif
vec3 spHsv(vec3 c){ vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0); vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r)); float d = q.x - min(q.w, q.y);
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x); }
vec3 spRgb(vec3 c){ vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0); vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www); return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y); }
float spShift(float h, float target, float amt){ float d = fract(target - h + 1.5) - 0.5; return fract(h + clamp(d, -amt, amt) + 1.0); }
// ink-studio style ramp: tone 0 deep shadow, 1 shadow, 2 the colour itself, 3 highlight (shadows lean blue, highlights lean warm)
vec3 spTone(vec3 lin, float s){
  vec3 h = spHsv(pow(max(lin, vec3(0.0)), vec3(1.0 / 2.2))); bool dark = h.z < 0.35;
  if (s < 0.5) h = vec3(spShift(h.x, 0.62, 0.05), min(1.0, h.y * 1.12), h.z * (dark ? 0.78 : 0.6));
  else if (s < 1.5) h = vec3(spShift(h.x, 0.62, 0.025), min(1.0, h.y * 1.08), h.z * (dark ? 0.95 : 0.74));
  else if (s > 2.5) h = vec3(spShift(h.x, 0.14, 0.02), h.y * 0.9, min(1.0, dark ? h.z * 1.5 + 0.05 : h.z + (1.0 - h.z) * 0.3));
  return pow(spRgb(h), vec3(2.2));
}
float spHash(vec3 p){ p = fract(p * vec3(0.1031, 0.1030, 0.0973)); p += dot(p, p.yxz + 33.33); return fract((p.x + p.y) * p.z); }
// splat cells: a tilted lattice locked to the world; cells grow in powers of two so one is never under ~1.6 screen pixels
float spCell(vec3 w){
  float fp = max(length(dFdx(w)), length(dFdy(w)));
  float cs = SPLAT_CELL * exp2(max(0.0, ceil(log2(fp * 1.5 / SPLAT_CELL))));
  vec3 q = mat3(0.857, 0.286, -0.429, -0.371, 0.914, -0.171, 0.357, 0.286, 0.889) * w;
  return spHash(floor(q / cs) + cs * 17.0);
}
float spNoise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  float a = spHash(vec3(i, 3.0)), b = spHash(vec3(i + vec2(1.0, 0.0), 3.0)), c = spHash(vec3(i + vec2(0.0, 1.0), 3.0)), d = spHash(vec3(i + vec2(1.0, 1.0), 3.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y); }
// pick a tone from the light level k (1 = plain sunlit; the game's light gives ~0.37 in cast shadow, ~0.62 on shaded sides,
// ~0.8 on half-lit sides, ~0.96 in full sun). No per-splat speckle: it twinkled as the camera moved.
vec3 splatK(vec3 base, float k, vec3 w){
  float t = k < SPLAT_K ? (k - 0.14) / 0.36 : 2.0 + (k - SPLAT_K) / 0.14;
#ifdef SPLAT_BLOTCH
  float bl = spNoise(w.xz / 9.0) * 0.65 + spNoise(w.xz / 3.1) * 0.35; t -= step(0.56, bl) * 0.6 + step(0.74, bl) * 0.35;
#endif
  return spTone(base, clamp(floor(t), 0.0, 3.0));
}
vec3 splatShade(vec3 base, vec3 lit, vec3 w){
  float lb = max(dot(base, vec3(0.2126, 0.7152, 0.0722)), 1e-4);
  return splatK(base, dot(lit, vec3(0.2126, 0.7152, 0.0722)) / lb, w);
}
"""

# ------------------------------------------------------------------ 1. splat shading for every toon material (not the skinned characters)
sub("import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';   // v52: merged jungle flora\n",
    "import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';   // v52: merged jungle flora\n"
    "// ================================================================ PIXEL-SPLAT ART PASS\n"
    "// Toon materials are shaded like ink-studio pixel splats; skinned characters keep their own shading.\n"
    "const SPLAT_GLSL = " + repr(SPLAT_GLSL).replace("\\n", "\\n") + ";\n"
    "{ const L = THREE.ShaderLib.toon;\n"
    "  L.vertexShader = L.vertexShader.replace('#include <common>', '#include <common>\\nvarying vec3 vSplatW;')\n"
    "    .replace('#include <project_vertex>', '#include <project_vertex>\\n\\tvSplatW = (mvPosition.xyz - viewMatrix[3].xyz) * mat3(viewMatrix);');\n"
    "  L.fragmentShader = L.fragmentShader.replace('#include <common>', '#include <common>\\nvarying vec3 vSplatW;\\n' + SPLAT_GLSL)\n"
    "    .replace('vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;',\n"
    "      'vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;\\n'\n"
    "      + '#if !defined(USE_SKINNING) && !defined(SPLAT_OFF)\\n\\toutgoingLight = splatShade(diffuseColor.rgb, reflectedLight.directDiffuse + reflectedLight.indirectDiffuse, vSplatW) + totalEmissiveRadiance;\\n#endif');\n"
    "}\n")

# ------------------------------------------------------------------ 2. low-res render + nearest upscale + 1 px ink outline pass
RENDER_JS = r"""const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(1);
// Pixel art: the world renders at ~230 px on the short side and every art pixel becomes a whole block of screen pixels.
// The runner and the chasers are drawn afterwards at full resolution in their original look, hidden behind pixel scenery
// by the world's depth, and they still cast their shadows into the pixel world.
const PIX = { z: 3, m: 3, w: 2, h: 2 }, CHAR_LAYER = 30;
const pixRT = new THREE.WebGLRenderTarget(2, 2, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthTexture: new THREE.DepthTexture(2, 2) });
const inkRT = new THREE.WebGLRenderTarget(2, 2, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: false });
pixRT.texture.colorSpace = inkRT.texture.colorSpace = THREE.SRGBColorSpace;
const pixU = { tCol: { value: pixRT.texture }, tInk: { value: inkRT.texture }, tDep: { value: pixRT.depthTexture }, uRes: { value: new THREE.Vector2(2, 2) },
  uNF: { value: new THREE.Vector2(0.1, 600) }, uFog: { value: new THREE.Vector2(48, 220) } };
const PIX_VS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';
const pixCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1), inkScene = new THREE.Scene(), outScene = new THREE.Scene();
// 1 px ink outline where a nearer surface ends, coloured as a dark version of that surface (low res)
inkScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({ uniforms: pixU, depthTest: false, depthWrite: false, vertexShader: PIX_VS,
  fragmentShader: 'uniform sampler2D tCol; uniform sampler2D tDep; uniform vec2 uRes; uniform vec2 uNF; uniform vec2 uFog; varying vec2 vUv;\n' +
    'float lin(float d){ return uNF.x * uNF.y / (uNF.y - d * (uNF.y - uNF.x)); }\n' +
    'void main(){ vec2 px = 1.0 / uRes; vec3 c = texture2D(tCol, vUv).rgb; float d0 = lin(texture2D(tDep, vUv).x), dn = d0; vec3 nc = c;\n' +
    ' for (int i = 0; i < 4; i++) { vec2 o = i == 0 ? vec2(px.x, 0.0) : i == 1 ? vec2(-px.x, 0.0) : i == 2 ? vec2(0.0, px.y) : vec2(0.0, -px.y);\n' +
    '  float d = lin(texture2D(tDep, vUv + o).x); if (d < dn) { dn = d; nc = texture2D(tCol, vUv + o).rgb; } }\n' +
    ' float edge = step(0.07 * d0 + 0.35, d0 - dn) * (1.0 - 0.75 * smoothstep(uFog.x, uFog.y, dn));\n' +
    ' vec3 ink = nc * vec3(0.085, 0.07, 0.1) + vec3(0.002, 0.001, 0.004);\n' +
    ' gl_FragColor = vec4(mix(c, ink, edge), 1.0);\n#include <colorspace_fragment>\n}' })));
// full-res composite: the pixel image in hard blocks, plus the world's depth (pushed back 15 cm so feet never sink into a block)
outScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({ uniforms: pixU, depthTest: true, depthWrite: true, depthFunc: THREE.AlwaysDepth, vertexShader: PIX_VS,
  fragmentShader: 'uniform sampler2D tInk; uniform sampler2D tDep; uniform vec2 uNF; varying vec2 vUv;\n' +
    'void main(){ float d = texture2D(tDep, vUv).x; float n = uNF.x, f = uNF.y;\n' +
    ' if (d < 1.0) { float z = n * f / (f - d * (f - n)) + 0.15; d = clamp(f * (z - n) / (z * (f - n)), 0.0, 1.0); }\n' +
    ' gl_FragDepth = d; gl_FragColor = texture2D(tInk, vUv);\n#include <colorspace_fragment>\n}' })));
function pixSize() {
  const dpr = window.devicePixelRatio || 1, Wd = Math.round(innerWidth * dpr), Hd = Math.round(innerHeight * dpr);
  if (!Wd || !Hd) return;
  PIX.z = Math.max(2, Math.round(Math.min(Wd, Hd) / 230)); PIX.w = Math.ceil(Wd / PIX.z); PIX.h = Math.ceil(Hd / PIX.z);
  PIX.m = dpr <= 2 ? PIX.z : Math.max(2, Math.round(PIX.z * 2 / dpr));     // canvas pixels per art pixel (like the original, at most ~2x CSS)
  renderer.setSize(PIX.w * PIX.m, PIX.h * PIX.m, false); pixRT.setSize(PIX.w, PIX.h); inkRT.setSize(PIX.w, PIX.h); pixU.uRes.value.set(PIX.w, PIX.h);
  const st = renderer.domElement.style; st.width = (PIX.w * PIX.z / dpr) + 'px'; st.height = (PIX.h * PIX.z / dpr) + 'px';
}
const _chars = [], _charMats = [];
function charObjects() {                          // the runner (with her tube + shield), the chasers and the pickup sparkles
  _chars.length = 0;
  const add = o => { if (o.material) _chars.push(o); };
  if (typeof hero !== 'undefined') hero.traverse(add);
  if (typeof monkeys !== 'undefined') for (const m of monkeys) m.g.traverse(add);
  if (typeof sparks !== 'undefined') for (const k of sparks) if (k.sp.visible) _chars.push(k.sp);
  return _chars;
}
let _lightsTagged = false;
function pixRender(sc, cam) {
  if (!_lightsTagged) { sc.traverse(o => { if (o.isLight) o.layers.enable(CHAR_LAYER); }); _lightsTagged = true; }
  pixU.uNF.value.set(cam.near, cam.far); if (sc.fog) pixU.uFog.value.set(sc.fog.near, sc.fog.far);
  const ch = charObjects(); _charMats.length = 0;                                  // (chasers share materials: save each one once)
  for (const o of ch) { o.layers.enable(CHAR_LAYER); for (const m of Array.isArray(o.material) ? o.material : [o.material]) { if (m.userData.pixHid) continue; m.userData.pixHid = true; _charMats.push(m, m.colorWrite, m.depthWrite); m.colorWrite = false; m.depthWrite = false; } }
  renderer.setRenderTarget(pixRT); renderer.render(sc, cam);                       // the pixel world (characters only cast shadows here)
  for (let i = 0; i < _charMats.length; i += 3) { const m = _charMats[i]; m.colorWrite = _charMats[i + 1]; m.depthWrite = _charMats[i + 2]; m.userData.pixHid = false; }
  renderer.setRenderTarget(inkRT); renderer.render(inkScene, pixCam);
  renderer.setRenderTarget(null); renderer.render(outScene, pixCam);
  const ac = renderer.autoClear, su = renderer.shadowMap.autoUpdate, lm = cam.layers.mask;  // the characters, full resolution, original look
  const bg = sc.background; sc.background = null;                                   // a colour background would clear the screen
  renderer.autoClear = false; renderer.shadowMap.autoUpdate = false; cam.layers.set(CHAR_LAYER);
  renderer.render(sc, cam);
  cam.layers.mask = lm; renderer.autoClear = ac; renderer.shadowMap.autoUpdate = su; sc.background = bg;
}
renderer.domElement.style.imageRendering = 'pixelated';
pixSize();
"""
sub("const renderer = new THREE.WebGLRenderer({ antialias: true });\n"
    "renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));\n"
    "renderer.setSize(innerWidth, innerHeight);\n", RENDER_JS)
sub("addEventListener('resize', () => {\n"
    "  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();\n"
    "  renderer.setSize(innerWidth, innerHeight);\n"
    "});\n",
    "addEventListener('resize', () => {\n"
    "  if (!innerWidth || !innerHeight) return;          // a hidden view reports 0x0 for a moment: keep the last size\n"
    "  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();\n"
    "  pixSize();\n"
    "});\n")
sub("if (TURN || !(state === 'start' && !menuEl.classList.contains('hidden'))) renderer.render(scene, camera);",
    "if (TURN || !(state === 'start' && !menuEl.classList.contains('hidden'))) pixRender(scene, camera);")
sub("flameU.uPx.value = renderer.getPixelRatio() * innerHeight / 40;", "flameU.uPx.value = PIX.h / 40;")
sub("  canvas{display:block}", "  canvas{display:block}\n  body>canvas{position:fixed;left:0;top:0;image-rendering:pixelated;image-rendering:crisp-edges}")

# ------------------------------------------------------------------ 3. scenery hull outlines off (the ink pass draws one even line instead)
sub("const rootOutline = new THREE.MeshBasicMaterial({ color: 0x5e3818, side: THREE.BackSide });\n",
    "const rootOutline = new THREE.MeshBasicMaterial({ color: 0x5e3818, side: THREE.BackSide });\n"
    "envOutline.visible = leafOutline.visible = rootOutline.visible = false;\n")
for name, col in [("rockOutline", "0x36424c"), ("hellOutline", "0x140605"), ("tunOutline", "0x1a2c44"), ("hwOl", "0x1e2433")]:
    sub(f"const {name} = new THREE.MeshBasicMaterial({{ color: {col}, side: THREE.BackSide }});",
        f"const {name} = new THREE.MeshBasicMaterial({{ color: {col}, side: THREE.BackSide }}); {name}.visible = false;")

# ------------------------------------------------------------------ 4. background: dithered sky bands, camo ground, splat islands
sub("    'void main(){ float h = vP.y; vec3 c = mix(bot, mid, smoothstep(0.0, 0.22, h)); c = mix(c, top, smoothstep(0.22, 0.85, h));\\n' +\n"
    "    ' gl_FragColor = vec4(c, 1.0);\\n #include <colorspace_fragment>\\n}',",
    "    'void main(){ float h = vP.y; vec3 c = mix(bot, mid, smoothstep(0.0, 0.22, h)); c = mix(c, top, smoothstep(0.22, 0.85, h));\\n' +\n"
    "    // pixel sky: the gradient snaps to bands, with a 4x4 ordered dither where two bands meet\n"
    "    ' vec2 fc = floor(mod(gl_FragCoord.xy, 4.0)), f1 = mod(fc, 2.0), f2 = mod(floor(fc / 2.0), 2.0);\\n' +\n"
    "    ' float bay = (4.0 * mod(2.0 * f1.x + 3.0 * f1.y, 4.0) + mod(2.0 * f2.x + 3.0 * f2.y, 4.0) + 0.5) / 16.0;\\n' +\n"
    "    ' vec3 g = pow(c, vec3(1.0 / 2.2)) * 14.0; c = pow((floor(g) + step(bay, fract(g))) / 14.0, vec3(2.2));\\n' +\n"
    "    ' gl_FragColor = vec4(c, 1.0);\\n #include <colorspace_fragment>\\n}',")
sub("const groundMat = etoon(0x72c845);", "const groundMat = etoon(0x72c845); groundMat.defines = { SPLAT_BLOTCH: '' };")
sub("const grassMat = etoon(0x8ad94f);", "const grassMat = etoon(0x8ad94f); grassMat.defines = { SPLAT_BLOTCH: '' };")
sub("  vertexShader: 'attribute vec3 aCol; uniform vec2 aIn; uniform float uT; uniform float uE; varying vec3 vC; varying vec3 vW; varying float vF;\\n' +\n"
    "    'void main(){ mat4 im = mat4(1.0);\\n#ifdef USE_INSTANCING\\n im = instanceMatrix;\\n#endif\\n vec4 w = modelMatrix * im * vec4(position, 1.0);\\n' +\n"
    "    ' w.y += sin(uT * 0.33 + aIn.x) * 1.8 - uE * 70.0; vW = w.xyz; vC = aCol; vF = aIn.y * (1.0 - uE); gl_Position = projectionMatrix * viewMatrix * w; }',\n"
    "  fragmentShader: 'uniform vec3 uFog; uniform vec3 uSky; varying vec3 vC; varying vec3 vW; varying float vF;\\n' +\n"
    "    'void main(){ vec3 N = normalize(cross(dFdx(vW), dFdy(vW))); if (dot(N, cameraPosition - vW) < 0.0) N = -N;\\n' +\n"
    "    ' float l = 0.66 + 0.45 * max(dot(N, normalize(vec3(-0.45, 0.8, 0.4))), 0.0) + 0.06 * N.y; vec3 c = vC * l + vec3(0.05, 0.08, 0.02) * max(-N.y, 0.0);\\n' +",
    "  vertexShader: 'attribute vec3 aCol; uniform vec2 aIn; uniform float uT; uniform float uE; varying vec3 vC; varying vec3 vW; varying vec3 vS; varying float vF;\\n' +\n"
    "    'void main(){ mat4 im = mat4(1.0);\\n#ifdef USE_INSTANCING\\n im = instanceMatrix;\\n#endif\\n vec4 w = modelMatrix * im * vec4(position, 1.0); vS = w.xyz;\\n' +\n"
    "    ' w.y += sin(uT * 0.33 + aIn.x) * 1.8 - uE * 70.0; vW = w.xyz; vC = aCol; vF = aIn.y * (1.0 - uE); gl_Position = projectionMatrix * viewMatrix * w; }',\n"
    "  fragmentShader: '#define SPLAT_CELL 0.2\\nuniform vec3 uFog; uniform vec3 uSky; varying vec3 vC; varying vec3 vW; varying vec3 vS; varying float vF;\\n' + SPLAT_GLSL +\n"
    "    'void main(){ vec3 N = normalize(cross(dFdx(vW), dFdy(vW))); if (dot(N, cameraPosition - vW) < 0.0) N = -N;\\n' +\n"
    "    ' float l = 0.66 + 0.45 * max(dot(N, normalize(vec3(-0.45, 0.8, 0.4))), 0.0) + 0.06 * N.y; vec3 c = splatK(vC, l * 0.92 - 0.02 * max(-N.y, 0.0), vS);\\n' +")

import re
s, n = re.subn(r"gradientMap: grad(?=[ ,}])", "gradientMap: grad, defines: { TOON: '', SPLAT_OFF: '' }", s)
assert n == 6, n

sub("hz = clamp(0.14 + (d - 90.0) / 420.0, 0.14, 0.72);   // v51: same aerial haze ramp as the giant",
    "hz = clamp(0.14 + (d - 90.0) / 420.0, 0.14, 0.72) * 0.5;   // v51: same aerial haze ramp as the giant (pixel edition: half, so the splat islands keep their colour)")

sub("sun.shadow.mapSize.set(1024, 1024);\nObject.assign(sun.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9, near: 1, far: 45 });\nsun.shadow.bias = -0.0008;\n",
    "// pixel edition: one 88 m shadow box centred 30 m ahead of the runner and snapped to whole shadow texels, so shadows are already\n"
    "// there long before she reaches them (no shadow edge sweeping over the path) and edges don't crawl while she runs\n"
    "sun.shadow.mapSize.set(2048, 2048);\nObject.assign(sun.shadow.camera, { left: -44, right: 44, top: 44, bottom: -44, near: 1, far: 160 });\n"
    "sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.03;\n"
    "const SUN_L = new THREE.Vector3(-6, 12, 4).normalize(), SUN_F = SUN_L.clone().negate(), SUN_R = new THREE.Vector3().crossVectors(SUN_F, new THREE.Vector3(0, 1, 0)).normalize(),\n"
    "  SUN_U = new THREE.Vector3().crossVectors(SUN_R, SUN_F), SUN_TEX = 88 / 2048, _sunC = new THREE.Vector3();\n"
    "function pixSun(pos, dx, dz) {\n"
    "  const l = Math.hypot(dx, dz) || 1; _sunC.set(pos.x + dx / l * 30, pos.y, pos.z + dz / l * 30);\n"
    "  const a = Math.round(_sunC.dot(SUN_R) / SUN_TEX) * SUN_TEX, b = Math.round(_sunC.dot(SUN_U) / SUN_TEX) * SUN_TEX, c = _sunC.dot(SUN_F);\n"
    "  _sunC.copy(SUN_R).multiplyScalar(a).addScaledVector(SUN_U, b).addScaledVector(SUN_F, c);\n"
    "  sun.target.position.copy(_sunC); sun.position.copy(_sunC).addScaledVector(SUN_L, 70);\n"
    "}\n")
sub("  sun.position.set(pos.x - 6, 12, pos.z + 4); sun.target.position.copy(pos);\n", "  pixSun(pos, cdx, cdz);\n")

if TEST:
    sub("const params = new URLSearchParams('');", "const params = new URLSearchParams(window.__UMA_TEST_PARAMS || '');")

out_path.write_text(s)
print("wrote", out_path, len(s))
