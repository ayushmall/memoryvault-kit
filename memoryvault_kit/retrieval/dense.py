#!/usr/bin/env python3
"""
Dense embedding retriever — two models for honest comparison.

Two baselines:
  - all-MiniLM-L6-v2  (2021, ~22MB, small but well-known)
  - BAAI/bge-small-en-v1.5 (2023, ~133MB, modern, better on most benchmarks)

Both encode every memory body once at index time, then cosine-rank candidates
at query time. Index is cached to ~/MemoryVault/.dense_index_{model}.pkl
so subsequent runs are fast.

Run:
    python3 -m memoryvault_kit.retrieval.dense --eval --model minilm
    python3 -m memoryvault_kit.retrieval.dense --eval --model bge
    python3 -m memoryvault_kit.retrieval.dense --eval --model both    # compare
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path
from collections import defaultdict

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "Dense retrieval requires numpy. Install it with:\n"
        "    pip install numpy\n"
        "Or install the optional dense-retrieval extras:\n"
        "    pip install memoryvault-kit[dense]\n"
        "BM25 + graph-walk retrieval (the default kit path) does NOT need numpy."
    ) from None

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve as bm25_retrieve, parse_memory,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
MEM_DIR = VAULT / "memories" / "2026"
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"

MODELS = {
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    "bge":    "BAAI/bge-small-en-v1.5",
}


def index_path(model_key: str) -> Path:
    return VAULT / f".dense_index_{model_key}.pkl"


def _doc_text(mem: dict) -> str:
    title = mem.get("title", "") or ""
    body = mem.get("body", "") or ""
    return (title + "\n" + body).strip()[:2000]


def build_dense_index(model_key: str, force: bool = False):
    cache = index_path(model_key)
    if cache.exists() and not force:
        with open(cache, "rb") as f:
            return pickle.load(f)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODELS[model_key])
    docs = []
    for p in MEM_DIR.rglob("*.md"):
        try:
            m = parse_memory(p)
            docs.append({"id": m["id"], "text": _doc_text(m)})
        except Exception:
            continue
    texts = [d["text"] for d in docs]
    print(f"  encoding {len(texts)} memories with {MODELS[model_key]}", file=sys.stderr)
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True,
                               batch_size=32)
    out = {
        "model_name": MODELS[model_key],
        "ids": [d["id"] for d in docs],
        "embeddings": embeddings.astype(np.float32),
    }
    with open(cache, "wb") as f:
        pickle.dump(out, f)
    return out


_QUERY_MODEL = {}


def _get_query_model(model_key: str):
    if model_key not in _QUERY_MODEL:
        from sentence_transformers import SentenceTransformer
        _QUERY_MODEL[model_key] = SentenceTransformer(MODELS[model_key])
    return _QUERY_MODEL[model_key]


def retrieve_dense(question: str, index: dict, model_key: str, k: int = 10):
    model = _get_query_model(model_key)
    q_emb = model.encode([question], normalize_embeddings=True)[0]
    scores = index["embeddings"] @ q_emb  # cosine, since both normalized
    top_idx = np.argsort(-scores)[:k]
    return [{"id": index["ids"][i], "score": float(scores[i])} for i in top_idx]


def eval_model(model_key: str):
    print(f"\n--- {MODELS[model_key]} ---", file=sys.stderr)
    t0 = time.time()
    dense_idx = build_dense_index(model_key)
    print(f"  index ready ({time.time()-t0:.1f}s)", file=sys.stderr)

    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]

    cov = {k: 0 for k in (1, 3, 5, 10)}
    per_bucket = defaultdict(lambda: {"n": 0, **{k: 0 for k in (1, 3, 5, 10)}})
    latencies = []

    for q in gold_qs:
        gold = set(q["expected_memory_ids"])
        bucket = q.get("bucket", "unknown")
        t1 = time.time()
        results = retrieve_dense(q["question"], dense_idx, model_key, k=10)
        latencies.append((time.time() - t1) * 1000)
        rids = [r["id"] for r in results]
        for k in (1, 3, 5, 10):
            if any(rid in gold for rid in rids[:k]):
                cov[k] += 1
                per_bucket[bucket][k] += 1
        per_bucket[bucket]["n"] += 1

    n = len(gold_qs)
    print(f"  questions     : {n}")
    print(f"  query latency : p50={sorted(latencies)[n//2]:.0f}ms  "
          f"p95={sorted(latencies)[int(n*0.95)]:.0f}ms")
    print(f"  coverage      : @1={cov[1]/n*100:.1f}%  @3={cov[3]/n*100:.1f}%  "
          f"@5={cov[5]/n*100:.1f}%  @10={cov[10]/n*100:.1f}%")
    return cov, per_bucket, n, latencies


def main():
    args = sys.argv[1:]
    if "--eval" not in args:
        print(__doc__)
        return

    model_arg = args[args.index("--model") + 1] if "--model" in args else "both"
    targets = ["minilm", "bge"] if model_arg == "both" else [model_arg]

    # Also run BM25 baseline for direct comparison
    print("=" * 80)
    print("  DENSE RETRIEVAL EVAL (train split)")
    print("=" * 80)

    mems_list = load_memories()
    bm_idx = build_index(mems_list)
    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]

    bm_cov = {k: 0 for k in (1, 3, 5, 10)}
    for q in gold_qs:
        gold = set(q["expected_memory_ids"])
        rids = [r["id"] for r in bm25_retrieve(q["question"], bm_idx, k=10)]
        for k in (1, 3, 5, 10):
            if any(rid in gold for rid in rids[:k]):
                bm_cov[k] += 1

    n = len(gold_qs)
    print(f"\n  BM25 baseline   : @1={bm_cov[1]/n*100:.1f}%  @3={bm_cov[3]/n*100:.1f}%  "
          f"@5={bm_cov[5]/n*100:.1f}%  @10={bm_cov[10]/n*100:.1f}%")

    results = {}
    for m in targets:
        results[m] = eval_model(m)

    print()
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  {'method':<35} {'@1':>7} {'@3':>7} {'@5':>7} {'@10':>7} {'p50 ms':>8}")
    print(f"  {'BM25 (lexical)':<35} {bm_cov[1]/n*100:>6.1f}% {bm_cov[3]/n*100:>6.1f}% "
          f"{bm_cov[5]/n*100:>6.1f}% {bm_cov[10]/n*100:>6.1f}% {'<1':>8}")
    for m in targets:
        cov, _, _, lat = results[m]
        p50 = sorted(lat)[len(lat)//2]
        label = f"{m} ({MODELS[m].split('/')[-1]})"
        print(f"  {label:<35} {cov[1]/n*100:>6.1f}% {cov[3]/n*100:>6.1f}% "
              f"{cov[5]/n*100:>6.1f}% {cov[10]/n*100:>6.1f}% {p50:>7.0f}")


if __name__ == "__main__":
    main()
