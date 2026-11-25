-- Uma Run shop database (Cloudflare D1). Safe to run more than once.
CREATE TABLE IF NOT EXISTS players (
  uid       TEXT PRIMARY KEY,           -- Firebase user id
  email     TEXT,
  purchased INTEGER NOT NULL DEFAULT 0, -- capsules credited by paid Xsolla orders (minus refunds)
  created   INTEGER,
  updated   INTEGER
);
CREATE TABLE IF NOT EXISTS orders (
  order_id  TEXT PRIMARY KEY,           -- Xsolla order id: each order is credited at most once
  uid       TEXT NOT NULL,
  qty       INTEGER NOT NULL,
  status    TEXT NOT NULL,              -- paid | canceled
  mode      TEXT,
  amount    TEXT,
  currency  TEXT,
  at        INTEGER
);
CREATE TABLE IF NOT EXISTS unlocks (
  uid  TEXT NOT NULL,                   -- one row per uma opened from a paid capsule (unused capsules = purchased - rows)
  uma  TEXT NOT NULL,
  at   INTEGER,
  PRIMARY KEY (uid, uma)
);
CREATE INDEX IF NOT EXISTS orders_uid ON orders (uid);
