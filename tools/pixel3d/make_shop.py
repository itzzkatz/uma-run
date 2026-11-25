"""Add the paid Uma Capsule shop (Xsolla, through the uma-run-shop Cloudflare Worker) to the original Uma Run file.

Usage: python3 make_shop.py <uma-run.html> <out.html> [--api https://uma-run-shop.<you>.workers.dev] [--test]

What it adds, all inside the existing capsule machine (Characters tab):
  - BUY CAPSULE · $1.99: needs a signed-in account (so the purchase is saved), opens Xsolla's payment page in a new tab
  - OPEN PAID CAPSULE ×N: spends a paid capsule (checked by the server) on a random uma you don't own, same reveal as a carrot pull
  - paid umas are restored on any device when the player signs in
  - hidden entirely while window.UMA_SHOP.api is empty, or once the collection is complete
--test lets the headless tests fake a signed-in player (window.__UMA_SHOP_TEST); never use it for a published build.
"""
import re
import sys
from pathlib import Path

args = sys.argv[1:]
src, out = Path(args[0]), Path(args[1])
API = args[args.index("--api") + 1] if "--api" in args else ""
TEST = "--test" in args
s = src.read_text()


def sub(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor found {n}x: {old[:80]!r}")
    s = s.replace(old, new)


# ---------------------------------------------------------------- config (next to FIREBASE_CONFIG)
sub("</script>\n<meta name=\"viewport\"",
    "/* UMA_SHOP: paid Uma Capsules through Xsolla. api = your uma-run-shop Cloudflare Worker URL (see shop-worker/README.md).\n"
    "   Leave api empty to hide the shop. The real price is set in Xsolla; price here is only the button label. */\n"
    f"window.UMA_SHOP = {{ api: {API!r}, price: '$1.99' }};\n"
    "</script>\n<meta name=\"viewport\"")

# ---------------------------------------------------------------- styles
sub("  .gInfo .cName{margin:0 0 1px}\n",
    "  .gInfo .cName{margin:0 0 1px}\n"
    "  .gShop{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.gShop.hidden{display:none}\n"
    "  .gShop .gbtn{font-size:15px;padding:7px 14px;letter-spacing:.5px}\n"
    "  .gShop .gbtn .sb{font-size:12px;opacity:.9;margin-left:4px}\n"
    "  .gShopNote{font-size:11.5px;font-weight:800;color:#6b7488;min-height:1.2em}.gShopNote.bad{color:#d8325a}.gShopNote.good{color:#2e9a3a}\n")

# ---------------------------------------------------------------- markup: under the PULL button
sub("          <button id=\"gPull\" class=\"gbtn gold big\">PULL</button>\n          <div class=\"cState\" id=\"gState\"></div>\n",
    "          <button id=\"gPull\" class=\"gbtn gold big\">PULL</button>\n          <div class=\"cState\" id=\"gState\"></div>\n"
    "          <div class=\"gShop hidden\" id=\"gShop\"><button id=\"gOpenPaid\" class=\"gbtn pink hidden\">🎟 OPEN PAID CAPSULE <span class=\"sb\" id=\"gPaidN\"></span></button>"
    "<button id=\"gBuy\" class=\"gbtn purple\">🛒 BUY CAPSULE <span class=\"sb\" id=\"gPrice\"></span></button></div>\n"
    "          <div class=\"gShopNote\" id=\"gShopNote\"></div>\n")

# ---------------------------------------------------------------- logic
SHOP_JS = r"""
// ---------------------------------------------------------------- paid Uma Capsules (Xsolla through the uma-run-shop Cloudflare Worker)
// The Worker credits capsules only from Xsolla's signed payment notice, once per order; it also remembers every uma opened from a paid
// capsule, so signing in on any device restores them. The game never sees the price or any key: the button label is cosmetic.
var SHOP = { n: 0, umas: [], busy: false, poll: null, sandbox: true, price: (window.UMA_SHOP && window.UMA_SHOP.price) || '$1.99' };
const shopApi = () => String((window.UMA_SHOP && window.UMA_SHOP.api) || '').replace(/\/+$/, '');
function shopNote(t, k = '') { const n = $('gShopNote'); if (n) { n.textContent = t; n.className = 'gShopNote ' + k; } }
async function shopToken() {
  if (window.__UMA_SHOP_TEST) return window.__UMA_SHOP_TEST.token;
  return FB.user ? FB.user.getIdToken() : null;
}
const shopSignedIn = () => !!(window.__UMA_SHOP_TEST || FB.user);
async function shopCall(path, body) {
  const tok = await shopToken(); if (!tok) throw Object.assign(new Error('signed_out'), { code: 'signed_out' });
  const r = await fetch(shopApi() + path, { method: body === undefined ? 'GET' : 'POST', headers: { authorization: 'Bearer ' + tok, ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.message || 'shop error'), { code: j.error || 'error', status: r.status });
  return j;
}
function shopApply(j) {                                  // balance + restore umas opened from paid capsules on any device
  SHOP.n = j.capsules || 0; SHOP.umas = j.umas || []; SHOP.sandbox = j.sandbox !== false;
  let added = 0; for (const id of SHOP.umas) if (SKINS.some(k => k.id === id) && !save.owned.includes(id)) { save.owned.push(id); added++; }
  if (added) { persist(); achCheck(); }
  renderShop(); if (added && typeof renderChars === 'function') renderChars();
  return added;
}
async function shopRefresh() {
  if (!SHOP) return null;
  if (!shopApi() || !shopSignedIn()) { SHOP.n = 0; renderShop(); return null; }
  try { return shopApply(await shopCall('/me')); } catch (e) { renderShop(); return null; }
}
function renderShop() {
  const box = $('gShop'); if (!box || !SHOP) return;
  const on = !!shopApi(), done = !unownedSkins().length;
  box.classList.toggle('hidden', !on || (done && !SHOP.n));
  $('gPrice').textContent = '· ' + SHOP.price + (SHOP.sandbox ? ' (test)' : '');
  $('gBuy').classList.toggle('hidden', done);
  $('gBuy').disabled = SHOP.busy;
  $('gOpenPaid').classList.toggle('hidden', !SHOP.n || done);
  $('gOpenPaid').disabled = SHOP.busy || gLock;
  $('gPaidN').textContent = '×' + SHOP.n;
}
async function shopBuy() {
  if (SHOP.busy || !shopApi()) return;
  if (!shopSignedIn()) { openAcct('up'); acctMsg('Create an account or sign in first, so the capsules you buy are saved to it.', 'info'); return; }
  // open the payment tab right away (inside the tap) so pop-up blockers allow it, then point it at Xsolla.
  // No size given, so browsers open a normal tab in this window instead of a separate pop-up window.
  const w = window.__UMA_SHOP_TEST ? null : window.open('', 'umaPay');
  SHOP.busy = true; renderShop(); shopNote('Opening the payment tab…');
  try {
    const { url } = await shopCall('/buy', {});
    if (window.__UMA_SHOP_TEST) window.__UMA_SHOP_TEST.opened = url;
    else if (w && !w.closed) w.location.href = url; else window.location.href = url;
    shopNote('Finish paying in the new tab, then come back to this one. Your capsule appears here as soon as Xsolla confirms it.');
    shopWatch(w);
  } catch (e) {
    if (w && !w.closed) w.close();
    shopNote(e.code === 'signed_out' || e.status === 401 ? 'Please sign in again, then retry.' : e.code === 'not_configured' ? 'The shop is not set up yet.' : 'Could not reach the shop. Try again in a moment.', 'bad');
  } finally { SHOP.busy = false; renderShop(); }
}
function shopWatch(w) {                                  // poll the balance while paying, and for a while after the payment tab closes
  clearInterval(SHOP.poll); const start = SHOP.n + SHOP.umas.length, t0 = Date.now(); let closedAt = 0;
  SHOP.poll = setInterval(async () => {
    if (w && w.closed && !closedAt) closedAt = Date.now();
    const j = await shopCall('/me').catch(() => null);
    if (j && (j.capsules || 0) + (j.umas || []).length > start) {
      clearInterval(SHOP.poll); shopApply(j); shopNote('Payment received: your capsule is ready! Tap OPEN PAID CAPSULE.', 'good');
      storeMsg('Uma Capsule added!', 'good'); sfx(1320, 0.12, 'triangle', 0.12, 1760); return;
    }
    if (Date.now() - t0 > 15 * 60000 || (closedAt && Date.now() - closedAt > 120000)) {
      clearInterval(SHOP.poll); shopNote('No payment yet. If you paid, it will show up the next time you open the shop.');
    }
  }, 3000);
}
async function shopOpen(btn) {
  if (gLock || SHOP.busy || !SHOP.n) return;
  const left = unownedSkins(); if (!left.length) { renderShop(); return; }
  gLock = true; SHOP.busy = true; renderShop(); renderChars();
  const sk = left[gRand(left.length)];
  try {
    const j = await shopCall('/open', { uma: sk.id });
    SHOP.busy = false; shopApply(j);
    if (!save.owned.includes(sk.id)) save.owned.push(sk.id);
    save.pulls = (save.pulls || 0) + 1; persist(); achCheck(); gLast = sk.id; renderChars(); gachaReveal(sk); shopNote('');
  } catch (e) {
    gLock = false; SHOP.busy = false;
    shopNote(e.code === 'no_capsules' ? 'No paid capsules left.' : 'Could not open the capsule. Check your connection and try again (nothing was spent).', 'bad');
    shopRefresh(); renderChars();
  }
}
$('gBuy').addEventListener('click', e => { e.stopPropagation(); shopBuy(); });
$('gOpenPaid').addEventListener('click', e => { e.stopPropagation(); shopOpen(e.currentTarget); });
"""
sub("$('gPull').addEventListener('click', e => { e.stopPropagation(); gachaPull(e.currentTarget); });\n",
    "$('gPull').addEventListener('click', e => { e.stopPropagation(); gachaPull(e.currentTarget); });\n" + SHOP_JS)

# keep the shop row in step with the machine
sub("  $('gTipCost').textContent = fmt(cost);\n", "  $('gTipCost').textContent = fmt(cost);\n  if (typeof renderShop === 'function') renderShop();\n")
# signed in or out: refresh the paid balance and restore paid umas
sub("  try { await mergeGuest(u, first); } catch (e) { $('profMsg').textContent = 'Cloud sync failed, will retry next time.'; }\n",
    "  try { await mergeGuest(u, first); } catch (e) { $('profMsg').textContent = 'Cloud sync failed, will retry next time.'; }\n"
    "  shopRefresh();\n")
sub("    refreshAcctUI(); return;\n  }\n  const first = save.acct.uid !== u.uid;",
    "    refreshAcctUI(); if (typeof shopRefresh === 'function') shopRefresh(); return;\n  }\n  const first = save.acct.uid !== u.uid;")

if TEST:
    # the headless tests have no Firebase: they inject a fake signed-in player and refresh the shop themselves
    s = s.replace("$('gOpenPaid').addEventListener('click',", "window.__shopRefresh = () => shopRefresh();\n$('gOpenPaid').addEventListener('click',", 1)

out.write_text(s)
print("wrote", out, len(s), "api:", API or "(empty: shop hidden)")
