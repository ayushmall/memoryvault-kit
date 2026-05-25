#!/usr/bin/env python3
"""
Memory fill-quality eval — measure how well each memory was authored.

The kit's recall is only as good as its memories. A memory with a vague
title ("Meeting notes"), no event_date, three over-linked entities, and
a one-line body is *technically* in the vault but won't retrieve well
for any specific query. The authoring agent (Claude, during ingest)
either gets this right or doesn't.

This eval scores every memory on **rule-based** signals — fast, free,
no judge needed — and aggregates by source so we can target the
worst-authored ingest paths.

Score components (each 0–1, then averaged):

- **title_specificity** — does the title carry concrete facts (numbers,
  IDs, named people/projects)? Vague titles like "Meeting" or "Notes"
  score 0. "ENG-10451 [Done · high]: Build Parameterised Agents" scores 1.
- **required_fields** — are id, title, type, source, entities, importance
  all present and non-empty?
- **temporal_present** — for non-stateful memories, is event_date set
  (not null)? For stateful, is as_of_date set?
- **body_adequacy** — is the body more than just a stub (≥120 chars
  excluding boilerplate)?
- **entity_link_sanity** — entities + mentions count is in a reasonable
  range (1–25). Outliers (0 entities or 40+ links) score lower.
- **type_content_match** — title verbs match the declared type
  ("decided"/"shipped"/"will" → decision; "meeting"/"call"/"discussion" →
  event; "is the contact"/"reports to" → relationship).

Output:
- Per-memory score with breakdown (debug)
- Per-source-type aggregate (mean + min + 25th percentile)
- Top 10 worst-scoring memories with diagnostics

Run:
    python3 -m memoryvault_kit.eval.fill_quality
    python3 -m memoryvault_kit.eval.fill_quality --by-source
    python3 -m memoryvault_kit.eval.fill_quality --worst 20
"""
from __future__ import annotations

import os
import re
import statistics
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"

STATEFUL_TYPES = {"reference", "relationship", "user_fact", "preference"}
STATEFUL_ID_PREFIXES = ("mem_CODE_", "mem_REL_", "mem_KIT_", "mem_01JAGF", "mem_01JSEED", "mem_NOTE_")

VAGUE_TITLE_TOKENS = {
    "meeting", "notes", "discussion", "call", "sync", "update",
    "review", "check-in", "checkin", "1:1", "weekly", "daily",
    "untitled", "tbd", "todo",
}

DECISION_VERBS = ("decided", "decide", "approved", "rejected", "chose", "selected",
                  "committed", "moves to", "shipped", "ga'd", "ga ", "launched",
                  "deferred", "p0", "p1", "won't", "will not")
EVENT_VERBS = ("meeting", "call", "discussion", "sync", "kickoff", "review",
               "demo", "session", "onsite", "workshop", "interview")
REL_VERBS = ("is the contact", "reports to", "is the lead", "owns",
             "married to", "child of", "founded", "joined", "left", "is at")


def parse(text: str) -> dict:
    """Pull the bits we score on."""
    fm_end = text.find("---", 4)
    fm = text[:fm_end] if fm_end > 0 else text
    body = text[fm_end + 3:] if fm_end > 0 else ""

    def get(field):
        m = re.search(rf"^{field}:\s*(.*)$", fm, re.MULTILINE)
        return m.group(1).strip().strip("'\"") if m else ""

    def get_list(field):
        m = re.search(rf"^{field}:\s*(\[.*\])\s*$", fm, re.MULTILINE)
        if not m:
            return []
        return re.findall(r"\[\[([^\]]+)\]\]", m.group(1))

    return {
        "id": get("id"),
        "title": get("title"),
        "type": get("type"),
        "source": get("source") or get("source_host"),
        "event_date": get("event_date"),
        "as_of_date": get("as_of_date"),
        "importance": get("importance"),
        "entities": get_list("entities"),
        "mentions": get_list("mentions"),
        "body": body.strip(),
    }


def score_title_specificity(title: str) -> float:
    """1.0 if title has concrete facts; 0 if vague."""
    if not title or len(title) < 6:
        return 0.0
    t = title.lower()
    # Specific patterns: ticket ID, $amount, date, name-named, "(state · priority)"
    score = 0.0
    if re.search(r"\b[A-Z]{2,}-\d+\b", title):         # ENG-1234
        score += 0.4
    if re.search(r"\$[\d,]+\.?\d*[kKmMbB]?", title):   # $50k
        score += 0.3
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*\d", t):
        score += 0.2
    if re.search(r"\bPR\s*#\s*\d+", title):            # PR #20451
        score += 0.4
    if re.search(r"\[.*?·.*?\]", title):               # [Done · high]
        score += 0.3
    # Has named entity (capitalized 3+ char word that's not a stop word)
    if re.search(r"\b[A-Z][a-z]{3,}\b", title):
        score += 0.2
    # Penalize vague tokens
    vague_hits = sum(1 for v in VAGUE_TITLE_TOKENS if v in t)
    if vague_hits >= 2 and score < 0.4:
        score -= 0.3
    return max(0.0, min(1.0, score))


