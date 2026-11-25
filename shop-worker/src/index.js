// Uma Run shop: a Cloudflare Worker between the game, Firebase sign-in and Xsolla.
//
//   GET  /me                 (signed in) -> { capsules, purchased, umas, sandbox, price }      capsule balance + umas to restore
//   POST /buy                (signed in) -> { url, orderId, sandbox }                           Xsolla payment window for one Uma Capsule
//   POST /open  { uma }      (signed in) -> { ok, capsules, umas }                              spend one paid capsule on an uma
//   POST /xsolla/webhook     (Xsolla)    -> user_validation, order_paid, order_canceled         signed with the webhook secret
//
// "Signed in" means an `Authorization: Bearer <Firebase ID token>` header from the game's existing Firebase accounts.
// Capsules are only ever credited by a signed order_paid webhook, once per Xsolla order.
//
// Bindings (wrangler.toml / dashboard):  DB (D1 database)
// Variables: XSOLLA_PROJECT_ID, FIREBASE_PROJECT_ID, CAPSULE_SKU, UMA_IDS, SANDBOX ("true" until you go live),
//            ALLOWED_ORIGINS ("*" or a comma list), PRICE_LABEL, RETURN_URL (optional)
// Secrets:   XSOLLA_API_KEY, XSOLLA_WEBHOOK_SECRET   (set them yourself: never put them in code or in the game)

const JWKS_URL = 'https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com';
let jwksCache = { keys: null, until: 0 };

// Built-in settings, so the Worker runs with no dashboard variables. A variable of the same name set on the
// Worker (Settings -> Variables and Secrets) overrides each one, e.g. SANDBOX = false when Xsolla approves live payments.
const DEFAULTS = {
  XSOLLA_PROJECT_ID: '320064',
  FIREBASE_PROJECT_ID: 'umarun-b6d8a',
  CAPSULE_SKU: 'uma_capsule',
  UMA_IDS: 'goldship,tamamo,seiun,teio,oguri,digital,tachyon,vivlos,pandora',
  PRICE_LABEL: '$1.99',
  SANDBOX: 'true',
  ALLOWED_ORIGINS: '*',
};
const withDefaults = env => new Proxy(env || {}, { get: (t, k) => (t[k] !== undefined && t[k] !== '' ? t[k] : DEFAULTS[k]) });

export default {
  async fetch(request, rawEnv, ctx) {
    const env = withDefaults(rawEnv);
    const url = new URL(request.url);
    const cors = corsHeaders(request, env);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      if (url.pathname === '/xsolla/webhook' && request.method === 'POST') return await webhook(request, env);
      if (url.pathname === '/me' && request.method === 'GET') return json(await me(await player(request, env), env), 200, cors);
      if (url.pathname === '/buy' && request.method === 'POST') return json(await buy(request, await player(request, env), env), 200, cors);
      if (url.pathname === '/open' && request.method === 'POST') return json(await open(request, await player(request, env), env), 200, cors);
      if (url.pathname === '/' || url.pathname === '/health') return json({ ok: true, service: 'uma-run-shop', sandbox: isSandbox(env), db: !!env.DB, keys: { api: !!env.XSOLLA_API_KEY, webhook: !!env.XSOLLA_WEBHOOK_SECRET } }, 200, cors);
      return json({ error: 'not_found' }, 404, cors);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.code, message: e.message }, e.status, cors);
      console.error('shop error', e && e.stack || e);
      return json({ error: 'server_error' }, 500, cors);
    }
  },
};

class HttpError extends Error { constructor(status, code, message) { super(message || code); this.status = status; this.code = code; } }
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });
const isSandbox = env => String(env.SANDBOX ?? 'true').toLowerCase() !== 'false';
const umaIds = env => String(env.UMA_IDS || '').split(',').map(s => s.trim()).filter(Boolean);
const now = () => Math.floor(Date.now() / 1000);

function corsHeaders(request, env) {
  const origin = request.headers.get('origin') || '';
  const allowed = String(env.ALLOWED_ORIGINS || '*').split(',').map(s => s.trim()).filter(Boolean);
  const ok = allowed.includes('*') ? '*' : (allowed.includes(origin) ? origin : '');
  const h = { 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'authorization, content-type', 'access-control-max-age': '86400', vary: 'origin' };
  if (ok) h['access-control-allow-origin'] = ok;
  return h;
}

