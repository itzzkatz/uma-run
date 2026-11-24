"""Debug additions for the pixel edition (used by make_pixel.py --debug).

The debug page is the same game, plus:
  - its own save: every storage key gets a "dbg:" prefix, so debug runs never touch the real save, best or stats
  - dev URL switches on (god, hell, sw, river, pu; hw = Highway Dash test), and it never posts to the leaderboard
  - a panel: jump to any biome, live readout (biome, distance, speed, FPS, draw calls), and an automatic
    "Tour all biomes" test that runs each stage with the game's god-mode autopilot and ends with a pass/fail report
"""

HEAD_JS = r"""<script>
// ===== DEBUG BUILD: own save ("dbg:" storage prefix), dev switches on, errors collected for the biome tour
(function () {
  try {
    var ls = window.localStorage, P = 'dbg:';
    var keys = function () { var a = []; for (var j = 0; j < ls.length; j++) { var k = ls.key(j); if (k && k.indexOf(P) === 0) a.push(k.slice(P.length)); } return a; };
    var shim = { getItem: function (k) { return ls.getItem(P + k); }, setItem: function (k, v) { ls.setItem(P + k, v); }, removeItem: function (k) { ls.removeItem(P + k); },
      clear: function () { keys().forEach(function (k) { ls.removeItem(P + k); }); }, key: function (i) { var a = keys(); return i < a.length ? a[i] : null; } };
    Object.defineProperty(shim, 'length', { get: function () { return keys().length; } });
    Object.defineProperty(window, 'localStorage', { value: shim, configurable: true });
    var once = JSON.parse(shim.getItem('sakuraSprintOnce') || '{}'); once.tut = 1; shim.setItem('sakuraSprintOnce', JSON.stringify(once));   // no tutorial in debug runs
  } catch (e) {}
  var q = new URLSearchParams(location.search);
  if (q.has('hw')) window.__TEIO_TEST = true;
  window.__dbgErr = [];
  addEventListener('error', function (e) { var m = String(e.message || ''); if (m && m !== 'Script error.') window.__dbgErr.push(m.slice(0, 180)); });
  addEventListener('unhandledrejection', function (e) { var r = e.reason; var m = String((r && r.message) || r || ''); if (!/firebase|gstatic|googlesyndication|Failed to fetch dynamically/i.test(m)) window.__dbgErr.push(('promise: ' + m).slice(0, 180)); });
})();
</script>
"""

