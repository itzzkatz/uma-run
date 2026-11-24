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
// ~0.8 on half-lit sides, ~0.96 in full sun), dither the tone edges per splat, and sprinkle a few lighter splats
vec3 splatK(vec3 base, float k, vec3 w){
  float h = spCell(w), t = k < SPLAT_K ? (k - 0.14) / 0.36 : 2.0 + (k - SPLAT_K) / 0.14;
  t += (h - 0.5) * 0.3;
#ifdef SPLAT_BLOTCH
  float bl = spNoise(w.xz / 9.0) * 0.65 + spNoise(w.xz / 3.1) * 0.35; t -= step(0.56, bl) * 0.6 + step(0.74, bl) * 0.35;
#endif
  float s = clamp(floor(t), 0.0, 3.0);
  if (h > 0.94) s = min(3.0, s + 1.0);          // a sprinkle of lighter splats (no dark ones: they read as black splotches)
  return spTone(base, s);
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
sub("const renderer = new THREE.WebGLRenderer({ antialias: true });\n"
    "renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));\n"
    "renderer.setSize(innerWidth, innerHeight);\n",
    "const renderer = new THREE.WebGLRenderer({ antialias: false });\n"
    "renderer.setPixelRatio(1);\n"
    "// pixel art: the world renders at ~230 px on the short side, then every art pixel is drawn as a whole block of screen pixels\n"
    "const PIX = { z: 3, w: 2, h: 2 };\n"
    "const pixRT = new THREE.WebGLRenderTarget(2, 2, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthTexture: new THREE.DepthTexture(2, 2) });\n"
    "pixRT.texture.colorSpace = THREE.SRGBColorSpace;\n"
    "const pixU = { tCol: { value: pixRT.texture }, tDep: { value: pixRT.depthTexture }, uRes: { value: new THREE.Vector2(2, 2) }, uNF: { value: new THREE.Vector2(0.1, 600) }, uFog: { value: new THREE.Vector2(48, 220) } };\n"
    "const pixScene = new THREE.Scene(), pixCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);\n"
    "pixScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({ uniforms: pixU, depthTest: false, depthWrite: false,\n"
    "  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',\n"
    "  fragmentShader: 'uniform sampler2D tCol; uniform sampler2D tDep; uniform vec2 uRes; uniform vec2 uNF; uniform vec2 uFog; varying vec2 vUv;\\n' +\n"
    "    'float lin(float d){ return uNF.x * uNF.y / (uNF.y - d * (uNF.y - uNF.x)); }\\n' +\n"
    "    'void main(){ vec2 px = 1.0 / uRes; vec3 c = texture2D(tCol, vUv).rgb; float d0 = lin(texture2D(tDep, vUv).x), dn = d0; vec3 nc = c;\\n' +\n"
    "    ' for (int i = 0; i < 4; i++) { vec2 o = i == 0 ? vec2(px.x, 0.0) : i == 1 ? vec2(-px.x, 0.0) : i == 2 ? vec2(0.0, px.y) : vec2(0.0, -px.y);\\n' +\n"
    "    '  float d = lin(texture2D(tDep, vUv + o).x); if (d < dn) { dn = d; nc = texture2D(tCol, vUv + o).rgb; } }\\n' +\n"
    "    // ink where a nearer surface ends: this pixel is the 1 px rim around it, coloured as a dark version of that surface\n"
    "    ' float edge = step(0.07 * d0 + 0.35, d0 - dn) * (1.0 - 0.75 * smoothstep(uFog.x, uFog.y, dn));\\n' +\n"
    "    ' vec3 ink = nc * vec3(0.085, 0.07, 0.1) + vec3(0.002, 0.001, 0.004);\\n' +\n"
    "    ' gl_FragColor = vec4(mix(c, ink, edge), 1.0);\\n#include <colorspace_fragment>\\n}' })));\n"
    "function pixSize() {\n"
    "  const dpr = window.devicePixelRatio || 1, Wd = Math.round(innerWidth * dpr), Hd = Math.round(innerHeight * dpr);\n"
    "  if (!Wd || !Hd) return;\n"
    "  PIX.z = Math.max(2, Math.round(Math.min(Wd, Hd) / 230)); PIX.w = Math.ceil(Wd / PIX.z); PIX.h = Math.ceil(Hd / PIX.z);\n"
    "  renderer.setSize(PIX.w, PIX.h, false); pixRT.setSize(PIX.w, PIX.h); pixU.uRes.value.set(PIX.w, PIX.h);\n"
    "  const st = renderer.domElement.style; st.width = (PIX.w * PIX.z / dpr) + 'px'; st.height = (PIX.h * PIX.z / dpr) + 'px';\n"
    "}\n"
    "function pixRender(sc, cam) {\n"
    "  pixU.uNF.value.set(cam.near, cam.far); if (sc.fog) pixU.uFog.value.set(sc.fog.near, sc.fog.far);\n"
    "  renderer.setRenderTarget(pixRT); renderer.render(sc, cam); renderer.setRenderTarget(null); renderer.render(pixScene, pixCam);\n"
    "}\n"
    "renderer.domElement.style.imageRendering = 'pixelated';\n"
    "pixSize();\n")
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

if TEST:
    sub("const params = new URLSearchParams('');", "const params = new URLSearchParams(window.__UMA_TEST_PARAMS || '');")

out_path.write_text(s)
print("wrote", out_path, len(s))
