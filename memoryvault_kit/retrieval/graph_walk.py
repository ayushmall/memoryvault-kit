#!/usr/bin/env python3
"""
graph.0.4 — graph walk on top of BM25.

Changes vs graph.0.3:
  - Switched keyword base from naive scorer to BM25 (keyword.0.2).
  - k_seed bumped from 3 to 5 (more bridges).
  - `related:` edges walked from EVERY top-30 candidate, not just top-K seeds
    (the related: field is author-curated; treat it as ground truth).
  - Score-threshold abstainer: if top-1 BM25 < threshold T, return [].
"""
import json
import re
import sys
import math
from pathlib import Path
from collections import defaultdict
import importlib.util

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
MEM_DIR = VAULT / "memories" / "2026"
ENT_DIR = VAULT / "entities"
QUESTIONS = VAULT / "evals" / "retrieval" / "questions.jsonl"

_bm25_spec = importlib.util.spec_from_file_location("bm25", str(Path(__file__).parent / "bm25.py"))
bm25 = importlib.util.module_from_spec(_bm25_spec); _bm25_spec.loader.exec_module(bm25)


def parse_memory_full(path):
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
    related = re.findall(r"mem_[A-Za-z0-9_]+", fm.get("related", ""))
    try:
        importance = float(fm.get("importance", "0.5"))
    except ValueError:
        importance = 0.5
    return {
        "id": fm.get("id", path.stem),
        "title": fm.get("title", "").strip().strip('"').strip("'"),
        "entities": entities,
        "tags": tags,
        "importance": importance,
        "body": body,
        "related": related,
        # Citation triad — surfaced by memory_ask so consumers can cite back
        # to the original Slack thread / Notion page / Granola meeting etc.
        "source": (fm.get("source") or fm.get("source_host", "")).strip().strip('"').strip("'") or None,
        "source_ref": fm.get("source_ref", "").strip().strip('"').strip("'") or None,
        "event_date": fm.get("event_date", "").strip().strip('"').strip("'") or None,
    }


def load_full_memories():
    return [m for m in (parse_memory_full(p) for p in sorted(MEM_DIR.glob("mem_*.md"))) if m]


def build_entity_index(mems):
    idx = defaultdict(list)
    for m in mems:
        for e in m["entities"]:
            idx[e.lower()].append(m["id"])
    return idx


def load_entity_aliases():
    aliases = {}
    for f in ENT_DIR.rglob("*.md"):
        try:
            text = f.read_text()
        except Exception:
            continue
        if not text.startswith("---"):
            continue
        fm = text.split("---", 2)[1]
        name_m = re.search(r"^name:\s*\"?([^\"\n]+)\"?\s*$", fm, re.M)
        if not name_m:
            continue
        name = name_m.group(1).strip().strip('"').strip("'").lower()
        alias_m = re.search(r"^aliases:\s*\[(.*?)\]\s*$", fm, re.M)
        names = {name}
        if alias_m:
            for a in re.findall(r'"([^"]+)"', alias_m.group(1)):
                names.add(a.lower())
        aliases[name] = names
    return aliases


def question_entity_hits(question, ent_aliases):
    qlow = question.lower()
    hits = set()
    for canonical, names in ent_aliases.items():
        for n in names:
            if len(n) < 3:
                continue
            if re.search(r"\b" + re.escape(n) + r"\b", qlow):
                hits.add(canonical); break
    return hits