PANEL_HTML = r"""<style>
#dbg{position:fixed;left:8px;bottom:8px;z-index:2147483000;font:12px/1.35 ui-monospace,Menlo,Consolas,monospace;color:#eef4ff;
  background:rgba(14,20,38,.86);border:2px solid #7cc4ff;border-radius:10px;padding:8px 9px;max-width:min(360px,calc(100vw - 16px));
  box-shadow:0 4px 14px rgba(0,0,0,.35);user-select:none;-webkit-user-select:none}
#dbg.min .body{display:none}
#dbg .hd{display:flex;align-items:center;gap:8px;cursor:pointer;font-weight:700;color:#ffd54a}
#dbg .hd span{color:#9fb6d8;font-weight:400;margin-left:auto}
#dbg .ro{margin:6px 0;white-space:pre;color:#cfe3ff}
#dbg .row{display:flex;flex-wrap:wrap;gap:5px;margin:5px 0}
#dbg button{font:inherit;font-weight:700;color:#10203a;background:#bfe3ff;border:0;border-radius:7px;padding:5px 8px;cursor:pointer}
#dbg button.on{background:#ffd54a}
#dbg button.tour{background:#7dffa8;width:100%}
#dbg label{display:flex;align-items:center;gap:5px;cursor:pointer}
#dbg select{font:inherit;background:#22304f;color:#eef4ff;border:1px solid #7cc4ff;border-radius:5px}
#dbgRep{position:fixed;inset:0;z-index:2147483001;display:none;align-items:center;justify-content:center;background:rgba(6,10,22,.72)}
#dbgRep .card{background:#101a33;color:#eef4ff;border:2px solid #7cc4ff;border-radius:12px;padding:14px 16px;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;max-width:min(680px,94vw);max-height:88vh;overflow:auto}
#dbgRep h3{margin:0 0 8px;font:700 16px system-ui,sans-serif;color:#ffd54a}
#dbgRep table{border-collapse:collapse;width:100%}
#dbgRep td,#dbgRep th{padding:4px 6px;border-bottom:1px solid #2a3a63;text-align:left;vertical-align:top}
#dbgRep .ok{color:#7dffa8;font-weight:700}#dbgRep .bad{color:#ff7d8a;font-weight:700}
#dbgRep button{margin-top:10px;margin-right:6px;font:700 13px system-ui,sans-serif;background:#bfe3ff;color:#10203a;border:0;border-radius:7px;padding:7px 11px;cursor:pointer}
</style>
<div id="dbg"><div class="hd" id="dbgHd">DEBUG <span id="dbgTag">tap to hide</span></div><div class="body">
  <div class="ro" id="dbgRo">loading…</div>
  <div class="row" id="dbgStages"></div>
  <div class="row"><button class="tour" id="dbgTour">▶ Tour all biomes (auto test)</button></div>
  <div class="row"><label><input type="checkbox" id="dbgGod" checked> God mode + autopilot</label>
    <label>Power-up <select id="dbgPu"><option value="">random</option><option>magnet</option><option>shield</option><option>x2</option></select></label></div>
  <div class="row"><button id="dbgRestart">↻ Restart this test</button><button id="dbgReset">Wipe debug save</button></div>
</div></div>
<div id="dbgRep"><div class="card" id="dbgRepCard"></div></div>
<script>
// ===== DEBUG PANEL (debug build only)
(function () {
  var STAGES = [
    { id: 'jungle', name: 'Jungle', q: '', expect: 'jungle', note: 'starts at 0 m' },
    { id: 'river', name: 'River', q: 'river', expect: 'water', note: 'first river at 90 m' },
    { id: 'inferno', name: 'Inferno', q: 'hell', expect: 'hell', note: 'starts at 4,900 m' },
    { id: 'exit', name: 'Inferno → jungle', q: 'hell&sw=1', expect: 'hell>jungle', note: 'starts at 9,900 m' },
    { id: 'tundra', name: 'Tundra', q: 'hell&sw=ice', expect: 'ice', note: '100 m before the tundra' },
    { id: 'highway', name: 'Highway Dash', q: 'hw', hash: '#now&auto', expect: 'highway', note: "Teio's secret dash" }
  ];
  var BIO = { jungle: 'Jungle', hell: 'Inferno', ice: 'Tundra' };
  var q = new URLSearchParams(location.search), $ = function (id) { return document.getElementById(id); };
  var cur = null; STAGES.forEach(function (s) { if (q.get('stage') === s.id) cur = s; });
  var tourI = q.has('tour') ? +q.get('tour') : -1;
  $('dbgGod').checked = q.has('stage') ? q.has('god') : true;
  if (q.get('pu')) $('dbgPu').value = q.get('pu');
  function url(s, tour) {
    var p = ['stage=' + s.id]; if (s.q) p.push(s.q); if ($('dbgGod').checked || tour !== undefined) p.push('god');
    if ($('dbgPu').value) p.push('pu=' + $('dbgPu').value); p.push('go'); if (tour !== undefined) p.push('tour=' + tour);
    return location.pathname + '?' + p.join('&') + (s.hash || '');
  }
  STAGES.forEach(function (s) {
    var b = document.createElement('button'); b.textContent = s.name; b.title = s.note; if (cur && cur.id === s.id) b.className = 'on';
    b.onclick = function () { sessionStorage.removeItem('dbgTour'); location.href = url(s); }; $('dbgStages').appendChild(b);
  });
  $('dbgHd').onclick = function () { $('dbg').classList.toggle('min'); $('dbgTag').textContent = $('dbg').classList.contains('min') ? 'tap to show' : 'tap to hide'; };
  $('dbgTour').onclick = function () { sessionStorage.setItem('dbgTour', '[]'); location.href = url(STAGES[0], 0); };
  $('dbgRestart').onclick = function () { location.reload(); };
  $('dbgReset').onclick = function () { localStorage.clear(); location.reload(); };
  // ---- live readout
  var fr = 0, fps = 0, t0 = performance.now(), fpsLog = [];
  (function tick() { fr++; var t = performance.now(); if (t - t0 >= 1000) { fps = fr * 1000 / (t - t0); fr = 0; t0 = t; if (G() && G().P && window.__dbg) { var st = window.__dbg.state(); if (st === 'play') fpsLog.push(fps); } } requestAnimationFrame(tick); })();
  function G() { return window.__game; }
  var seen = {}, water = false, hw = false, firstD = null, order = [], metAt = null, started = performance.now();
  function expectMet(s) {
    if (!s) return false;
    if (s.expect === 'water') return water; if (s.expect === 'highway') return hw;
    if (s.expect === 'hell>jungle') return order.indexOf('hell') >= 0 && order.lastIndexOf('jungle') > order.indexOf('hell');
    return !!seen[s.expect];
  }
  setInterval(function () {
    var g = G(), d = window.__dbg; if (!g || !d) return;
    var P = g.P, b = d.biome(); if (d.state() === 'play') { seen[b] = 1; if (order[order.length - 1] !== b) order.push(b); if (d.water()) water = true; if (d.hw()) hw = true; if (firstD === null) firstD = P.dist; }
    var inf = d.info();
    $('dbgRo').textContent = (cur ? 'Test: ' + cur.name + (tourI >= 0 ? '  (tour ' + (tourI + 1) + '/' + STAGES.length + ')' : '') + '\n' : 'Pick a biome test below\n') +
      'Biome ' + (BIO[b] || b) + (d.water() ? ' · river' : '') + (d.hw() ? ' · HIGHWAY' : '') + ' · ' + Math.floor(P.dist) + ' m · ' + (P.speed || 0).toFixed(1) + ' m/s\n' +
      'FPS ' + fps.toFixed(0) + ' · ' + inf.calls + ' draws · ' + (inf.tris / 1000).toFixed(0) + 'k tris\n' +
      'Art ' + inf.w + '×' + inf.h + ' px, ×' + inf.z + ' · state ' + d.state() + (window.__dbgErr.length ? ' · ERRORS ' + window.__dbgErr.length : '') +
      (cur ? '\nCheck: ' + (expectMet(cur) ? 'PASS ✓' : 'waiting for ' + cur.expect + '…') : '');
    // ---- tour: move on 80 m after the stage's check passes, or after 150 s
    if (tourI >= 0 && cur && firstD !== null) {
      if (expectMet(cur) && metAt === null) metAt = P.dist;
      var done = (metAt !== null && P.dist - metAt >= 80) || performance.now() - started > 150000;
      if (done && !window.__dbgTourDone) { window.__dbgTourDone = 1; finishStage(); }
    }
  }, 250);
  function finishStage() {
    var log = JSON.parse(sessionStorage.getItem('dbgTour') || '[]'), f = fpsLog.slice(1);
    var avg = f.length ? f.reduce(function (a, b) { return a + b; }, 0) / f.length : 0, min = f.length ? Math.min.apply(null, f) : 0;
    log.push({ id: cur.id, name: cur.name, pass: expectMet(cur), seen: order.map(function (b) { return BIO[b] || b; }).join(' → ') + (water ? ' + river' : '') + (hw ? ' + highway' : ''),
      from: Math.floor(firstD), to: Math.floor(G().P.dist), avg: Math.round(avg), min: Math.round(min), errors: window.__dbgErr.slice(0, 5) });
    sessionStorage.setItem('dbgTour', JSON.stringify(log));
    var next = STAGES[tourI + 1];
    if (next) location.href = url(next, tourI + 1); else showReport(log);
  }
  function showReport(log) {
    var ok = log.every(function (r) { return r.pass && !r.errors.length; });
    var h = '<h3>Biome tour: ' + (ok ? '<span class="ok">ALL PASS</span>' : '<span class="bad">SOME CHECKS FAILED</span>') + '</h3><table><tr><th>Test</th><th>Result</th><th>Seen</th><th>Distance</th><th>FPS avg/min</th></tr>';
    log.forEach(function (r) { h += '<tr><td>' + r.name + '</td><td class="' + (r.pass && !r.errors.length ? 'ok">PASS' : 'bad">FAIL') + '</td><td>' + r.seen + '</td><td>' + r.from + '–' + r.to + ' m</td><td>' + r.avg + ' / ' + r.min + '</td></tr>' +
      (r.errors.length ? '<tr><td></td><td colspan="4" class="bad">' + r.errors.join('<br>') + '</td></tr>' : ''); });
    h += '</table><button id="dbgRepCopy">Copy report</button><button id="dbgRepClose">Close</button>';
    $('dbgRepCard').innerHTML = h; $('dbgRep').style.display = 'flex';
    $('dbgRepClose').onclick = function () { $('dbgRep').style.display = 'none'; };
    $('dbgRepCopy').onclick = function () { var t = log.map(function (r) { return r.name + ': ' + (r.pass && !r.errors.length ? 'PASS' : 'FAIL') + ' | ' + r.seen + ' | ' + r.from + '-' + r.to + ' m | fps ' + r.avg + '/' + r.min + (r.errors.length ? ' | ' + r.errors.join('; ') : ''); }).join('\n');
      try { navigator.clipboard.writeText(t); this.textContent = 'Copied'; } catch (e) {} };
    window.__dbgReport = log;
  }
  // ---- auto start (?go): skip the guest / controls prompts, then start the run
  if (q.has('go')) {
    var tries = 0, iv = setInterval(function () {
      var g = G(); if (!g || !g.startGame || !window.__dbg) { if (++tries > 240) clearInterval(iv); return; }
      var gb = $('guestBtn'); if (gb && gb.offsetParent) { gb.click(); return; }
      var ps = $('pickSwipe'); if (ps && ps.offsetParent) { ps.click(); return; }
      clearInterval(iv); if (window.__dbg.state() !== 'play') g.startGame(); started = performance.now();
    }, 400);
  }
})();
</script>
"""

# exposes the bits the panel reads; inserted next to the game's own window.__game hook
STATE_JS = ("renderer.info.autoReset = false;   // debug: count every pass of a frame\n"
            "window.__dbg = { biome: () => biomeAt(P.dist), water: () => !!P.inWater, hw: () => !!HWD.on, state: () => state, segs: () => segments.length,\n"
            "  info: () => ({ calls: renderer.info.render.calls, tris: renderer.info.render.triangles, w: PIX.w, h: PIX.h, z: PIX.z }),\n"
            "  embersOnPath: () => { if (!embers.visible) return null; const p = embers.userData.pos, M = HW; let n = 0, up = 0;\n"
            "    for (let i = 0; i < p.length; i += 3) { if (p[i + 1] < -0.5) continue; up++; for (const g of segments) { const dx = p[i] - g.start.x, dz = p[i + 2] - g.start.z,\n"
            "      s = dx * g.dir.x + dz * g.dir.z, l = dx * g.right.x + dz * g.right.z; if (s > -M && s < g.L + M && Math.abs(l) < M) { n++; break; } } } return { onPath: n, shown: up }; } };\n")
