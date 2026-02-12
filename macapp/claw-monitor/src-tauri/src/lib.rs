use rusqlite::Connection;
use serde::Serialize;
use std::time::{SystemTime, UNIX_EPOCH};

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveMetrics {
    ts_ms: i64,

    session_key: Option<String>,
    model: Option<String>,

    input_tokens: Option<i64>,
    output_tokens: Option<i64>,
    total_tokens: Option<i64>,
    remaining_tokens: Option<i64>,
    context_tokens: Option<i64>,
    percent_used: Option<i64>,

    // computed rates
    tokens_per_s: Option<f64>,
    in_tokens_per_s: Option<f64>,
    out_tokens_per_s: Option<f64>,

    net_rx_bytes_per_s: Option<f64>,
    net_tx_bytes_per_s: Option<f64>,
}

fn db_path_default() -> String {
    if let Ok(p) = std::env::var("CLAWMONITOR_DB") {
        if !p.trim().is_empty() {
            return p;
        }
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/Users/Shared".to_string());
    format!(
        "{}/.openclaw/workspace/projects/openclaw-usage-monitor/collector/usage.db",
        home
    )
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Rollup {
    window_label: String,
    start_ts_ms: i64,
    end_ts_ms: i64,

    // deltas across the window
    input_tokens: Option<i64>,
    output_tokens: Option<i64>,
    total_tokens: Option<i64>,

    net_rx_bytes: Option<i64>,
    net_tx_bytes: Option<i64>,
}

fn get_window_delta(conn: &Connection, start_ms: i64, end_ms: i64) -> Result<Rollup, String> {
    // Find first sample >= start and last sample <= end
    let first = conn
        .query_row(
            r#"
            SELECT ts_ms, input_tokens, output_tokens, total_tokens, net_rx_bytes, net_tx_bytes
            FROM samples
            WHERE ts_ms >= ?1 AND ts_ms <= ?2
            ORDER BY ts_ms ASC
            LIMIT 1
            "#,
            [start_ms, end_ms],
            |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, Option<i64>>(1)?,
                    r.get::<_, Option<i64>>(2)?,
                    r.get::<_, Option<i64>>(3)?,
                    r.get::<_, Option<i64>>(4)?,
                    r.get::<_, Option<i64>>(5)?,
                ))
            },
        )
        .map_err(|e| e.to_string())?;

    let last = conn
        .query_row(
            r#"
            SELECT ts_ms, input_tokens, output_tokens, total_tokens, net_rx_bytes, net_tx_bytes
            FROM samples
            WHERE ts_ms >= ?1 AND ts_ms <= ?2
            ORDER BY ts_ms DESC
            LIMIT 1
            "#,
            [start_ms, end_ms],
            |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, Option<i64>>(1)?,
                    r.get::<_, Option<i64>>(2)?,
                    r.get::<_, Option<i64>>(3)?,
                    r.get::<_, Option<i64>>(4)?,
                    r.get::<_, Option<i64>>(5)?,
                ))
            },
        )
        .map_err(|e| e.to_string())?;

    let (ts0, in0, out0, tot0, rx0, tx0) = first;
    let (ts1, in1, out1, tot1, rx1, tx1) = last;

    let delta = |a: Option<i64>, b: Option<i64>| match (a, b) {
        (Some(x), Some(y)) => {
            // Counters can reset (new session, compaction, truncation). Negative deltas are not meaningful for usage.
            let d = y - x;
            if d >= 0 { Some(d) } else { None }
        }
        _ => None,
    };

    Ok(Rollup {
        window_label: "".to_string(),
        start_ts_ms: ts0,
        end_ts_ms: ts1,
        input_tokens: delta(in0, in1),
        output_tokens: delta(out0, out1),
        total_tokens: delta(tot0, tot1),
        net_rx_bytes: delta(rx0, rx1),
        net_tx_bytes: delta(tx0, tx1),
    })
}

