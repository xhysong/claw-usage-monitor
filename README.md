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

## LaunchAgent (optional)

If you want the collector to run in the background on login, create a LaunchAgent.

1) Create `~/Library/LaunchAgents/ai.openclaw.claw-monitor.collector.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.openclaw.claw-monitor.collector</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>REPLACE_WITH_REPO_PATH/collector/collect.py</string>
    <string>--db</string><string>$HOME/.openclaw/workspace/projects/openclaw-usage-monitor/collector/usage.db</string>
    <string>--interval</string><string>1.0</string>
    <string>--keep-days</string><string>90</string>
    <string>--profile</string><string>openclaw</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/ClawMonitor/collector.out.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/ClawMonitor/collector.err.log</string>
</dict>
</plist>
```

2) Load + start it:

```bash
mkdir -p "$HOME/Library/Logs/ClawMonitor"
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.claw-monitor.collector.plist
launchctl kickstart -k gui/$(id -u)/ai.openclaw.claw-monitor.collector
```

3) Troubleshooting:

```bash
launchctl print gui/$(id -u)/ai.openclaw.claw-monitor.collector
tail -n 200 "$HOME/Library/Logs/ClawMonitor/collector.err.log"
```

Tip: launchd has a minimal environment. If the collector can't find `openclaw`, set `OPENCLAW_BIN=/opt/homebrew/bin/openclaw` in the plist.

## Notes / limitations

- **Token metrics are snapshots.** They come from `openclaw status --json` (session snapshots), which typically update after a turn completes.
- **Token rate is derived.** `tok/s` is computed from deltas between successive samples for the same session.
- **Not true streaming usage.** If you want per-chunk/streaming usage while a response is still generating, you need a different data source (e.g., listening to gateway response lifecycle events / SSE and extracting `usage` when reported).
- **launchd environment is minimal.** Background LaunchAgents often cannot find `openclaw`/`node` unless you set `PATH` (and sometimes `OPENCLAW_BIN`).
- **Network stats are best-effort.** `nettop` per-PID stats may require permissions and can vary across macOS versions; the collector falls back to `netstat -ib` totals when needed.
