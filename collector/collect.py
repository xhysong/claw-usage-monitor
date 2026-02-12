#!/usr/bin/env python3
"""OpenClaw Usage Monitor Collector (macOS)

- Samples every second.
- Token/context source: `openclaw status --json` (recent sessions include token fields).
- Network source: macOS `nettop` per PID when possible (gateway + openclaw browser).

This script is intentionally conservative: if any metric can't be collected,
we still write what we have.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List


def resolve_openclaw_bin() -> str:
    """Resolve the `openclaw` binary path.

    launchd jobs often have a minimal PATH, so relying on plain `openclaw` can fail.
    """
    env = os.environ.get("OPENCLAW_BIN")
    if env:
        return env
    found = shutil.which("openclaw")
    if found:
        return found
    # common install locations
    for p in ["/usr/local/bin/openclaw", "/opt/homebrew/bin/openclaw"]:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return "openclaw"


OPENCLAW_BIN = resolve_openclaw_bin()


def run(cmd: List[str], timeout: float = 20.0) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(cmd)}\nstderr: {p.stderr.strip()}")
    return p.stdout


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class StatusSample:
    session_key: Optional[str]
    model: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    remaining_tokens: Optional[int]
    context_tokens: Optional[int]
    percent_used: Optional[int]


def get_openclaw_status_json() -> Dict[str, Any]:
    # `openclaw status --json` can be slow under load; give it more time.
    out = run([OPENCLAW_BIN, "status", "--json"], timeout=25)
    return json.loads(out)


def pick_primary_session(status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Prefer the most recently updated session.
    recent = (((status.get("sessions") or {}).get("recent")) or [])
    if not recent:
        return None
    # already sorted by updatedAt desc in status; but be safe
    recent = sorted(recent, key=lambda r: r.get("updatedAt", 0), reverse=True)
    return recent[0]


def parse_status_sample(status: Dict[str, Any]) -> StatusSample:
    s = pick_primary_session(status) or {}
    return StatusSample(
        session_key=s.get("key"),
        model=s.get("model"),
        input_tokens=s.get("inputTokens"),
        output_tokens=s.get("outputTokens"),
        total_tokens=s.get("totalTokens"),
        remaining_tokens=s.get("remainingTokens"),
        context_tokens=s.get("contextTokens"),
        percent_used=s.get("percentUsed"),
    )


PID_RE = re.compile(r"\(pid\s+(\d+)\)")


def get_gateway_pid() -> Optional[int]:
    # `openclaw gateway status` prints "Runtime: running (pid XXXX)"
    try:
        out = run([OPENCLAW_BIN, "gateway", "status"], timeout=10)
        m = PID_RE.search(out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


BROWSER_PID_RE = re.compile(r"\(pid\s+(\d+)\)")


def get_browser_pid(profile: str = "openclaw") -> Optional[int]:
    # Use log line via CLI: `openclaw browser status` includes pid sometimes.
    try:
        out = run([OPENCLAW_BIN, "browser", "status", "--browser-profile", profile], timeout=10)
        m = BROWSER_PID_RE.search(out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def nettop_bytes_for_pid(pid: int) -> Optional[Tuple[int, int]]:
    """Return (rx_bytes, tx_bytes) for PID using nettop.

    nettop output formats vary by macOS version; we use a minimal JSON mode when available.
    If it fails, return None.
    """
    try:
        out = run(["/usr/bin/nettop", "-P", "-L", "1", "-n", "-J", "bytes_in,bytes_out", "-p", str(pid)], timeout=5)
        lines = [ln for ln in out.splitlines() if ln.strip().startswith("{") and ln.strip().endswith("}")]
        if not lines:
            return None
        j = json.loads(lines[-1])
        rx = j.get("bytes_in") or j.get("rx_bytes") or j.get("in_bytes")
        tx = j.get("bytes_out") or j.get("tx_bytes") or j.get("out_bytes")
        if rx is None or tx is None:
            return None
        return int(rx), int(tx)
    except Exception:
        return None


def netstat_total_bytes() -> Optional[Tuple[int, int]]:
    """Return (rx_bytes, tx_bytes) as system-wide totals via `netstat -ib`.

    This is a reliable fallback when per-PID nettop is unavailable (permissions/format).
    """
    try:
        out = run(["/usr/sbin/netstat", "-ib"], timeout=5)
    except Exception:
        try:
            out = run(["/usr/bin/netstat", "-ib"], timeout=5)
        except Exception:
            return None

    # Columns include Ibytes / Obytes. We'll parse header to find the correct indices.
    rx_total = 0
    tx_total = 0
    header_cols = None
    ibytes_i = None
    obytes_i = None

    for ln in out.splitlines():
        if ln.strip().startswith("Name"):
            header_cols = ln.split()
            try:
                ibytes_i = header_cols.index("Ibytes")
                obytes_i = header_cols.index("Obytes")
            except ValueError:
                ibytes_i = None
                obytes_i = None
            continue

        if not header_cols or ibytes_i is None or obytes_i is None:
            continue
        if not ln.strip():
            continue

        parts = ln.split()
        if len(parts) <= max(ibytes_i, obytes_i):
            continue

        name = parts[0]
        if not (name.startswith("en") or name.startswith("bridge")):
            continue

        try:
            ibytes = int(parts[ibytes_i])
            obytes = int(parts[obytes_i])
        except Exception:
            continue

        rx_total += ibytes
        tx_total += obytes
    if rx_total == 0 and tx_total == 0:
        return None
    return rx_total, tx_total


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection, schema_path: str) -> None:
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def insert_sample(conn: sqlite3.Connection, ts_ms: int, s: StatusSample, net_rx: Optional[int], net_tx: Optional[int]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO samples (
          ts_ms, session_key, model,
          input_tokens, output_tokens, total_tokens, remaining_tokens,
          context_tokens, percent_used,
          net_rx_bytes, net_tx_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_ms,
            s.session_key,
            s.model,
            s.input_tokens,
            s.output_tokens,
            s.total_tokens,
            s.remaining_tokens,
            s.context_tokens,
            s.percent_used,
            net_rx,
            net_tx,
        ),
    )


def prune_old(conn: sqlite3.Connection, keep_days: int = 90) -> None:
    cutoff = now_ms() - keep_days * 86400 * 1000
    conn.execute("DELETE FROM samples WHERE ts_ms < ?", (cutoff,))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--schema", default=os.path.join(os.path.dirname(__file__), "schema.sql"))
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--profile", default="openclaw")
    ap.add_argument("--keep-days", type=int, default=90)
    args = ap.parse_args()

    conn = open_db(args.db)
    init_db(conn, args.schema)

    gateway_pid = None
    browser_pid = None
    last_pid_refresh = 0.0

    last_status_err_at = 0.0
    last_net_err_at = 0.0

    # Carry forward the last good status sample so brief timeouts don't erase token history.
    last_good_status = StatusSample(None, None, None, None, None, None, None, None)

    # one-time environment diagnostics (helps when launchd PATH is minimal)
    try:
        node_path = shutil.which("node")
        print(f"[collector] OPENCLAW_BIN={OPENCLAW_BIN}", file=sys.stderr)
        print(f"[collector] PATH={os.environ.get('PATH','')}", file=sys.stderr)
        print(f"[collector] which node={node_path}", file=sys.stderr)
    except Exception:
        pass

    while True:
        t0 = time.time()
        ts = now_ms()

        # refresh pids every 30s
        if t0 - last_pid_refresh > 30:
            gateway_pid = get_gateway_pid()
            browser_pid = get_browser_pid(args.profile)
            last_pid_refresh = t0

        # tokens/context
        status = None
        try:
            status = get_openclaw_status_json()
            s = parse_status_sample(status)
            # update carry-forward cache if we got any token fields
            if s.session_key or s.total_tokens is not None:
                last_good_status = s
        except Exception as e:
            # log occasionally for debugging
            if t0 - last_status_err_at > 60:
                last_status_err_at = t0
                print(f"[collector] status sample failed: {e}", file=sys.stderr)
            # carry forward last known good token values
            s = last_good_status

        # net bytes (best effort): per-PID (gateway + browser) via nettop; fallback to system totals via netstat
        net_rx = 0
        net_tx = 0
        any_net = False
        for pid in [gateway_pid, browser_pid]:
            if not pid:
                continue
            bt = nettop_bytes_for_pid(pid)
            if bt:
                any_net = True
                net_rx += bt[0]
                net_tx += bt[1]

        if not any_net:
            totals = netstat_total_bytes()
            if totals:
                any_net = True
                net_rx, net_tx = totals

        if not any_net:
            net_rx = None
            net_tx = None

        insert_sample(conn, ts, s, net_rx, net_tx)
        prune_old(conn, keep_days=args.keep_days)
        conn.commit()

        # sleep to interval
        dt = time.time() - t0
        sleep_s = max(0.0, args.interval - dt)
        time.sleep(sleep_s)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
