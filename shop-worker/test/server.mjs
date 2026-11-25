// Local stand-in for the deployed Worker, for testing the game end to end: the real Worker code over HTTP, with a SQLite D1,
// fake Google sign-in keys and a fake Xsolla token API. Test-only helpers:
//   GET  /__test/token?uid=alice          -> a Firebase-style ID token for that player
//   POST /__test/pay?uid=alice&order=123  -> Xsolla's signed order_paid webhook for one capsule
//   GET  /__test/xsolla                   -> the token requests the Worker sent to "Xsolla"
// node --experimental-sqlite --no-warnings test/server.mjs [port]
import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { createHash, webcrypto } from 'node:crypto';
import worker from '../src/index.js';

const subtle = webcrypto.subtle, PROJECT = 'umarun-b6d8a', SECRET = 'local-webhook-secret', PORT = +(process.argv[2] || 8792);
const db = new DatabaseSync(':memory:'); db.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
const stmt = (sql, args = []) => ({ sql, args, bind: (...a) => stmt(sql, a), first: async () => db.prepare(sql).get(...args) ?? null,
  all: async () => ({ results: db.prepare(sql).all(...args) }), run: async () => ({ meta: { changes: Number(db.prepare(sql).run(...args).changes) } }) });
const D1 = { prepare: sql => stmt(sql), batch: async l => { db.exec('BEGIN'); try { const o = l.map(s => ({ meta: { changes: Number(db.prepare(s.sql).run(...s.args).changes) } })); db.exec('COMMIT'); return o; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
const kp = await subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await subtle.exportKey('jwk', kp.publicKey)), kid: 'local', alg: 'RS256' };
const enc = o => Buffer.from(JSON.stringify(o)).toString('base64url');
async function idToken(uid) {
  const t = Math.floor(Date.now() / 1000), h = enc({ alg: 'RS256', kid: 'local' }), p = enc({ iss: 'https://securetoken.google.com/' + PROJECT, aud: PROJECT, sub: uid, email: uid + '@example.com', iat: t, exp: t + 3600 });
  return `${h}.${p}.${Buffer.from(await subtle.sign('RSASSA-PKCS1-v1_5', kp.privateKey, new TextEncoder().encode(h + '.' + p))).toString('base64url')}`;
}
const xsolla = []; let order = 50000;
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url.startsWith('https://www.googleapis.com/')) return new Response(JSON.stringify({ keys: [jwk] }));
  if (url.includes('store.xsolla.com')) { xsolla.push(JSON.parse(init.body)); return new Response(JSON.stringify({ token: 'local_tok_' + order, order_id: order++ }), { status: 201 }); }
  return realFetch(url, init);
};
const env = { DB: D1, XSOLLA_PROJECT_ID: '320064', FIREBASE_PROJECT_ID: PROJECT, CAPSULE_SKU: 'uma_capsule', UMA_IDS: 'goldship,tamamo,seiun,teio,oguri,digital,tachyon,vivlos,pandora',
  SANDBOX: 'true', ALLOWED_ORIGINS: '*', PRICE_LABEL: '$1.99', XSOLLA_API_KEY: 'local-key', XSOLLA_WEBHOOK_SECRET: SECRET };

createServer(async (req, res) => {
  const u = new URL(req.url, 'http://localhost'); const chunks = []; for await (const c of req) chunks.push(c); const body = Buffer.concat(chunks);
  const send = (code, obj) => { res.writeHead(code, { 'content-type': 'application/json', 'access-control-allow-origin': '*' }); res.end(JSON.stringify(obj)); };
  if (u.pathname === '/__test/token') return send(200, { token: await idToken(u.searchParams.get('uid')) });
  if (u.pathname === '/__test/xsolla') return send(200, xsolla);
  if (u.pathname === '/__test/pay') {
    const uid = u.searchParams.get('uid'), raw = JSON.stringify({ notification_type: 'order_paid', items: [{ sku: 'uma_capsule', type: 'virtual_good', quantity: 1, amount: '1.99' }],
      order: { id: Number(u.searchParams.get('order')), mode: 'sandbox', currency: 'USD', amount: '1.99', status: 'paid' }, user: { external_id: uid, email: uid + '@example.com' } });
    const r = await worker.fetch(new Request('http://local/xsolla/webhook', { method: 'POST', body: raw, headers: { authorization: 'Signature ' + createHash('sha1').update(raw + SECRET).digest('hex') } }), env, {});
    return send(200, { webhook: r.status });
  }
  const r = await worker.fetch(new Request('http://local' + req.url, { method: req.method, headers: req.headers, body: ['GET', 'HEAD', 'OPTIONS'].includes(req.method) ? undefined : body }), env, {});
  res.writeHead(r.status, Object.fromEntries(r.headers)); res.end(Buffer.from(await r.arrayBuffer()));
}).listen(PORT, '127.0.0.1', () => console.log('shop stand-in on', PORT));
