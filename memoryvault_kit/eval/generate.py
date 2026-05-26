#!/usr/bin/env python3
"""
Generate eval questions from the user's actual vault.

Replaces the placeholder `<person>`/`<month>` templates with real questions
that reference the user's actual entities and memories. The user gets a
runnable eval set immediately — no manual annotation required.

Three bucket generators (enough to demonstrate retrieval signal without
shipping the full 513-line reverse-design pipeline):

  needle      — rare entities (df=1): "What's in our notes about <entity>?"
  alias       — entities with ≥2 aliases: "What's the latest on <alias>?"
  aggregate   — entities with df≥3: "Summarize what we know about <entity>"

Default: ~30 questions total. Configurable via `--n`.

Run:
    memory eval init --from-vault         # generates + writes
    memory eval init --from-vault --n 50  # bigger starter set
"""
from __future__ import annotations

import json
import os
import random
import re
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
ENTITIES_DIR = VAULT / "entities"


def _parse_fm(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                fm[key] = []
            else:
                fm[key] = [s.strip().strip('"').strip("'") for s in re.split(r",\s*", inner)]
        else:
            fm[key] = val.strip('"').strip("'")
    return fm


def load_memories():
    out = []
    if not MEM_DIR.is_dir():
        return out
    for p in MEM_DIR.rglob("*.md"):
        try:
            text = p.read_text()
            fm = _parse_fm(text)
            if not fm.get("id"):
                continue
            body = text.split("---", 2)[-1].strip() if "---" in text else text
            out.append({
                "id": fm["id"],
                "title": fm.get("title", ""),
                "entities": fm.get("entities", []) or [],
                "tags": fm.get("tags", []) or [],
                "body": body,
            })
        except Exception:
            continue
    return out


def load_entities():
    out = {}
    if not ENTITIES_DIR.is_dir():
        return out
    for p in ENTITIES_DIR.rglob("*.md"):
        try:
            fm = _parse_fm(p.read_text())
            name = (fm.get("name") or "").strip()
            if not name:
                continue
            aliases = fm.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            out[name] = {
                "name": name,
                "aliases": [a for a in aliases if a],
                "type": fm.get("type", "unknown"),
            }
        except Exception:
            continue
    return out


def compute_df(memories: list, entities: dict) -> dict[str, int]:
    """For each entity name, count how many memories reference it."""
    df = defaultdict(int)
    for m in memories:
        # Memory's `entities` is a list like ["[[Foo]]", "[[Bar Baz]]"]
        for e in m.get("entities", []):
            stripped = e.strip("[]").strip()
            if stripped in entities:
                df[stripped] += 1
    return dict(df)


def memories_for_entity(name: str, memories: list) -> list:
    needle = f"[[{name}]]".lower()
    return [m for m in memories if any(needle == e.lower() for e in m.get("entities", []))]


def gen_needle(memories, entities, df, n=10) -> list[dict]:
    """Rare entities (df=1) — single-source questions."""
    candidates = [name for name, count in df.items() if count == 1]
    random.shuffle(candidates)
    out = []
    for name in candidates[:n]:
        mems = memories_for_entity(name, memories)
        if not mems:
            continue
        gold = mems[0]
        out.append({
            "id": f"q_needle_{len(out)+1:03d}",
            "bucket": "needle-in-haystack",
            "question": f"What do we have on {name} in our notes?",
            "expected_memory_ids": [gold["id"]],
            "expected_tags": gold.get("tags", []),
            "notes": f"Rare entity (df=1) — only mentioned in {gold.get('title','')[:60]}",
        })
    return out


def gen_alias(memories, entities, df, n=10) -> list[dict]:
    """Entities with ≥1 alias — test alias resolution."""
    candidates = [
        (name, ent) for name, ent in entities.items()
        if ent.get("aliases") and df.get(name, 0) >= 1
    ]
    random.shuffle(candidates)
    out = []
    for name, ent in candidates[:n]:
        alias = ent["aliases"][0]
        mems = memories_for_entity(name, memories)
        if not mems:
            continue
        gold = mems[0]
        out.append({
            "id": f"q_alias_{len(out)+1:03d}",
            "bucket": "alias",
            "question": f"What's the latest on {alias}?",
            "expected_memory_ids": [gold["id"]],
            "expected_tags": gold.get("tags", []),
            "notes": f"Alias '{alias}' resolves to canonical '{name}'",
        })
    return out


def gen_aggregate(memories, entities, df, n=10) -> list[dict]:
    """High-df entities — broad-survey questions."""
    candidates = [(name, c) for name, c in df.items() if c >= 3]
    candidates.sort(key=lambda x: -x[1])  # most-mentioned first
    random.shuffle(candidates := candidates[:n*3])  # mix the top 3n
    out = []
    for name, count in candidates[:n]:
        mems = memories_for_entity(name, memories)
        if len(mems) < 2:
            continue
        out.append({
            "id": f"q_aggregate_{len(out)+1:03d}",
            "bucket": "aggregate",
            "question": f"Summarize what we know about {name}.",
            "expected_memory_ids": [m["id"] for m in mems[:5]],  # any of these counts
            "expected_tags": [],
            "notes": f"High-df entity ({count} memories); any of the top-5 mentioned is acceptable",
        })
    return out


def generate_eval_set(n_total: int = 30, seed: int = 42) -> list[dict]:
    random.seed(seed)
    memories = load_memories()
    entities = load_entities()
    if not memories:
        return []
    df = compute_df(memories, entities)

    # Split target across buckets
    n_each = max(3, n_total // 3)
    questions = []
    questions += gen_needle(memories, entities, df, n=n_each)
    questions += gen_alias(memories, entities, df, n=n_each)
    questions += gen_aggregate(memories, entities, df, n=n_each)
    return questions[:n_total]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=None,
                    help="output path (default: <vault>/evals/retrieval/questions.jsonl)")
    args = ap.parse_args()

    qs = generate_eval_set(n_total=args.n, seed=args.seed)
    if not qs:
        print("No memories found in vault — can't generate questions.")
        return 1

    out_path = Path(args.output) if args.output else (
        VAULT / "evals" / "retrieval" / "questions.jsonl"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for q in qs:
            f.write(json.dumps(q) + "\n")

    print(f"Wrote {len(qs)} questions to {out_path}")
    print(f"  Bucket breakdown:")
    from collections import Counter
    c = Counter(q["bucket"] for q in qs)
    for bucket, n in c.most_common():
        print(f"    {bucket:<25} {n}")
    print()
    print(f"Run `memory eval run` to score them against your retriever.")
    return 0


if __name__ == "__main__":
    main()
