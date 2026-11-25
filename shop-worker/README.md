# Uma Run shop: paid Uma Capsules with Xsolla on Cloudflare

A Cloudflare Worker that sells **Uma Capsules** for **$1.99** through Xsolla and keeps track of them per player.
Players sign in with the game's existing Firebase accounts. A capsule opens the game's capsule machine
(a random uma the player doesn't own yet, equal odds, no duplicates).

```
game ──(Firebase sign-in token)──> Worker /buy ──(API key)──> Xsolla: payment token
game opens Xsolla's payment window
Xsolla ──(signed order_paid)──> Worker /xsolla/webhook ──> +1 capsule in D1 (once per order)
game ──> Worker /me (balance + paid umas to restore)   game ──> Worker /open {uma} (spend 1 capsule)
```

## Live setup (Nov 2026)

- Worker: `https://uma-run-shop.itzzkatz.workers.dev` (check it at `/health`)
- D1 database: `uma-run-shop` (id `4835945b-24a9-4b5c-8906-894da6dd6bbe`), bound as `DB`
- Xsolla project 320064: item `uma_capsule` ($1.99), webhooks to `https://umarun.space/xsolla/webhook`.
  A Workers route `umarun.space/xsolla/*` sends that path of the website to this Worker; the rest of umarun.space
  stays on the `uma-run` site Worker. `https://uma-run-shop.itzzkatz.workers.dev/xsolla/webhook` still works too.
- Secrets `XSOLLA_API_KEY` and `XSOLLA_WEBHOOK_SECRET` are set on the Worker. The plain-text settings below are built
  into `src/index.js` as defaults, so no variables are needed; add one with the same name to override it
  (for example `SANDBOX` = `false` once Xsolla approves real payments).
- `https://umarun.space/` (and `www.`) is the buy-capsule version of the game too. Workers routes `umarun.space/*` and
  `www.umarun.space/*` (plus exact `/` and `/index.html` routes, all **fail open**) send the site to this Worker, which
  answers only the home page (any query string), `/capsule/` and `/xsolla/webhook`; every other path is passed straight
  through to the `uma-run` site Worker. If GitHub Pages can't be reached, or the Worker fails or runs out of its daily
  free requests, visitors get the site's own home page as before. To undo, delete those routes.
- `https://umarun.space/capsule/` is the buy-capsule version of the game. A Workers route `umarun.space/capsule*`
  sends it to this Worker, which serves `capsule/index.html` from GitHub Pages (cached 5 minutes). Everything else the
  page loads (`vendor/` three.js modules, icons, manifest) is the main site's own copy. `/capsule/sw.js` is a separate
  offline worker with its own cache (`uma-run-capsule-v1`), so it never clears the main game's cache. The main game at
  `https://umarun.space/` is unchanged. One quirk: on a player's very first visit to `/capsule/`, the main site's sw.js
  (which handles that first page load) files it as its offline copy of `/`; the next online visit to the main game puts
  the main page back. Only the offline fallback is affected.
- Two placeholder players, `webhook-test-user` and `xsolla-test-2`, exist so Xsolla's webhook tester can pass its
  "valid user" check. They hold no capsules.

## What's where

| File | What it is |
| --- | --- |
| `src/index.js` | the Worker |
| `schema.sql` | the D1 tables (`players`, `orders`, `unlocks`) |
| `wrangler.toml` | settings for deploying with Wrangler (optional, the dashboard works too) |
| `test/worker.test.mjs` | 18 tests against the real Worker code (`npm test`, Node 22) |
| `test/server.mjs` | a local stand-in of the Worker for testing the game end to end |

## Settings

Variables (plain text):

| Name | Value |
| --- | --- |
| `XSOLLA_PROJECT_ID` | `320064` |
| `FIREBASE_PROJECT_ID` | `umarun-b6d8a` |
| `CAPSULE_SKU` | `uma_capsule` (must match the item SKU in Xsolla) |
| `UMA_IDS` | `goldship,tamamo,seiun,teio,oguri,digital,tachyon,vivlos,pandora` |
| `PRICE_LABEL` | `$1.99` (label only, the real price is the one in Xsolla) |
| `SANDBOX` | `true` until Xsolla approves real payments, then `false` |
| `ALLOWED_ORIGINS` | `*`, or the sites that host the game, comma separated |

Secrets (type these yourself, never in code or in the game file):

| Name | Where to get it |
| --- | --- |
| `XSOLLA_API_KEY` | Xsolla Publisher Account > Company settings > API keys (shown only once when created) |
| `XSOLLA_WEBHOOK_SECRET` | Xsolla Publisher Account > project 320064 > Project settings > Webhooks > Secret key |

Binding: a D1 database bound as `DB`, with `schema.sql` run once.

## Deploy from the Cloudflare dashboard

1. **Storage & Databases > D1 > Create**: name it `uma-run-shop`. Open its **Console**, paste `schema.sql`, run it.
2. **Workers & Pages > Create > Start with Hello World**: name it `uma-run-shop`, deploy, then **Edit code**,
   replace everything with `src/index.js`, and deploy.
3. Worker **Settings > Bindings > Add > D1 database**: variable name `DB`, database `uma-run-shop`.
4. Worker **Settings > Variables and Secrets**: add the variables above as *Text* and the two secrets as *Secret*.
5. Your Worker address is `https://uma-run-shop.<your-subdomain>.workers.dev`. Opening it shows `{"ok":true,...}`.

Or with Wrangler: `npx wrangler d1 create uma-run-shop` (paste the id into `wrangler.toml`),
`npx wrangler d1 execute uma-run-shop --remote --file schema.sql`, `npx wrangler secret put XSOLLA_API_KEY`,
`npx wrangler secret put XSOLLA_WEBHOOK_SECRET`, `npx wrangler deploy`.

## Xsolla setup (project 320064)

1. **Items catalog > Virtual items**: create an item with SKU `uma_capsule`, name *Uma Capsule*, price **1.99 USD**.
2. **Project settings > Webhooks**: turn webhooks on, set the URL to `https://uma-run-shop.<your-subdomain>.workers.dev/xsolla/webhook`,
   and copy the secret key into the Worker secret `XSOLLA_WEBHOOK_SECRET`.
3. **Company settings > API keys**: create a key, put it in the Worker secret `XSOLLA_API_KEY`.
4. In the game file, set `window.UMA_SHOP = { api: 'https://uma-run-shop.<your-subdomain>.workers.dev', price: '$1.99' }`
   (near `FIREBASE_CONFIG` at the top), or rebuild with `python3 make_shop.py uma-run.html out.html --api <url>`.
5. Test in sandbox with an Xsolla test card. Real payments only start after you sign Xsolla's licensing agreement
   and set `SANDBOX` to `false`.

## Refunds and edge cases

- A refunded or charged-back order (`order_canceled`) removes its capsule if it is still unopened. If the player already
  opened it, the uma stays and their capsule count can't go below zero.
- Xsolla may resend a webhook: each order id is credited at most once.
- Opening is atomic: a capsule can't be spent twice, and retrying a pull that went through doesn't charge again.