// ------------------------------------------------------------------ Firebase ID token check (RS256, Google's public keys)
const b64url = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4)), c => c.charCodeAt(0));
async function googleKeys() {
  if (jwksCache.keys && Date.now() < jwksCache.until) return jwksCache.keys;
  const r = await fetch(JWKS_URL);
  if (!r.ok) throw new HttpError(503, 'auth_unavailable', 'Could not load Google sign-in keys');
  const maxAge = Number((/max-age=(\d+)/.exec(r.headers.get('cache-control') || '') || [])[1] || 3600);
  const { keys } = await r.json();
  jwksCache = { keys, until: Date.now() + Math.min(maxAge, 6 * 3600) * 1000 };
  return keys;
}
export async function verifyFirebaseToken(token, projectId) {
  const parts = String(token || '').split('.');
  if (parts.length !== 3) throw new HttpError(401, 'signed_out', 'Sign in to buy capsules');
  let header, claims;
  try { header = JSON.parse(new TextDecoder().decode(b64url(parts[0]))); claims = JSON.parse(new TextDecoder().decode(b64url(parts[1]))); }
  catch (e) { throw new HttpError(401, 'bad_token', 'Invalid sign-in token'); }
  if (header.alg !== 'RS256' || !header.kid) throw new HttpError(401, 'bad_token', 'Invalid sign-in token');
  const jwk = (await googleKeys()).find(k => k.kid === header.kid);
  if (!jwk) { jwksCache.until = 0; throw new HttpError(401, 'bad_token', 'Unknown sign-in key, sign in again'); }
  const key = await crypto.subtle.importKey('jwk', { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: 'RS256', ext: true }, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64url(parts[2]), new TextEncoder().encode(parts[0] + '.' + parts[1]));
  if (!ok) throw new HttpError(401, 'bad_token', 'Invalid sign-in token');
  const t = now();
  if (claims.aud !== projectId || claims.iss !== 'https://securetoken.google.com/' + projectId) throw new HttpError(401, 'bad_token', 'Token is for another project');
  if (!(claims.exp > t - 30) || !(claims.iat <= t + 300) || !claims.sub || typeof claims.sub !== 'string' || claims.sub.length > 128)
    throw new HttpError(401, 'expired', 'Sign-in expired, try again');
  return { uid: claims.sub, email: claims.email || '' };
}
async function player(request, env) {
  const m = /^Bearer\s+(.+)$/i.exec(request.headers.get('authorization') || '');
  return verifyFirebaseToken(m && m[1], env.FIREBASE_PROJECT_ID);
}

// ------------------------------------------------------------------ player state
async function state(env, uid) {
  const row = await env.DB.prepare('SELECT purchased FROM players WHERE uid = ?').bind(uid).first();
  const { results } = await env.DB.prepare('SELECT uma FROM unlocks WHERE uid = ? ORDER BY at, rowid').bind(uid).all();
  const umas = (results || []).map(r => r.uma), purchased = row ? row.purchased : 0;
  return { purchased, capsules: Math.max(0, purchased - umas.length), umas };
}
async function me(p, env) {
  return { ...(await state(env, p.uid)), sandbox: isSandbox(env), price: env.PRICE_LABEL || '$1.99' };
}

// ------------------------------------------------------------------ buy: ask Xsolla for a payment token for one capsule
async function buy(request, p, env) {
  if (!env.XSOLLA_API_KEY) throw new HttpError(503, 'not_configured', 'The shop is not set up yet');
  const t = now();
  // the player row is what user_validation checks: only signed-in players who started a purchase are valid
  await env.DB.prepare('INSERT INTO players (uid, email, purchased, created, updated) VALUES (?, ?, 0, ?, ?) ON CONFLICT(uid) DO UPDATE SET email = excluded.email, updated = excluded.updated')
    .bind(p.uid, p.email, t, t).run();
  const cf = request.cf || {}, ip = request.headers.get('cf-connecting-ip') || '';
  const body = {
    sandbox: isSandbox(env),
    user: { id: { value: p.uid }, ...(p.email ? { email: { value: p.email } } : {}),
      ...(/^\d+\.\d+\.\d+\.\d+$/.test(ip) ? {} : { country: { value: (cf.country && /^[A-Z]{2}$/.test(cf.country) ? cf.country : 'US'), allow_modify: true } }) },
    purchase: { items: [{ sku: env.CAPSULE_SKU || 'uma_capsule', quantity: 1 }] },
    settings: { language: 'en', ...(env.RETURN_URL ? { return_url: env.RETURN_URL } : {}) },
  };
  const headers = { 'content-type': 'application/json', authorization: 'Basic ' + btoa(env.XSOLLA_PROJECT_ID + ':' + env.XSOLLA_API_KEY) };
  if (/^\d+\.\d+\.\d+\.\d+$/.test(ip)) headers['x-user-ip'] = ip;
  const r = await fetch(`https://store.xsolla.com/api/v3/project/${env.XSOLLA_PROJECT_ID}/admin/payment/token`, { method: 'POST', headers, body: JSON.stringify(body) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok || !out.token) { console.error('xsolla token failed', r.status, JSON.stringify(out)); throw new HttpError(502, 'payment_unavailable', 'The payment service did not answer, try again'); }
  const host = isSandbox(env) ? 'https://sandbox-secure.xsolla.com' : 'https://secure.xsolla.com';
  return { url: `${host}/paystation4/?token=${encodeURIComponent(out.token)}`, orderId: out.order_id, sandbox: isSandbox(env) };
}

// ------------------------------------------------------------------ open: spend one paid capsule on an uma the player picked (no duplicates)
async function open(request, p, env) {
  const { uma } = await request.json().catch(() => ({}));
  if (!umaIds(env).includes(uma)) throw new HttpError(400, 'bad_uma', 'Unknown uma');
  // one statement: only inserts if this player has an unused capsule and doesn't already have this uma from a capsule
  const r = await env.DB.prepare(
    'INSERT OR IGNORE INTO unlocks (uid, uma, at) SELECT ?1, ?2, ?3 WHERE ' +
    '(SELECT purchased FROM players WHERE uid = ?1) > (SELECT COUNT(*) FROM unlocks WHERE uid = ?1)').bind(p.uid, uma, now()).run();
  const s = await state(env, p.uid);
  if (!r.meta || r.meta.changes !== 1) {
    if (s.umas.includes(uma)) return { ok: true, already: true, ...s };          // a retry of a pull that already went through
    throw new HttpError(409, 'no_capsules', 'No paid capsules left');
  }
  return { ok: true, ...s };
}

// ------------------------------------------------------------------ Xsolla webhooks
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
function sameText(a, b) { if (a.length !== b.length) return false; let d = 0; for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i); return d === 0; }
const xErr = (code, message) => json({ error: { code, message } }, 400);

