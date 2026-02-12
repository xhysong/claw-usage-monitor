import { invoke } from "@tauri-apps/api/core";

type LiveMetrics = {
  tsMs: number;
  sessionKey?: string | null;
  model?: string | null;

  inputTokens?: number | null;
  outputTokens?: number | null;
  totalTokens?: number | null;
  remainingTokens?: number | null;
  contextTokens?: number | null;
  percentUsed?: number | null;

  tokensPerS?: number | null;
  inTokensPerS?: number | null;
  outTokensPerS?: number | null;
  netRxBytesPerS?: number | null;
  netTxBytesPerS?: number | null;
};

type Rollup = {
  windowLabel: string;
  startTsMs: number;
  endTsMs: number;
  inputTokens?: number | null;
  outputTokens?: number | null;
  totalTokens?: number | null;
  netRxBytes?: number | null;
  netTxBytes?: number | null;
};

function fmtRate(n?: number | null, unit = "t/s") {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n.toFixed(1)} ${unit}`;
}

function fmtBytesPerS(n?: number | null) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs < 1024) return `${n.toFixed(0)} B/s`;
  const kb = n / 1024;
  const mb = kb / 1024;
  if (Math.abs(mb) >= 1) return `${mb.toFixed(2)} MB/s`;
  return `${kb.toFixed(1)} KB/s`;
}

function fmtBytes(n?: number | null) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  const kb = n / 1024;
  const mb = kb / 1024;
  const gb = mb / 1024;
  if (abs >= 1024 * 1024 * 1024) return `${gb.toFixed(2)} GB`;
  if (abs >= 1024 * 1024) return `${mb.toFixed(2)} MB`;
  if (abs >= 1024) return `${kb.toFixed(1)} KB`;
  return `${n.toFixed(0)} B`;
}

async function tick() {
  const m = (await invoke("get_live_metrics", { dbPath: null })) as LiveMetrics;
  const rollups = (await invoke("get_rollups", { dbPath: null })) as Rollup[];

  (document.querySelector("#tokens-rate") as HTMLElement).textContent = fmtRate(
    m.tokensPerS,
    "tok/s"
  );
  (document.querySelector("#tokens-rate-io") as HTMLElement).textContent =
    `${fmtRate(m.inTokensPerS, "in/s")} · ${fmtRate(m.outTokensPerS, "out/s")}`;

  (document.querySelector("#context") as HTMLElement).textContent =
    m.contextTokens && m.percentUsed != null
      ? `${m.percentUsed}% of ${m.contextTokens}`
      : "—";

  (document.querySelector("#net") as HTMLElement).textContent =
    `${fmtBytesPerS(m.netRxBytesPerS)} ↓  ·  ${fmtBytesPerS(m.netTxBytesPerS)} ↑`;

  for (const r of rollups) {
    const el = document.querySelector(`#rollup-${r.windowLabel}`) as HTMLElement | null;
    if (!el) continue;
    const tok = r.totalTokens ?? null;
    el.textContent = `${tok ?? "—"} tok · net ↓ ${fmtBytes(r.netRxBytes)} ↑ ${fmtBytes(
      r.netTxBytes
    )}`;
  }

  (document.querySelector("#model") as HTMLElement).textContent = m.model ?? "—";
  (document.querySelector("#session") as HTMLElement).textContent =
    m.sessionKey ?? "—";

  (document.querySelector("#updated") as HTMLElement).textContent =
    new Date(m.tsMs).toLocaleString();
}

window.addEventListener("DOMContentLoaded", () => {
  tick();
  setInterval(tick, 1000);
});
