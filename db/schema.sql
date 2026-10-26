CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY,
  url TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | running | captcha | done | error
  msg TEXT DEFAULT '',
  name TEXT DEFAULT '', -- título da página da loja
  profile TEXT DEFAULT '', -- pasta em db/profiles usada na leitura
  added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY,
  store_id INTEGER NOT NULL REFERENCES stores(id),
  url TEXT UNIQUE NOT NULL,
  title TEXT, price REAL, material TEXT, thumb TEXT DEFAULT '', image INTEGER DEFAULT 0, -- image=1: cópia local em db/images/<id>.img
  is_3d INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'new' -- new | approved | discarded
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  ts TEXT DEFAULT CURRENT_TIMESTAMP,
  sold INTEGER, reviews INTEGER, rank INTEGER
);
CREATE TABLE IF NOT EXISTS models (
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  source_url TEXT DEFAULT '', license_note TEXT DEFAULT '',
  file_path TEXT DEFAULT '', -- relativo à raiz do projeto, em products/<id>/model/
  added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS slices (
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  minutes INTEGER, grams REAL, file_path TEXT DEFAULT '', ts TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kits (
  listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
  title TEXT, description TEXT, bullets TEXT DEFAULT '[]', scripts TEXT DEFAULT '[]', keywords TEXT DEFAULT '[]',
  confirmed INTEGER DEFAULT 0, ts TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publications (
  listing_id INTEGER NOT NULL REFERENCES listings(id), channel TEXT NOT NULL, -- ml | shopee | tiktok
  external_id TEXT DEFAULT '', url TEXT DEFAULT '', status TEXT DEFAULT 'published', ts TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (listing_id, channel)
);
-- uma linha por etapa do produto aprovado: model | slice | cost | copy | kit
CREATE TABLE IF NOT EXISTS steps (
  listing_id INTEGER NOT NULL REFERENCES listings(id),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | running | ok | error | blocked
  data TEXT DEFAULT '{}',
  PRIMARY KEY (listing_id, name)
);