async function webhook(request, env) {
  const raw = await request.text();
  if (!env.XSOLLA_WEBHOOK_SECRET) return xErr('INVALID_SIGNATURE', 'Webhook secret not configured');
  const given = (request.headers.get('authorization') || '').replace(/^Signature\s+/i, '').trim().toLowerCase();
  const want = hex(await crypto.subtle.digest('SHA-1', new TextEncoder().encode(raw + env.XSOLLA_WEBHOOK_SECRET)));
  if (!sameText(given, want)) return xErr('INVALID_SIGNATURE', 'Invalid signature');
  let b; try { b = JSON.parse(raw); } catch (e) { return xErr('INVALID_PARAMETER', 'Bad JSON'); }
  const type = b.notification_type, sku = env.CAPSULE_SKU || 'uma_capsule';

  if (type === 'user_validation') {
    const uid = String(b.user && (b.user.id ?? b.user.external_id) || '');
    const row = uid && await env.DB.prepare('SELECT uid FROM players WHERE uid = ?').bind(uid).first();
    return row ? new Response(null, { status: 200 }) : xErr('INVALID_USER', 'Invalid user');
  }
  if (type === 'order_paid' || type === 'order_canceled') {
    const uid = String(b.user && (b.user.external_id ?? b.user.id) || ''), orderId = String(b.order && b.order.id || '');
    if (!uid || !orderId) return xErr('INVALID_PARAMETER', 'Missing user or order');
    const qty = (b.items || []).filter(it => it && it.sku === sku).reduce((n, it) => n + Math.max(0, Math.floor(Number(it.quantity) || 0)), 0);
    const o = b.order || {}, t = now();
    if (type === 'order_paid') {
      const known = await env.DB.prepare('SELECT uid FROM players WHERE uid = ?').bind(uid).first();
      if (!known) return xErr('INVALID_USER', 'Invalid user');
      // credit once per order: the UPDATE only runs while this order id is new, then the order is recorded (one transaction)
      await env.DB.batch([
        env.DB.prepare('UPDATE players SET purchased = purchased + ?1, updated = ?2 WHERE uid = ?3 AND NOT EXISTS (SELECT 1 FROM orders WHERE order_id = ?4)').bind(qty, t, uid, orderId),
        env.DB.prepare('INSERT OR IGNORE INTO orders (order_id, uid, qty, status, mode, amount, currency, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
          .bind(orderId, uid, qty, 'paid', String(o.mode || ''), String(o.amount ?? ''), String(o.currency || ''), t),
      ]);
    } else {
      // take back a paid order's capsules once; an early cancel (before any paid notice) blocks a later credit
      await env.DB.batch([
        env.DB.prepare("UPDATE players SET purchased = MAX(0, purchased - (SELECT qty FROM orders WHERE order_id = ?1)), updated = ?2 WHERE uid = ?3 AND EXISTS (SELECT 1 FROM orders WHERE order_id = ?1 AND status = 'paid')").bind(orderId, t, uid),
        env.DB.prepare("UPDATE orders SET status = 'canceled', at = ?2 WHERE order_id = ?1").bind(orderId, t),
        env.DB.prepare("INSERT OR IGNORE INTO orders (order_id, uid, qty, status, mode, amount, currency, at) VALUES (?, ?, ?, 'canceled', ?, ?, ?, ?)")
          .bind(orderId, uid, qty, String(o.mode || ''), String(o.amount ?? ''), String(o.currency || ''), t),
      ]);
    }
    return new Response(null, { status: 204 });
  }
  return new Response(null, { status: 204 });                     // other notification types: acknowledged, nothing to do
}
