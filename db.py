import aiosqlite
import os
from contextlib import asynccontextmanager
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS shots (
  id           TEXT PRIMARY KEY,
  timestamp    DATETIME NOT NULL,
  duration_s   REAL,
  profile_name TEXT,
  raw_json     TEXT,
  graph_path   TEXT,
  posted_at    DATETIME
);

CREATE TABLE IF NOT EXISTS feedback (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  shot_id      TEXT REFERENCES shots(id),
  flavor_score INTEGER CHECK(flavor_score BETWEEN 1 AND 10),
  flavor_notes TEXT,
  bean_name    TEXT,
  roaster      TEXT,
  roast_date   DATE,
  grind_size   REAL,
  dose_g       REAL,
  yield_g      REAL,
  brew_ratio   REAL GENERATED ALWAYS AS (yield_g / dose_g) VIRTUAL,
  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT,
  raw_json     TEXT,
  applied_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  source       TEXT CHECK(source IN ('device','bot_recommendation'))
);

CREATE TABLE IF NOT EXISTS recommendations (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  shot_id          TEXT REFERENCES shots(id),
  generated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  recommendation   TEXT,
  adjustments_json TEXT,
  applied          BOOLEAN DEFAULT 0,
  applied_at       DATETIME
);

CREATE TABLE IF NOT EXISTS config (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

async def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

@asynccontextmanager
async def get_db():
    """Async context manager for DB connections. Use as: async with get_db() as db:"""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
