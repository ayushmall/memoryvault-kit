#!/usr/bin/env python3
"""
Build a self-contained HTML dashboard from evals/results_log.jsonl.

Run:
    python3 evals/dashboard/build.py
    open evals/dashboard/index.html
"""
import json
from pathlib import Path

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
LOG = VAULT / "evals" / "results_log.jsonl"
GRAPH_LOG = VAULT / "evals" / "graph" / "audit_log.jsonl"
OUT = VAULT / "evals" / "dashboard" / "index.html"

BUCKETS = [
    "needle-in-haystack", "negation-rejection", "multi-hop", "temporal",
    "alias", "disambiguation", "aggregate", "lateral", "paraphrase", "abstention",
]


def load_runs():
    if not LOG.exists():
        return []
    runs = []
    for line in LOG.read_text().splitlines():
        if not line.strip():
            continue
        runs.append(json.loads(line))
    return runs


def load_graph_snapshots():
    if not GRAPH_LOG.exists():
        return []
    snaps = []
    for line in GRAPH_LOG.read_text().splitlines():
        if line.strip():
            snaps.append(json.loads(line))
    return snaps


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MemoryVault — Retrieval Eval Dashboard</title>
<style>
  :root {
    --bg: #0f1115; --panel: #161a22; --border: #232938;
    --fg: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --good: #3fb950; --warn: #d29922; --bad: #f85149;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg); font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         margin: 0; padding: 24px; max-width: 1400px; margin: 0 auto; }
  h1 { margin: 0 0 4px; font-size: 22px; font-weight: 600; }
  h2 { margin: 32px 0 12px; font-size: 16px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: .3px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.note { white-space: normal; color: var(--muted); font-size: 12px; max-width: 380px; }
  .retriever { font-weight: 600; color: var(--accent); }
  .delta-pos { color: var(--good); }
  .delta-neg { color: var(--bad); }
  .heatcell { display: inline-block; width: 56px; padding: 6px 4px; text-align: center;
              border-right: 1px solid var(--bg); font-variant-numeric: tabular-nums; font-size: 12px; }
  .heatcell.empty { background: #1f242e; color: #555; }
  svg { display: block; }
  .legend { font-size: 12px; color: var(--muted); display: flex; gap: 16px; margin-top: 8px; }
  .legend .sw { display: inline-block; width: 12px; height: 12px; border-radius: 2px; margin-right: 4px; vertical-align: -2px; }
  details summary { cursor: pointer; color: var(--accent); padding: 4px 0; user-select: none; }
  pre { background: #0a0d12; padding: 12px; border-radius: 6px; font-size: 12px; overflow-x: auto; color: #c9d1d9; }
</style>
</head>
<body>

<h1>MemoryVault — Retrieval Eval Dashboard</h1>
<div class="sub">Append-only log of retriever runs. Each row is one experiment; metrics over the same 220-question test set unless noted.</div>

<h2>Top-line trend</h2>
<div class="panel" id="trend"></div>

<h2>Run leaderboard</h2>
<div class="panel"><table id="leaderboard"></table></div>

<h2>Per-bucket Recall@5 heatmap</h2>
<div class="panel" id="heatmap"></div>

<h2>Graph health</h2>
<div class="panel" id="graph-health"></div>

<h2>Run details</h2>
<div class="panel" id="details"></div>

<script>
const RUNS = __RUNS__;
const BUCKETS = __BUCKETS__;
const GRAPH_SNAPS = __GRAPH_SNAPS__;

function fmt(v) {
  if (v == null || v === "?") return "—";
  if (typeof v === "number") return v.toFixed(3);
  return v;
}

function deltaClass(cur, prev) {
  if (prev == null || cur == null) return "";
  if (cur > prev) return "delta-pos";
  if (cur < prev) return "delta-neg";
  return "";
}

function deltaArrow(cur, prev) {
  if (prev == null || cur == null) return "";
  const d = cur - prev;
  if (Math.abs(d) < 1e-4) return "";
  return d > 0 ? ` ▲${d.toFixed(3)}` : ` ▼${(-d).toFixed(3)}`;
}

// --- Trend chart ---
function renderTrend() {
  const W = 1000, H = 280, P = 40;
  const metrics = [
    {key: "recall_at_5", label: "R@5", color: "#58a6ff"},
    {key: "recall_at_10", label: "R@10", color: "#3fb950"},
    {key: "mrr", label: "MRR", color: "#d29922"},
    {key: "abstain_correct_rate", label: "Abstain", color: "#bc8cff"},
  ];
  const runs220 = RUNS.filter(r => r.n_questions === 220);
  const N = runs220.length;
  if (!N) return;
  const xStep = (W - P*2) / Math.max(N - 1, 1);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`;
  // grid
  for (let i = 0; i <= 10; i++) {
    const y = P + (H - P*2) * (1 - i/10);
    svg += `<line x1="${P}" y1="${y}" x2="${W-P}" y2="${y}" stroke="#232938" stroke-width="1"/>`;
    svg += `<text x="8" y="${y+4}" fill="#8b949e" font-size="11">${(i/10).toFixed(1)}</text>`;
  }
  // x labels
  runs220.forEach((r, i) => {
    const x = P + i * xStep;
    svg += `<text x="${x}" y="${H-12}" fill="#8b949e" font-size="11" text-anchor="middle">${r.retriever}</text>`;
  });
  // lines per metric
  metrics.forEach(m => {
    const pts = runs220.map((r, i) => {
      const v = r[m.key];
      if (v == null) return null;
      const x = P + i * xStep;
      const y = P + (H - P*2) * (1 - v);
      return [x, y, v];
    }).filter(p => p);
    if (pts.length < 1) return;
    const path = pts.map((p, i) => (i ? "L" : "M") + p[0] + " " + p[1]).join(" ");
    svg += `<path d="${path}" stroke="${m.color}" fill="none" stroke-width="2"/>`;
    pts.forEach(p => {
      svg += `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="${m.color}"/>`;
    });
  });
  svg += `</svg>`;
  // legend
  let legend = `<div class="legend">`;
  metrics.forEach(m => { legend += `<span><span class="sw" style="background:${m.color}"></span>${m.label}</span>`; });
  legend += `</div>`;
  document.getElementById("trend").innerHTML = svg + legend;
}

// --- Leaderboard ---
function renderLeaderboard() {
  // Find best previous keyword run for delta reference
  const head = `
    <thead><tr>
      <th>Retriever</th><th>n</th>
      <th class="num">R@5</th><th class="num">R@10</th><th class="num">MRR</th>
      <th class="num">Ent@5 strict</th><th class="num">Abstain</th>
      <th>Note</th>
    </tr></thead>`;
  let baseline = null;
  for (const r of RUNS) { if (r.retriever === "keyword" && r.n_questions === 220) { baseline = r; break; } }
  const rows = RUNS.slice().reverse().map(r => {
    const isBaseline = r === baseline;
    const r5 = r.recall_at_5, r10 = r.recall_at_10, mrr = r.mrr;
    const es = r.entity_recall_at_5_strict, ab = r.abstain_correct_rate;
    const cmp = (cur) => baseline && !isBaseline ? deltaArrow(cur, baseline.recall_at_5) : "";
    return `
      <tr>
        <td class="retriever">${r.retriever}</td>
        <td>${r.n_questions ?? "—"}</td>
        <td class="num"><span class="${baseline && !isBaseline ? deltaClass(r5, baseline.recall_at_5) : ''}">${fmt(r5)}${baseline && !isBaseline ? deltaArrow(r5, baseline.recall_at_5) : ''}</span></td>
        <td class="num"><span class="${baseline && !isBaseline ? deltaClass(r10, baseline.recall_at_10) : ''}">${fmt(r10)}${baseline && !isBaseline ? deltaArrow(r10, baseline.recall_at_10) : ''}</span></td>
        <td class="num">${fmt(mrr)}</td>
        <td class="num">${fmt(es)}</td>
        <td class="num">${fmt(ab)}</td>
        <td class="note">${r.note ?? ""}</td>
      </tr>`;
  }).join("");
  document.getElementById("leaderboard").innerHTML = head + "<tbody>" + rows + "</tbody>";
}

// --- Heatmap ---
function colorFor(v) {
  if (v == null) return "#1f242e";
  // cool->warm gradient: 0=red, .5=yellow, 1=green
  const r = Math.round(255 * (1 - Math.min(1, v)));
  const g = Math.round(180 * Math.min(1, v));
  const b = 60;
  return `rgb(${r},${g},${b})`;
}
function renderHeatmap() {
  const runs220 = RUNS.filter(r => r.n_questions === 220 && r.by_bucket);
  let html = `<table style="border-collapse:separate; border-spacing:0;">`;
  html += `<thead><tr><th></th>`;
  BUCKETS.forEach(b => html += `<th style="font-size:11px; text-align:center; padding:4px;">${b.replace('-', '‑')}</th>`);
  html += `</tr></thead><tbody>`;
  runs220.forEach(r => {
    html += `<tr><td class="retriever">${r.retriever}</td>`;
    BUCKETS.forEach(b => {
      const v = r.by_bucket[b] && r.by_bucket[b].recall_at_5;
      const txt = v == null ? "—" : v.toFixed(2);
      const bg = colorFor(v);
      html += `<td class="heatcell" style="background:${bg}; color:${v != null && v < 0.5 ? '#fff' : '#0a0d12'}; font-weight:600;">${txt}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table>`;
  html += `<div class="legend"><span>Recall@5 per bucket — green=good, red=poor. Greys = bucket missing from run.</span></div>`;
  document.getElementById("heatmap").innerHTML = html;
}

// --- Details ---
function renderDetails() {
  const runs220 = RUNS.filter(r => r.n_questions === 220);
  const html = runs220.slice().reverse().map(r => `
    <details>
      <summary>${r.retriever} — ${r.timestamp ?? ''}</summary>
      <pre>${JSON.stringify(r, null, 2)}</pre>
    </details>
  `).join("");
  document.getElementById("details").innerHTML = html;
}

// --- Graph health ---
function renderGraphHealth() {
  if (!GRAPH_SNAPS.length) {
    document.getElementById("graph-health").innerHTML = "<i style='color:#8b949e'>no audit_log yet — run evals/graph/track.py</i>";
    return;
  }
  // KPI table comparing first vs latest snapshot
  const first = GRAPH_SNAPS[0];
  const latest = GRAPH_SNAPS[GRAPH_SNAPS.length - 1];
  // Group: lower-is-better metrics (defects), higher-is-better metrics (coverage)
  const metrics = [
    {key: "n_memories", label: "memories", goal: "up"},
    {key: "n_entities_in_use", label: "entities in use", goal: "up"},
    {key: "useful_entities", label: "useful entities (df 2-20)", goal: "up"},
    {key: "pct_memories_with_entities", label: "% memories tagged", goal: "up", fmt: "pct"},
    {key: "biggest_component_share", label: "graph connectedness", goal: "up", fmt: "pct"},
    {key: "dead_wikilinks", label: "dead wikilinks", goal: "down"},
    {key: "orphan_entity_files", label: "orphan entity files", goal: "down"},
    {key: "entities_without_aliases", label: "entities without aliases", goal: "down"},
    {key: "memories_with_no_edges", label: "memories with no edges", goal: "down"},
    {key: "singleton_entities", label: "singleton entities (dead-end)", goal: "down"},
    {key: "lint_errors", label: "lint errors", goal: "down"},
    {key: "lint_warnings", label: "lint warnings", goal: "down"},
  ];
  let html = `<table>
    <thead><tr><th>Metric</th><th class="num">First</th><th class="num">Latest</th><th class="num">Δ</th><th></th></tr></thead><tbody>`;
  metrics.forEach(m => {
    const a = first[m.key], b = latest[m.key];
    if (a == null || b == null) return;
    const delta = b - a;
    let direction = "";
    if (Math.abs(delta) > 0.0001) {
      const better = (m.goal === "up" && delta > 0) || (m.goal === "down" && delta < 0);
      direction = better ? "✓" : "⚠";
    }
    const fmtVal = (v) => m.fmt === "pct" ? (v*100).toFixed(1) + "%" : (Number.isInteger(v) ? v : v.toFixed(2));
    const cls = direction === "✓" ? "delta-pos" : (direction === "⚠" ? "delta-neg" : "");
    html += `<tr>
      <td>${m.label}</td>
      <td class="num">${fmtVal(a)}</td>
      <td class="num">${fmtVal(b)}</td>
      <td class="num ${cls}">${direction} ${delta > 0 ? "+" : ""}${m.fmt === "pct" ? (delta*100).toFixed(1)+"pp" : (Number.isInteger(delta) ? delta : delta.toFixed(2))}</td>
      <td style="font-size:11px; color:var(--muted)">goal: ${m.goal}</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  // Snapshot timeline
  html += `<div style="margin-top:12px; font-size:12px; color:var(--muted);">
    ${GRAPH_SNAPS.length} snapshots logged.
    First: ${first.timestamp} (${first.note || "—"}). Latest: ${latest.timestamp} (${latest.note || "—"}).
  </div>`;
  document.getElementById("graph-health").innerHTML = html;
}

renderTrend();
renderLeaderboard();
renderHeatmap();
renderGraphHealth();
renderDetails();
</script>
</body>
</html>
"""


def main():
    runs = load_runs()
    snaps = load_graph_snapshots()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = (HTML
        .replace("__RUNS__", json.dumps(runs))
        .replace("__BUCKETS__", json.dumps(BUCKETS))
        .replace("__GRAPH_SNAPS__", json.dumps(snaps)))
    OUT.write_text(html)
    print(f"Wrote {OUT} ({len(runs)} runs, {len(snaps)} graph snapshots)")


if __name__ == "__main__":
    main()
