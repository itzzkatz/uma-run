"""Headless Chrome check of the 3D game: load, start a run, take screenshots, print console errors.
Usage: python3 shot.py <page.html> <tag> [params] [--phone] [--secs N]"""
import json, subprocess, sys, time
from playwright.sync_api import sync_playwright

page_name, tag = sys.argv[1], sys.argv[2]
prm = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else ''
phone = '--phone' in sys.argv
secs = int(sys.argv[sys.argv.index('--secs') + 1]) if '--secs' in sys.argv else 8
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8790", "--bind", "127.0.0.1"], cwd="/home/claude/uma/pixel3d",
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
init = """
try { localStorage.setItem('sakuraSprintOnce', JSON.stringify({tut: 1, corner: 1, stumble: 1, catch: 1, behind: 1, ctl: 1}));
      localStorage.setItem('sakuraSprintTilt', 'swipe'); } catch (e) {}
window.__UMA_TEST_PARAMS = %s;
""" % json.dumps(prm)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome",
                              args=["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"])
        vp = {"width": 390, "height": 844} if phone else {"width": 1280, "height": 760}
        ctx = b.new_context(viewport=vp, device_scale_factor=(3 if phone else 1), has_touch=phone, is_mobile=phone)
        ctx.add_init_script(init)
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.type + ': ' + m.text) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errs.append('pageerror: ' + str(e)))
        pg.on("response", lambda r: errs.append('http %d %s' % (r.status, r.url[:120])) if r.status >= 400 else None)
        pg.on("requestfailed", lambda r: errs.append('failed ' + r.url[:120]))
        t0 = time.time()
        pg.goto(f"http://127.0.0.1:8790/{page_name}")
        try:
            for _ in range(60):
                pg.wait_for_timeout(1000)
                if pg.evaluate("!!(window.__game && window.__game.startGame)"): break
            else: raise Exception('timeout')
        except Exception as ex:
            print('NOT LOADED'); [print('  ', e[:400]) for e in errs[:20]]; pg.screenshot(path=f"/tmp/{tag}_fail.png"); raise SystemExit(1)
        print('loaded in', round(time.time() - t0, 1), 's')
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"/tmp/{tag}_menu.png")
        pg.evaluate("(() => { const g = document.getElementById('guestBtn'); if (g && g.offsetParent) g.click(); })()")
        pg.wait_for_timeout(800)
        pg.evaluate("(() => { const g = document.getElementById('pickSwipe'); if (g && g.offsetParent) g.click(); })()")
        pg.wait_for_timeout(800)
        pg.evaluate("window.__game.startGame()")
        for i in range(secs):
            pg.wait_for_timeout(1000)
            if i in (1, secs // 2, secs - 1):
                pg.screenshot(path=f"/tmp/{tag}_{i}.png")
        st = pg.evaluate("({d: window.__game.P.dist, sp: window.__game.P.speed, death: window.__game.P.death})")
        fps = pg.evaluate("new Promise(r=>{let n=0,t=performance.now();function f(){n++; if(performance.now()-t<2000) requestAnimationFrame(f); else r(n/2);} requestAnimationFrame(f);})")
        print('state', st, 'fps', fps)
        for e in errs[:12]: print('  ', e[:300])
        b.close()
finally:
    srv.terminate()
