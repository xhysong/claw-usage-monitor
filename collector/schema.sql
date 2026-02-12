-- SQLite schema for OpenClaw Usage Monitor

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 1s samples (append-only)
CREATE TABLE IF NOT EXISTS samples (
  ts_ms INTEGER NOT NULL,
  session_key TEXT,
  model TEXT,

  input_tokens INTEGER,
  output_tokens INTEGER,
  total_tokens INTEGER,
  remaining_tokens INTEGER,
  context_tokens INTEGER,
  percent_used INTEGER,

  -- net bytes attributed to OpenClaw processes
  net_rx_bytes INTEGER,
  net_tx_bytes INTEGER,

  PRIMARY KEY (ts_ms, session_key)
);

-- Reset markers for counters (soft reset)
CREATE TABLE IF NOT EXISTS resets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,            -- e.g. session|day|3day|7day|custom
  at_ts_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts_ms);
CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_key);
