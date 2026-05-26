#!/usr/bin/env python3
"""
BM25 keyword retriever — keyword.0.2.

Replaces the naive (unique_hits×10 + total_hits) × (0.5 + importance) scorer with proper BM25:
  - IDF weighting (rare tokens like 'doe' count more than common ones like 'agents')
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
# Alias map lives in the vault (was /tmp, which is volatile and wipes on reboot —
# we discovered the kit had been running with an empty alias map for a long time).
# Falls back to /tmp only for backward compat with existing installs.
ALIAS_MAP_PATH = next(
    (p for p in [VAULT / ".alias_map.json", Path("/tmp/alias_map.json")] if p.exists()),
    VAULT / ".alias_map.json",
)

ALIAS_BLOCKLIST = {
    "customer", "vendor", "founder", "ceo", "cto", "tech lead", "eng lead",
    "engineering lead", "agents", "viz",
    "scim", "sso", "mcp", "gcp", "okta", "gui",
}

STOPWORDS = set("""
a an the is are was were be been being and or but if then of to in on at by for with about as it its this that
what who when where why how which whose whom did do does done has have had can could would should will may might
our your their his her my we i you they them us he she who's whats lets let
""".split())

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_]+")

# BM25 hyperparams — defaults; overridable via .mvkit/retrieval_config.json
try:
    from memoryvault_kit.retrieval.config import get as _cfg
    K1 = _cfg("bm25.k1", 1.5)
    B = _cfg("bm25.b", 0.75)
except Exception:
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
    mentions = re.findall(r"\[\[([^\]]+)\]\]", fm.get("mentions", ""))
    tags = re.findall(r"[a-z0-9\-_]+", fm.get("tags", "").lower())
    try:
        importance = float(fm.get("importance", "0.5"))
    except ValueError:
        importance = 0.5
    title = fm.get("title", "").strip().strip('"').strip("'")
    mem_id = fm.get("id", path.stem).strip().strip('"').strip("'")
    # Pull common structured fields (priority, state, type, source) for D11
    # filter retrieval. Other downstream code (retrievers, eval) doesn't read
    # these directly; they're available via mem["fm"] for filters.
    def _strip(s):
        return (s or "").strip().strip('"').strip("'") if isinstance(s, str) else s
    return {
        "id": mem_id,
        "title": title,
        "entities": entities,
        "mentions": mentions,
        "tags": tags,
        "importance": importance,
        "body": body,
        "path": str(path),
        # Extra structured fields for filter-based retrieval (D11):
        "type": _strip(fm.get("type")),
        "state": _strip(fm.get("state")),
        "priority": _strip(fm.get("priority")),
        "source": _strip(fm.get("source")),
        "assignee": _strip(fm.get("assignee")),
        "updated": _strip(fm.get("updated")),
        "created": _strip(fm.get("created")),
        "fm": fm,  # full raw frontmatter for any other field
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
        # entities = structural participants (3× weight, repeated)
        # mentions = peripheral references (1× weight, single)
        ent_weight = " ".join(m["entities"]) + " " + " ".join(m["entities"]) + " " + " ".join(m["entities"])
        ment_weight = " ".join(m.get("mentions", []))
        haystack = (m["title"] + " " + m["body"] + " " + ent_weight + " " + ment_weight + " " + " ".join(m["tags"]))
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
_ALIAS_DF = None  # document frequency for each alias phrase — used to skip noise expansions
_ALIAS_DF_THRESHOLD = 0.20  # phrase appearing in >20% of memories is too common to expand
_CURRENT_DOCS = None  # set by retrieve() to make DF computation possible


def _build_alias_df(docs):
    """Count how many memories contain each alias phrase in their haystack."""
    if _ALIAS_IDX is None:
        return {}
    df = {}
    for phrase in _ALIAS_IDX:
        c = sum(1 for d in docs if phrase in d["haystack_low"])
        df[phrase] = c
    return df


def load_alias_index():
    """Build alias-phrase clusters from the alias map.

    Returns: dict[lowercased_surface_form → set of related surface forms].

    Supports two on-disk schemas:
      - new nested: {"canonical_to_aliases": {canonical: [aliases]}, ...}
      - legacy flat: {canonical: [aliases]}

    Length filter: ≥3 chars (was ≥4 — that killed common 3-char acronyms,
    which are exactly the high-value aliases we built this map to handle).
    """
    if not ALIAS_MAP_PATH.exists():
        return {}
    raw = json.loads(ALIAS_MAP_PATH.read_text())
    # New nested schema?
    if isinstance(raw, dict) and "canonical_to_aliases" in raw:
        clusters = raw["canonical_to_aliases"]
    else:
        clusters = raw  # legacy flat schema
    idx = {}
    for canonical, aliases in clusters.items():
        all_low = [p.lower() for p in [canonical] + list(aliases)]
        # Note: we used to strip "@"-containing forms here, but that killed the
        # entire class of email-handle queries ("what's the latest on x@y.com").
        # Emails are LEGITIMATE aliases for people and we want them indexed.
        keep = [
            p for p in all_low
            if p not in ALIAS_BLOCKLIST and len(p) >= 3
        ]
        if len(keep) < 2:
            continue
        for p in keep:
            idx.setdefault(p, set()).update(keep)
    return idx


def query_alias_phrases(question: str, docs=None) -> list[str]:
    """Return alias phrases to use for query-side expansion.

    Filters out alias phrases that appear in >20% of memories — these add no
    discriminative signal and inflate the bonus for every doc symmetrically
    (i.e., the company-name problem in a company-internal vault).
    """
    global _ALIAS_IDX, _ALIAS_DF
    if _ALIAS_IDX is None:
        _ALIAS_IDX = load_alias_index()
    if _ALIAS_DF is None and docs is not None:
        n = len(docs)
        if n > 0:
            _ALIAS_DF = {ph: cnt / n for ph, cnt in _build_alias_df(docs).items()}
    qlow = question.lower()
    extras = set()
    for phrase, group in _ALIAS_IDX.items():
        if phrase in qlow:
            for alt in group:
                if alt == phrase or alt in qlow:
                    continue
                # Skip alts that are too common — they boost everything equally
                if _ALIAS_DF and _ALIAS_DF.get(alt, 0) > _ALIAS_DF_THRESHOLD:
                    continue
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
    # Alias phrase bonus: each matched alias phrase adds a meaningful BM25 hit.
    # Phrases too common (>20% DF) are filtered out by query_alias_phrases.
    phrase_bonus = 0.0
    for ph in query_alias_phrases(question, _CURRENT_DOCS):
        if ph in doc["haystack_low"]:
            phrase_bonus += 2.5  # bumped from 1.5 — rare aliases are strong signal
    if base == 0 and phrase_bonus == 0:
        return 0.0
    # Importance multiplier: keep modest. Prevents importance from dominating.
    imp = doc["mem"]["importance"]
    return (base + phrase_bonus) * (0.7 + 0.6 * imp)  # range [0.7, 1.3]


def retrieve(question: str, index: dict, k: int = 10) -> list[dict]:
    global _CURRENT_DOCS
    _CURRENT_DOCS = index["docs"]
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
