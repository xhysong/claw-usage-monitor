# Claw Usage Monitor (macOS)

A small macOS menu bar + dashboard app to monitor **OpenClaw usage**:

- Token/context snapshots (via `openclaw status --json`)
- Token rate (derived from successive samples)
- Network bytes (best-effort per PID via `nettop`, with a `netstat` fallback)
- Rollups (1d / 3d / 7d) stored in SQLite

## Privacy & security

This repo is designed to avoid collecting secrets. Still:

- **Do not commit** your local SQLite database (`usage.db`) or logs.
- Never commit `~/.openclaw/openclaw.json` or any auth files.

The provided `.gitignore` excludes `*.db` and `*.log` by default.

## How it works

- **Collector** (`collector/collect.py`): samples every second and writes to SQLite.
- **App** (`macapp/claw-monitor/`): reads the SQLite DB and displays live + rollups.

## Quick start

### 1) Run collector

```bash
python3 collector/collect.py \
  --db "$HOME/.openclaw/workspace/projects/openclaw-usage-monitor/collector/usage.db" \
  --interval 1.0 \
  --keep-days 90 \
  --profile openclaw
```

### 2) Run the app (dev)

```bash
cd macapp/claw-monitor
npm install
npm run tauri dev
```

## Notes / limitations

- Token metrics come from `openclaw status --json` (session snapshots). They typically update after a turn completes.
- `nettop` per-PID stats may require permissions and can vary across macOS versions.
