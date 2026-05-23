#!/usr/bin/env python3
"""
Naive grep baseline — the floor any retriever has to clear to claim value.

Approach:
  - Tokenize the question (no stopwords, no IDF)
  - For each memory, count how many query tokens appear anywhere in body+title+tags
  - Rank by raw hit count

No length normalization, no IDF, no graph. This is what "grep memories/ for words"
gives you. Useful as the "without any retriever" baseline in evals.
"""
import json
import os
import re
import sys
from pathlib import Path
from collections import Counter

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
MEM_DIR = VAULT / "memories"
QUESTIONS = VAULT / "evals" / "retrieval" / "questions.jsonl"

STOPWORDS = set("the is are was a an of to in on at by for with about as it this that what who".split())
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_]+")


def tokenize(text):
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def parse_memory(p):
    text = p.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block, body = parts[1], parts[2]
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return {"id": fm.get("id", p.stem),
            "title": fm.get("title", ""),
            "haystack": (fm.get("title", "") + " " + body + " " +
                         fm.get("tags", "") + " " + fm.get("entities", "")).lower()}


def load_memories():
    return [m for m in (parse_memory(p) for p in MEM_DIR.rglob("mem_*.md")) if m]


def retrieve(question, mems, k=10):
    qtoks = tokenize(question)
    if not qtoks:
        return []
    scored = []
    for m in mems:
        hits = sum(m["haystack"].count(t) for t in qtoks)
        if hits > 0:
            scored.append((hits, m))
    scored.sort(key=lambda x: -x[0])
    return [{"id": m["id"], "title": m["title"], "score": s} for s, m in scored[:k]]


def main():
    mems = load_memories()
    print(f"Indexed {len(mems)} memories (grep baseline)", file=sys.stderr)
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grep_output.jsonl"
    questions = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    with open(out_path, "w") as f:
        for q in questions:
            r = retrieve(q["question"], mems, k=10)
            f.write(json.dumps({"id": q["id"], "retrieved": [x["id"] for x in r]}) + "\n")
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