def score_required_fields(m: dict) -> float:
    """Fraction of required fields present + non-empty."""
    required = ["id", "title", "type", "source", "importance"]
    have = sum(1 for f in required if m.get(f))
    if not m.get("entities") and not m.get("mentions"):
        have -= 0.5  # at least one link expected
    return max(0.0, have / len(required))


def is_stateful(m: dict) -> bool:
    if m["type"] in STATEFUL_TYPES:
        return True
    if any(m["id"].startswith(p.removeprefix("mem_")) or m["id"].startswith(p)
           for p in STATEFUL_ID_PREFIXES):
        return True
    return False


def score_temporal(m: dict) -> float:
    """Non-stateful: needs event_date. Stateful: needs as_of_date."""
    if is_stateful(m):
        return 1.0 if m.get("as_of_date") else 0.0
    has_event = m.get("event_date") and m["event_date"] != "null"
    return 1.0 if has_event else 0.0


def score_body(m: dict) -> float:
    body = m["body"]
    # Strip boilerplate footers
    body = re.sub(r"\nSurfaced from:.*$", "", body, flags=re.DOTALL)
    body = re.sub(r"\nAuthored from a code read.*$", "", body, flags=re.DOTALL)
    chars = len(body)
    if chars < 50:
        return 0.0
    if chars < 120:
        return 0.5
    if chars < 300:
        return 0.85
    return 1.0


def score_entity_sanity(m: dict) -> float:
    n_ent = len(m["entities"])
    n_ment = len(m["mentions"])
    total = n_ent + n_ment
    if n_ent == 0:
        return 0.0
    if total > 35:
        return 0.5
    if total > 25:
        return 0.75
    return 1.0


def score_type_match(m: dict) -> float:
    title_low = m["title"].lower()
    body_low = m["body"].lower()[:600]
    t = m["type"]
    if t == "decision":
        return 1.0 if any(v in title_low or v in body_low for v in DECISION_VERBS) else 0.3
    if t == "event":
        return 1.0 if any(v in title_low or v in body_low for v in EVENT_VERBS) else 0.5
    if t == "relationship":
        return 1.0 if any(v in title_low or v in body_low for v in REL_VERBS) else 0.4
    # Other types are harder to validate by text — give pass
    return 0.85


def score_memory(m: dict) -> dict:
    parts = {
        "title_specificity": score_title_specificity(m["title"]),
        "required_fields":   score_required_fields(m),
        "temporal":          score_temporal(m),
        "body_adequacy":     score_body(m),
        "entity_sanity":     score_entity_sanity(m),
        "type_match":        score_type_match(m),
    }
    overall = sum(parts.values()) / len(parts)
    return {"overall": overall, **parts}


def detect_source(mem_id: str) -> str:
    body = mem_id.removeprefix("mem_")
    if body.startswith("INGEST_"):
        return "_".join(body.split("_", 2)[:2])
    return body.split("_", 1)[0]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-source", action="store_true")
    ap.add_argument("--worst", type=int, default=10)
    args = ap.parse_args()

    rows = []
    for p in MEM_DIR.glob("mem_*.md"):
        m = parse(p.read_text())
        s = score_memory(m)
        s["id"] = p.stem
        s["source"] = detect_source(p.stem)
        s["title"] = m["title"]
        rows.append(s)

    overall = statistics.mean(r["overall"] for r in rows)
    print(f"Scanned {len(rows)} memories. Overall fill quality: {overall:.3f}")
    print()
    print("Per-component (mean across all memories):")
    for k in ("title_specificity", "required_fields", "temporal", "body_adequacy",
              "entity_sanity", "type_match"):
        mu = statistics.mean(r[k] for r in rows)
        print(f"  {k:<22} {mu:.3f}")

    if args.by_source:
        print()
        print(f"{'source':<22} {'n':>5} {'mean':>7} {'min':>6} {'p25':>6} {'p50':>6}")
        print("-" * 60)
        by_src = defaultdict(list)
        for r in rows:
            by_src[r["source"]].append(r["overall"])
        for src in sorted(by_src, key=lambda s: -len(by_src[s])):
            vals = sorted(by_src[src])
            if len(vals) < 1: continue
            mu = statistics.mean(vals)
            p25 = vals[len(vals)//4]
            p50 = vals[len(vals)//2]
            print(f"  {src:<20} {len(vals):>5} {mu:>7.3f} {min(vals):>6.3f} {p25:>6.3f} {p50:>6.3f}")

    if args.worst:
        print()
        print(f"=== Worst {args.worst} memories ===")
        rows.sort(key=lambda r: r["overall"])
        for r in rows[:args.worst]:
            print(f"  {r['overall']:.2f}  {r['id']:<40} {r['title'][:60]}")
            weak = [k for k in ("title_specificity","required_fields","temporal","body_adequacy","entity_sanity","type_match") if r[k] < 0.5]
            if weak:
                print(f"        ↳ weak: {', '.join(weak)}")


if __name__ == "__main__":
    main()