def retrieve(question, index, full_by_id, entity_idx, ent_aliases,
             k=10, k_seed=5, entity_df_cap=20, abstain_threshold=None):
    """
    Args:
      abstain_threshold: if top BM25 score < this, return []. Set via calibration.
    """
    # Pass 1: BM25 over all memories
    scored = []
    for doc in index["docs"]:
        s = bm25.score(question, doc, index["idf"], index["avgdl"])
        if s > 0:
            scored.append((s, doc["mem"]["id"]))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    bm25_by_id = {mid: s for s, mid in scored}

    # Abstention check on raw top-1 score
    top1_score = scored[0][0]
    if abstain_threshold is not None and top1_score < abstain_threshold:
        return []

    candidate_ids = set(bm25_by_id.keys())
    distinctive_overlap = defaultdict(int)
    in_related = set()
    q_entity_boost = set()

    # Pass 2a: graph walk from top-k_seed BM25 seeds
    seeds = [mid for _, mid in scored[:k_seed]]
    for seed_id in seeds:
        seed = full_by_id.get(seed_id)
        if not seed:
            continue
        for ent in seed["entities"]:
            df = len(entity_idx.get(ent.lower(), []))
            if df == 0 or df > entity_df_cap:
                continue
            for mid in entity_idx[ent.lower()]:
                if mid == seed_id:
                    continue
                distinctive_overlap[mid] += 1
                candidate_ids.add(mid)

    # Pass 2b: walk `related:` from EVERY top-30 candidate (not just seeds).
    # related: is author-curated -> treat as strong evidence.
    for _, mid in scored[:30]:
        m = full_by_id.get(mid)
        if not m:
            continue
        for related_mid in m["related"]:
            if related_mid in full_by_id:
                in_related.add(related_mid)
                candidate_ids.add(related_mid)

    # Pass 2c: question-mentioned entities -> boost any memory wikilinking them
    q_entities = question_entity_hits(question, ent_aliases)
    for canonical in q_entities:
        df = len(entity_idx.get(canonical, []))
        if df == 0 or df > entity_df_cap:
            continue
        for mid in entity_idx[canonical]:
            q_entity_boost.add(mid)
            candidate_ids.add(mid)

    # Pass 3: rerank. Boost magnitudes calibrated to BM25 scale (typical top score ~10-20).
    # We want graph signal to be a tiebreaker, not dominator.
    # Defaults below; can be overridden via .mvkit/retrieval_config.json.
    try:
        from memoryvault_kit.retrieval.config import get as _cfg
        BOOST_DISTINCTIVE = _cfg("graph_walk.boost_distinctive", 0.8)
        BOOST_RELATED = _cfg("graph_walk.boost_related", 3.0)
        BOOST_Q_ENTITY = _cfg("graph_walk.boost_q_entity", 1.5)
    except Exception:
        BOOST_DISTINCTIVE = 0.8     # per shared distinctive entity, capped
        BOOST_RELATED = 3.0         # author-curated edge — strong
        BOOST_Q_ENTITY = 1.5        # question literally mentions an entity in this doc

    final = []
    for mid in candidate_ids:
        m = full_by_id.get(mid)
        if not m:
            continue
        base = bm25_by_id.get(mid, 0.0)
        ovl = min(distinctive_overlap[mid], 3)
        graph_s = (BOOST_DISTINCTIVE * ovl
                   + (BOOST_RELATED if mid in in_related else 0.0)
                   + (BOOST_Q_ENTITY if mid in q_entity_boost else 0.0))
        final.append((base + graph_s, base, graph_s, m))

    final.sort(key=lambda x: -x[0])
    return [{"id": m["id"], "score": round(t, 3), "bm25": round(b, 3), "graph": round(g, 3),
             "title": m["title"]} for t, b, g, m in final[:k]]


def main():
    mems = load_full_memories()
    full_by_id = {m["id"]: m for m in mems}
    bm25_mems = bm25.load_memories()
    index = bm25.build_index(bm25_mems)
    entity_idx = build_entity_index(mems)
    ent_aliases = load_entity_aliases()
    print(f"Indexed {index['N']} memories, {len(entity_idx)} entity nodes, {len(ent_aliases)} entity files",
          file=sys.stderr)

    questions = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    threshold = None
    if "--abstain" in sys.argv:
        i = sys.argv.index("--abstain")
        threshold = float(sys.argv[i+1])
        print(f"Using abstain_threshold = {threshold}", file=sys.stderr)
    out_path = sys.argv[-1] if sys.argv[-1].endswith(".jsonl") else "/tmp/graph_04_output.jsonl"

    with open(out_path, "w") as f:
        for q in questions:
            results = retrieve(q["question"], index, full_by_id, entity_idx, ent_aliases,
                               k=10, abstain_threshold=threshold)
            f.write(json.dumps({"id": q["id"], "retrieved": [r["id"] for r in results]}) + "\n")
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
