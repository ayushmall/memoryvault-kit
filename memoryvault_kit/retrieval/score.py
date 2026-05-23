#!/usr/bin/env python3
"""
Generic scorer: takes any retriever's output JSONL ({"id": "qNNN", "retrieved": [...]})
and scores against questions.jsonl. Computes Recall@K, Precision@K, MRR, Entity-recall@5,
and per-bucket breakdowns. Abstention is scored by len(retrieved) == 0.

Usage:
    python3 score.py <retriever_output.jsonl> <retriever_name>
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
QUESTIONS = VAULT / "evals" / "retrieval" / "questions.jsonl"
MEM_DIR = VAULT / "memories" / "2026"


def load_memory_meta():
    """Map memory_id -> {entities, tags} for entity-recall scoring."""
    meta = {}
    import re
    for p in MEM_DIR.glob("mem_*.md"):
        text = p.read_text()
        if not text.startswith("---"):
            continue
        fm = text.split("---", 2)[1]
        mid_m = re.search(r"^id:\s*(\S+)", fm, re.M)
        if not mid_m:
            continue
        mid = mid_m.group(1).strip().strip('"').strip("'")
        ents = re.findall(r"\[\[([^\]]+)\]\]", fm)
        tags = re.findall(r"[a-z0-9\-_]+", (re.search(r"^tags:\s*(.*)", fm, re.M).group(1).lower() if re.search(r"^tags:", fm, re.M) else ""))
        meta[mid] = {"entities": [f"[[{e}]]" for e in ents], "tags": tags}
    return meta


def score(output_path: str, retriever_name: str):
    questions = {q["id"]: q for q in (json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip())}
    outputs = {}
    for line in Path(output_path).read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        outputs[o["id"]] = o.get("retrieved", [])

    mem_meta = load_memory_meta()

    agg = defaultdict(list)
    bucket_agg = defaultdict(lambda: defaultdict(list))
    abstain_correct = []
    per_q = []
    missing = []

    for qid, q in questions.items():
        if qid not in outputs:
            missing.append(qid)
            continue
        ret = outputs[qid]
        gold_ids = set(q.get("expected_memory_ids") or [])
        gold_ents = set(q.get("expected_entities") or [])
        gold_tags = set(q.get("expected_tags") or [])
        bucket = q.get("bucket", "unknown")
        expect_abstain = q.get("expect_abstain", False)
        rec_q = {"id": qid, "bucket": bucket, "retrieved": ret[:10], "gold_ids": list(gold_ids)}

        if expect_abstain:
            ok = len(ret) == 0
            abstain_correct.append(1.0 if ok else 0.0)
            rec_q["abstain_correct"] = ok
            per_q.append(rec_q)
            continue

        for k in (5, 10):
            topk = ret[:k]
            if gold_ids:
                hits = len(gold_ids & set(topk))
                r_v = hits / len(gold_ids)
                p_v = hits / k
                agg[f"recall_at_{k}"].append(r_v)
                agg[f"precision_at_{k}"].append(p_v)
                bucket_agg[bucket][f"recall_at_{k}"].append(r_v)
                rec_q[f"recall_at_{k}"] = r_v

        if gold_ids:
            mrr = 0.0
            for i, mid in enumerate(ret, 1):
                if mid in gold_ids:
                    mrr = 1.0 / i
                    break
            agg["mrr"].append(mrr)
            bucket_agg[bucket]["mrr"].append(mrr)
            rec_q["mrr"] = mrr

        # entity recall@5 — LOOSE: any top-5 memory's entities count
        ents_in_top5 = set()
        tags_in_top5 = set()
        for mid in ret[:5]:
            if mid in mem_meta:
                ents_in_top5.update(mem_meta[mid]["entities"])
                tags_in_top5.update(mem_meta[mid]["tags"])
        if gold_ents:
            er = len(gold_ents & ents_in_top5) / len(gold_ents)
            agg["entity_recall_at_5_loose"].append(er)
            bucket_agg[bucket]["entity_recall_at_5_loose"].append(er)
            rec_q["entity_recall_at_5_loose"] = er
        if gold_tags:
            tr = len(gold_tags & tags_in_top5) / len(gold_tags)
            agg["tag_recall_at_5"].append(tr)
            rec_q["tag_recall_at_5"] = tr

        # entity recall@5 — STRICT: only entities from retrieved memories that are also in gold_ids
        # This isolates "did we get the right memory" from "did we spray the topic"
        if gold_ents and gold_ids:
            correct_retrieved = [mid for mid in ret[:5] if mid in gold_ids]
            ents_strict = set()
            for mid in correct_retrieved:
                if mid in mem_meta:
                    ents_strict.update(mem_meta[mid]["entities"])
            er_strict = len(gold_ents & ents_strict) / len(gold_ents)
            agg["entity_recall_at_5_strict"].append(er_strict)
            bucket_agg[bucket]["entity_recall_at_5_strict"].append(er_strict)
            rec_q["entity_recall_at_5_strict"] = er_strict

        per_q.append(rec_q)

    avg = lambda v: sum(v) / len(v) if v else None
    summary = {k: avg(v) for k, v in agg.items()}
    summary["abstain_correct_rate"] = avg(abstain_correct)
    summary["n_questions"] = len(questions)
    summary["n_scored"] = len(per_q)
    summary["n_missing"] = len(missing)
    summary["retriever"] = retriever_name

    by_bucket = {}
    for b, m in bucket_agg.items():
        by_bucket[b] = {k: round(avg(v), 3) for k, v in m.items()}
        by_bucket[b]["n"] = max(len(v) for v in m.values())
    summary["by_bucket"] = by_bucket

    return {"summary": summary, "per_question": per_q, "missing": missing}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: score.py <retriever_output.jsonl> <retriever_name>", file=sys.stderr)
        sys.exit(1)
    result = score(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2, default=str))
