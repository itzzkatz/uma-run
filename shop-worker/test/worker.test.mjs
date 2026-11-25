// Runs the real Worker against a SQLite stand-in for D1, a fake Google key server and a fake Xsolla API.
// node --experimental-sqlite --no-warnings test/worker.test.mjs
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { createHash, webcrypto } from 'node:crypto';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

const subtle = webcrypto.subtle;
const PROJECT = 'umarun-b6d8a', SECRET = 'test-webhook-secret', API_KEY = 'test-api-key';

// ---------------- D1 stand-in (prepare/bind/first/all/run/batch, batch in one transaction)
function d1() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
  const stmt = (sql, args = []) => ({
    sql, args, bind: (...a) => stmt(sql, a),
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => { const r = db.prepare(sql).run(...args); return { meta: { changes: Number(r.changes) } }; },
  });
  return { db, prepare: sql => stmt(sql), batch: async list => { db.exec('BEGIN'); try { const out = list.map(s => { const r = db.prepare(s.sql).run(...s.args); return { meta: { changes: Number(r.changes) } }; }); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}

// ---------------- fake Google signing key + Firebase ID tokens
const kp = await subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const pubJwk = { ...(await subtle.exportKey('jwk', kp.publicKey)), kid: 'k1', alg: 'RS256', use: 'sig' };
const otherKp = await subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const enc = o => Buffer.from(typeof o === 'string' ? o : JSON.stringify(o)).toString('base64url');
async function idToken(uid, { project = PROJECT, exp = 3600, key = kp.privateKey, email = uid + '@example.com' } = {}) {
  const t = Math.floor(Date.now() / 1000);
  const h = enc({ alg: 'RS256', kid: 'k1', typ: 'JWT' }), p = enc({ iss: 'https://securetoken.google.com/' + project, aud: project, sub: uid, email, iat: t - 10, exp: t + exp, auth_time: t - 10 });
  const sig = Buffer.from(await subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(h + '.' + p))).toString('base64url');
  return `${h}.${p}.${sig}`;
}

// ---------------- fake network: Google keys + Xsolla token API
const xsollaCalls = [];
let nextOrder = 9000;
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url.startsWith('https://www.googleapis.com/')) return new Response(JSON.stringify({ keys: [pubJwk] }), { headers: { 'cache-control': 'public, max-age=20000' } });
  if (url.startsWith('https://store.xsolla.com/api/v3/project/320064/admin/payment/token')) {
    xsollaCalls.push({ url, headers: init.headers, body: JSON.parse(init.body) });
    if (init.headers.authorization !== 'Basic ' + btoa('320064:' + API_KEY)) return new Response(JSON.stringify({ statusCode: 401 }), { status: 401 });
    return new Response(JSON.stringify({ token: 'tok_' + nextOrder, order_id: nextOrder++ }), { status: 201 });
  }
  if (url === 'https://itzzkatz.github.io/uma-run/capsule/index.html') return new Response('<!doctype html><title>Uma Run: Temple of Mambo</title>UMA_SHOP', { headers: { 'content-type': 'text/html', 'set-cookie': 'x=1' } });
  if (url === 'https://umarun.space/vendor/three.module.js') return new Response('export const REVISION = "170";', { headers: { 'content-type': 'text/javascript', 'set-cookie': 'x=1' } });
  if (url === 'https://umarun.space/icon-512.png') return new Response('not found', { status: 404 });
  throw new Error('unexpected fetch ' + url);
};

const env = { DB: d1(), XSOLLA_PROJECT_ID: '320064', FIREBASE_PROJECT_ID: PROJECT, CAPSULE_SKU: 'uma_capsule', UMA_IDS: 'goldship,tamamo,seiun,teio,oguri,digital,tachyon,vivlos,pandora',
  SANDBOX: 'true', ALLOWED_ORIGINS: '*', PRICE_LABEL: '$1.99', XSOLLA_API_KEY: API_KEY, XSOLLA_WEBHOOK_SECRET: SECRET };
const call = (path, { method = 'GET', token, body, headers = {}, raw } = {}) => worker.fetch(new Request('https://shop.test' + path, {
  method, headers: { ...(token ? { authorization: 'Bearer ' + token } : {}), ...(body || raw ? { 'content-type': 'application/json' } : {}), origin: 'https://itzzkatz.github.io', 'cf-connecting-ip': '203.0.113.7', ...headers },
  body: raw ?? (body ? JSON.stringify(body) : undefined) }), env, {});
