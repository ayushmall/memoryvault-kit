#!/usr/bin/env python3
"""
BM25 keyword retriever — keyword.0.2.

Replaces the naive (unique_hits×10 + total_hits) × (0.5 + importance) scorer with proper BM25:
  - IDF weighting (rare tokens like 'kedia' count more than common ones like 'agents')
  - Length normalization (long memories don't dominate by accident)
  - Saturation curve on TF (10 mentions of 'agents' aren't 10× more useful than 1)

Importance and alias-phrase bonuses are layered on top of BM25 score.
"""
import json
import math
import re
import sys
from pathlib import Path
from collections import Counter

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
MEM_DIR = VAULT / "memories" / "2026"
QUESTIONS = VAULT / "evals" / "retrieval" / "questions.jsonl"
ALIAS_MAP_PATH = Path("/tmp/alias_map.json")

ALIAS_BLOCKLIST = {
    "customer", "vendor", "founder", "ceo", "cto", "tech lead", "eng lead",
    "engineering lead", "agents", "viz", "ace", "vab", "pf", "wow", "cls",
    "scim", "sso", "mcp", "gcp", "okta", "gui",
}

STOPWORDS = set("""
a an the is are was were be been being and or but if then of to in on at by for with about as it its this that
what who when where why how which whose whom did do does done has have had can could would should will may might
our your their his her my we i you they them us he she who's whats lets let
""".split())

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_]+")

# BM25 hyperparams
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def parse_memory(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block, body = parts[1], parts[2].strip()
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    entities = re.findall(r"\[\[([^\]]+)\]\]", fm.get("entities", ""))
    tags = re.findall(r"[a-z0-9\-_]+", fm.get("tags", "").lower())
    try:
        importance = float(fm.get("importance", "0.5"))
    except ValueError:
        importance = 0.5
    title = fm.get("title", "").strip().strip('"').strip("'")
    return {
        "id": fm.get("id", path.stem),
        "title": title,
        "entities": entities,
        "tags": tags,
        "importance": importance,
        "body": body,
        "path": str(path),
    }


def load_memories():
    mems = []
    for p in sorted(MEM_DIR.glob("mem_*.md")):
        m = parse_memory(p)
        if m:
            mems.append(m)
    return mems


def build_index(mems: list) -> dict:
    """Pre-compute per-memory TF, doc length, and corpus-level DF + avgdl + IDF."""
    docs = []
    df = Counter()
    total_len = 0
    for m in mems:
        haystack = (m["title"] + " " + m["body"] + " " + " ".join(m["entities"]) + " " + " ".join(m["tags"]))
        toks = tokenize(haystack)
        tf = Counter(toks)
        docs.append({"id": m["id"], "tf": tf, "dl": len(toks), "mem": m, "haystack_low": haystack.lower()})
        for t in tf:
            df[t] += 1
        total_len += len(toks)
    N = len(docs)
    avgdl = total_len / N if N else 1.0
    # BM25 IDF (Lucene variant): log(1 + (N - df + 0.5) / (df + 0.5))
    idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
    return {"docs": docs, "df": df, "idf": idf, "avgdl": avgdl, "N": N}


_ALIAS_IDX = None


def load_alias_index():
    if not ALIAS_MAP_PATH.exists():
        return {}
    raw = json.loads(ALIAS_MAP_PATH.read_text())
    idx = {}
    for canonical, aliases in raw.items():
        all_low = [p.lower() for p in [canonical] + list(aliases)]
        keep = [p for p in all_low if p not in ALIAS_BLOCKLIST and "@" not in p and len(p) >= 4]
        if len(keep) < 2:
            continue
        for p in keep:
            idx.setdefault(p, set()).update(keep)
    return idx


def query_alias_phrases(question: str) -> list[str]:
    global _ALIAS_IDX
    if _ALIAS_IDX is None:
        _ALIAS_IDX = load_alias_index()
    qlow = question.lower()
    extras = set()
    for phrase, group in _ALIAS_IDX.items():
        if phrase in qlow:
            for alt in group:
                if alt != phrase and alt not in qlow:
                    extras.add(alt)
    return list(extras)


def bm25_score(qtoks: list, doc: dict, idf: dict, avgdl: float) -> float:
    """Standard BM25 over a single doc."""
    if not qtoks:
        return 0.0
    score = 0.0
    dl_norm = 1 - B + B * doc["dl"] / max(avgdl, 1)
    for t in qtoks:
        if t not in idf:
            continue
        tf = doc["tf"].get(t, 0)
        if tf == 0:
            continue
        score += idf[t] * (tf * (K1 + 1)) / (tf + K1 * dl_norm)
    return score


def score(question: str, doc: dict, idf: dict, avgdl: float) -> float:
    qtoks = tokenize(question)
    if not qtoks:
        return 0.0
    base = bm25_score(qtoks, doc, idf, avgdl)
    # Alias phrase bonus: each matched alias phrase adds half an "average" BM25 hit
    phrase_bonus = 0.0
    for ph in query_alias_phrases(question):
        if ph in doc["haystack_low"]:
            phrase_bonus += 1.5
    if base == 0 and phrase_bonus == 0:
        return 0.0
    # Importance multiplier: keep modest. Prevents importance from dominating.
    imp = doc["mem"]["importance"]
    return (base + phrase_bonus) * (0.7 + 0.6 * imp)  # range [0.7, 1.3]


def retrieve(question: str, index: dict, k: int = 10) -> list[dict]:
    scored = []
    for doc in index["docs"]:
        s = score(question, doc, index["idf"], index["avgdl"])
        if s > 0:
            scored.append((s, doc))
    scored.sort(key=lambda x: -x[0])
    return [{"id": d["mem"]["id"], "score": round(s, 3),
             "title": d["mem"]["title"], "entities": d["mem"]["entities"],
             "tags": d["mem"]["tags"]}
            for s, d in scored[:k]]


def main():
    mems = load_memories()
    index = build_index(mems)
    print(f"Indexed {index['N']} memories, avgdl={index['avgdl']:.1f}, vocab={len(index['idf'])}",
          file=sys.stderr)
    questions = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bm25_output.jsonl"
    with open(out_path, "w") as f:
        for q in questions:
            results = retrieve(q["question"], index, k=10)
            f.write(json.dumps({"id": q["id"], "retrieved": [r["id"] for r in results]}) + "\n")
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
