#!/usr/bin/env python3
"""
Retrieval config loader — single source of truth for retrieval knobs.

Reads `<vault>/.mvkit/retrieval_config.json` if present, falls back to
defaults baked here. Modules across retrieval/ + eval/ can call
`get(<path>)` instead of carrying their own constants.

Design principle: code stays a working default. Config lets users
TUNE per-vault without forking code. New knobs land here first; the
modules they affect read via this loader.

Usage:
    from memoryvault_kit.retrieval.config import get

    k1 = get("bm25.k1")                    # 1.5 default, or whatever the user set
    boost = get("graph_walk.boost_related") # 3.0 default
    retriever = get("active_retriever.name")  # "combined_graph" default
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

DEFAULTS = {
    "active_retriever": {"name": "combined_graph"},
    "bm25": {
        "k1": 1.5, "b": 0.75,
        "importance_floor": 0.7, "importance_scale": 0.6,
    },
    "graph_walk": {
        "k_seed": 5, "entity_df_cap": 20,
        "boost_distinctive": 0.8, "boost_related": 3.0, "boost_q_entity": 1.5,
    },
    "entity_lookup": {
        "canonical_first": True, "canonical_min_importance": 0.7,
    },
    "thin_retrieval": {"score_floor": 5.0, "min_results": 3},
    "soft_coverage": {
        "score_floor": 5.0, "min_results": 2, "coverage_target": 0.6,
    },
    "tier_overrides": {
        "lean": {"k": 3, "use_reranker": False},
        "full": {"k": 5, "use_reranker": False},
    },
}


@lru_cache(maxsize=1)
def _load() -> dict:
    """Load the vault's retrieval_config.json + merge over defaults."""
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    cfg_path = vault / ".mvkit" / "retrieval_config.json"
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if cfg_path.exists():
        try:
            user_cfg = json.loads(cfg_path.read_text())
            _deep_merge(cfg, user_cfg)
        except Exception:
            pass  # malformed config → silently fall back to defaults
    return cfg


def _deep_merge(base: dict, override: dict):
    """Merge override into base in place. Skips keys starting with `_`."""
    for k, v in override.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def get(path: str, default=None):
    """Get a config value by dotted path. Falls back to default if missing.

    Examples:
        get("bm25.k1")               → 1.5
        get("graph_walk.boost_related") → 3.0
        get("active_retriever.name") → "combined_graph"
        get("does.not.exist", 42)    → 42
    """
    cfg = _load()
    node = cfg
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def reload():
    """Invalidate cache. Useful after the user edits the config mid-session."""
    _load.cache_clear()