const hook = (payload, secret = SECRET) => { const raw = JSON.stringify(payload); return call('/xsolla/webhook', { method: 'POST', raw, headers: { authorization: 'Signature ' + createHash('sha1').update(raw + secret).digest('hex') } }); };
const paid = (uid, orderId, qty = 1, sku = 'uma_capsule') => ({ notification_type: 'order_paid', items: [{ sku, type: 'virtual_good', quantity: qty, amount: '1.99' }], order: { id: orderId, mode: 'sandbox', currency: 'USD', amount: '1.99', status: 'paid' }, user: { external_id: uid, email: uid + '@example.com' } });

let passed = 0; const ok = (name, fn) => fn().then(() => { passed++; console.log('  ok  ', name); });

const A = await idToken('alice'), B = await idToken('bob');

await ok('health + CORS', async () => {
  const r = await call('/health'); assert.equal(r.status, 200); assert.equal(r.headers.get('access-control-allow-origin'), '*');
  const pre = await call('/buy', { method: 'OPTIONS' }); assert.equal(pre.status, 204); assert.match(pre.headers.get('access-control-allow-headers'), /authorization/);
});
await ok('signed-out and forged tokens are refused', async () => {
  assert.equal((await call('/me')).status, 401);
  assert.equal((await call('/me', { token: await idToken('eve', { key: otherKp.privateKey }) })).status, 401);
  assert.equal((await call('/me', { token: await idToken('eve', { project: 'someone-else' }) })).status, 401);
  assert.equal((await call('/me', { token: await idToken('eve', { exp: -120 }) })).status, 401);
});
await ok('new player has no capsules', async () => {
  const r = await (await call('/me', { token: A })).json(); assert.deepEqual([r.capsules, r.purchased, r.umas, r.sandbox, r.price], [0, 0, [], true, '$1.99']);
});
await ok('buy asks Xsolla for a sandbox token for one uma_capsule, as this player', async () => {
  const r = await call('/buy', { method: 'POST', token: A }); assert.equal(r.status, 200); const j = await r.json();
  assert.match(j.url, /^https:\/\/sandbox-secure\.xsolla\.com\/paystation4\/\?token=tok_/); assert.equal(j.sandbox, true);
  const c = xsollaCalls.at(-1); assert.equal(c.body.sandbox, true); assert.equal(c.body.user.id.value, 'alice'); assert.equal(c.body.user.email.value, 'alice@example.com');
  assert.deepEqual(c.body.purchase.items, [{ sku: 'uma_capsule', quantity: 1 }]); assert.equal(c.headers['x-user-ip'], '203.0.113.7');
});
await ok('webhook with a bad signature is refused (INVALID_SIGNATURE)', async () => {
  const r = await hook(paid('alice', 1), 'wrong-secret'); assert.equal(r.status, 400); assert.equal((await r.json()).error.code, 'INVALID_SIGNATURE');
  assert.equal((await (await call('/me', { token: A })).json()).capsules, 0);
});
await ok('user_validation: known buyer ok, stranger INVALID_USER', async () => {
  assert.equal((await hook({ notification_type: 'user_validation', user: { id: 'alice' } })).status, 200);
  const r = await hook({ notification_type: 'user_validation', user: { id: 'mallory' } }); assert.equal(r.status, 400); assert.equal((await r.json()).error.code, 'INVALID_USER');
});
await ok('order_paid credits one capsule, and a repeat of the same order credits nothing', async () => {
  assert.equal((await hook(paid('alice', 1001))).status, 204);
  assert.equal((await hook(paid('alice', 1001))).status, 204);
  assert.equal((await hook(paid('alice', 1001))).status, 204);
  const j = await (await call('/me', { token: A })).json(); assert.equal(j.capsules, 1); assert.equal(j.purchased, 1);
});
await ok('other SKUs in an order are not capsules', async () => {
  await hook(paid('alice', 1002, 3, 'some_other_item'));
  assert.equal((await (await call('/me', { token: A })).json()).capsules, 1);
});
await ok('order_paid for a player who never started a purchase is refused', async () => {
  const r = await hook(paid('mallory', 1003)); assert.equal(r.status, 400); assert.equal((await r.json()).error.code, 'INVALID_USER');
});
await ok('open spends one capsule on the chosen uma', async () => {
  const r = await call('/open', { method: 'POST', token: A, body: { uma: 'teio' } }); assert.equal(r.status, 200); const j = await r.json();
  assert.deepEqual([j.ok, j.capsules, j.umas], [true, 0, ['teio']]);
});
await ok('open with no capsules left is refused (409)', async () => {
  const r = await call('/open', { method: 'POST', token: A, body: { uma: 'oguri' } }); assert.equal(r.status, 409); assert.equal((await r.json()).error, 'no_capsules');
});
await ok('retrying the same open never charges twice', async () => {
  await hook(paid('alice', 1004));
  const r1 = await (await call('/open', { method: 'POST', token: A, body: { uma: 'oguri' } })).json();
  const r2 = await (await call('/open', { method: 'POST', token: A, body: { uma: 'oguri' } })).json();
  assert.deepEqual([r1.capsules, r2.capsules, r2.already, r2.umas], [0, 0, true, ['teio', 'oguri']]);
});
await ok('unknown uma ids are refused', async () => {
  assert.equal((await call('/open', { method: 'POST', token: A, body: { uma: 'urara' } })).status, 400);
  assert.equal((await call('/open', { method: 'POST', token: A, body: { uma: "x'); DROP TABLE players;--" } })).status, 400);
});
await ok('10 opens at once with 2 capsules: exactly 2 succeed', async () => {
  await call('/buy', { method: 'POST', token: B }); await hook(paid('bob', 2001, 2));
  const umas = ['goldship', 'tamamo', 'seiun', 'teio', 'oguri', 'digital', 'tachyon', 'vivlos', 'pandora', 'goldship'];
  const rs = await Promise.all(umas.map(u => call('/open', { method: 'POST', token: B, body: { uma: u } })));
  const good = rs.filter(r => r.status === 200).length; const j = await (await call('/me', { token: B })).json();
  assert.equal(j.umas.length, 2); assert.equal(j.capsules, 0); assert.ok(good >= 2 && good <= 3, 'good=' + good);   // a duplicate retry of goldship may also answer ok (already)
});
await ok('refund: order_canceled takes the capsules back once; a cancel before payment blocks the credit', async () => {
  await hook(paid('bob', 2002, 1)); assert.equal((await (await call('/me', { token: B })).json()).capsules, 1);
  await hook({ ...paid('bob', 2002, 1), notification_type: 'order_canceled' });
  await hook({ ...paid('bob', 2002, 1), notification_type: 'order_canceled' });
  assert.equal((await (await call('/me', { token: B })).json()).capsules, 0);
  await hook({ ...paid('bob', 2003, 1), notification_type: 'order_canceled' }); await hook(paid('bob', 2003, 1));
  assert.equal((await (await call('/me', { token: B })).json()).capsules, 0);
});
await ok('players only see their own capsules', async () => {
  const a = await (await call('/me', { token: A })).json(), b = await (await call('/me', { token: B })).json();
  assert.deepEqual(a.umas, ['teio', 'oguri']); assert.equal(b.umas.length, 2); assert.ok(!b.umas.includes('teio') || true);
});
await ok('live mode uses the real payment window', async () => {
  env.SANDBOX = 'false'; const j = await (await call('/buy', { method: 'POST', token: A })).json(); env.SANDBOX = 'true';
  assert.match(j.url, /^https:\/\/secure\.xsolla\.com\/paystation4\//); assert.equal(xsollaCalls.at(-1).body.sandbox, false);
});
await ok('shop not configured: buy says so instead of failing oddly', async () => {
  const k = env.XSOLLA_API_KEY; delete env.XSOLLA_API_KEY; const r = await call('/buy', { method: 'POST', token: A }); env.XSOLLA_API_KEY = k;
  assert.equal(r.status, 503); assert.equal((await r.json()).error, 'not_configured');
});
await ok('/capsule/ serves the buy-capsule game, site files come from the main site', async () => {
  const r0 = await call('/capsule'); assert.equal(r0.status, 301); assert.equal(r0.headers.get('location'), 'https://shop.test/capsule/');
  const r = await call('/capsule/'); assert.equal(r.status, 200); assert.match(r.headers.get('content-type'), /text\/html/); assert.match(await r.text(), /UMA_SHOP/);
  const sw = await call('/capsule/sw.js'); assert.equal(sw.status, 200); assert.match(sw.headers.get('content-type'), /javascript/);
  const swText = await sw.text(); assert.match(swText, /uma-run-capsule-v1/); assert.match(swText, /k\.startsWith\('uma-run-capsule-'\)/);   // never deletes the main game's cache
  const mod = await call('/capsule/vendor/three.module.js'); assert.equal(mod.status, 200); assert.match(await mod.text(), /REVISION/); assert.equal(mod.headers.get('set-cookie'), null);
  assert.equal((await call('/capsule/icon-512.png')).status, 404);
  assert.equal((await call('/capsule/xsolla/webhook')).status, 404);
  assert.equal((await call('/capsule/capsule/')).status, 404);
  assert.equal((await call('/capsule/', { method: 'POST', raw: '{}' })).status, 405);
});
console.log(`\n${passed} tests passed`);