#[tauri::command]
fn get_rollups(db_path: Option<String>) -> Result<Vec<Rollup>, String> {
    let db_path = db_path.unwrap_or_else(db_path_default);
    let conn = Connection::open(db_path).map_err(|e| e.to_string())?;

    let end = now_ms();
    let windows: Vec<(&str, i64)> = vec![
        ("1d", 24 * 60 * 60 * 1000),
        ("3d", 3 * 24 * 60 * 60 * 1000),
        ("7d", 7 * 24 * 60 * 60 * 1000),
    ];

    let mut out = Vec::new();
    for (label, dur) in windows {
        let start = end - dur;
        match get_window_delta(&conn, start, end) {
            Ok(mut r) => {
                r.window_label = label.to_string();
                out.push(r);
            }
            Err(_) => {
                // No samples in this window yet
                out.push(Rollup {
                    window_label: label.to_string(),
                    start_ts_ms: start,
                    end_ts_ms: end,
                    input_tokens: None,
                    output_tokens: None,
                    total_tokens: None,
                    net_rx_bytes: None,
                    net_tx_bytes: None,
                });
            }
        }
    }

    Ok(out)
}

#[tauri::command]
fn get_live_metrics(db_path: Option<String>) -> Result<LiveMetrics, String> {
    let db_path = db_path.unwrap_or_else(db_path_default);
    let conn = Connection::open(db_path).map_err(|e| e.to_string())?;

    // Get most recent sample (any session), then find the previous sample for the SAME session.
    let (ts1, session_key, model, in1, out1, tot1, rem1, ctx1, pct1, rx1, tx1): (
        i64,
        Option<String>,
        Option<String>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
        Option<i64>,
    ) = conn
        .query_row(
            r#"
            SELECT ts_ms, session_key, model,
                   input_tokens, output_tokens, total_tokens, remaining_tokens,
                   context_tokens, percent_used,
                   net_rx_bytes, net_tx_bytes
            FROM samples
            ORDER BY ts_ms DESC
            LIMIT 1
            "#,
            [],
            |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                    r.get(6)?,
                    r.get(7)?,
                    r.get(8)?,
                    r.get(9)?,
                    r.get(10)?,
                ))
            },
        )
        .map_err(|e| e.to_string())?;

    let mut tokens_per_s = None;
    let mut in_tokens_per_s = None;
    let mut out_tokens_per_s = None;
    let mut net_rx_bytes_per_s = None;
    let mut net_tx_bytes_per_s = None;

    // If we have a session_key, compute rates against the prior sample for that same session.
    if let Some(sk) = session_key.clone() {
        let prev: Result<(i64, Option<i64>, Option<i64>, Option<i64>, Option<i64>, Option<i64>), _> = conn.query_row(
            r#"
            SELECT ts_ms, input_tokens, output_tokens, total_tokens, net_rx_bytes, net_tx_bytes
            FROM samples
            WHERE session_key = ?1 AND ts_ms < ?2
            ORDER BY ts_ms DESC
            LIMIT 1
            "#,
            rusqlite::params![sk, ts1],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)),
        );

        if let Ok((ts0, in0, out0, tot0, rx0, tx0)) = prev {
            let dt_s = (ts1 - ts0) as f64 / 1000.0;
            if dt_s > 0.0 {
                if let (Some(a), Some(b)) = (tot1, tot0) {
                    let d = a - b;
                    if d >= 0 {
                        tokens_per_s = Some(d as f64 / dt_s);
                    }
                }
                if let (Some(a), Some(b)) = (in1, in0) {
                    let d = a - b;
                    if d >= 0 {
                        in_tokens_per_s = Some(d as f64 / dt_s);
                    }
                }
                if let (Some(a), Some(b)) = (out1, out0) {
                    let d = a - b;
                    if d >= 0 {
                        out_tokens_per_s = Some(d as f64 / dt_s);
                    }
                }
                if let (Some(a), Some(b)) = (rx1, rx0) {
                    let d = a - b;
                    net_rx_bytes_per_s = Some(d as f64 / dt_s);
                }
                if let (Some(a), Some(b)) = (tx1, tx0) {
                    let d = a - b;
                    net_tx_bytes_per_s = Some(d as f64 / dt_s);
                }
            }
        }
    }

    Ok(LiveMetrics {
        ts_ms: ts1,
        session_key,
        model,
        input_tokens: in1,
        output_tokens: out1,
        total_tokens: tot1,
        remaining_tokens: rem1,
        context_tokens: ctx1,
        percent_used: pct1,
        tokens_per_s,
        in_tokens_per_s,
        out_tokens_per_s,
        net_rx_bytes_per_s,
        net_tx_bytes_per_s,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![get_live_metrics, get_rollups])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
