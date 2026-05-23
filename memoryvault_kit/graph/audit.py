#!/usr/bin/env python3
"""
Graph quality audit — measures the entity graph independently of retrieval.

Five lenses:
  1. Coverage — what % of memories have entities, distribution of links per memory.
  2. Discrimination — how IDF-weighted is the entity vocabulary; are there too many hubs?
  3. Connectivity — is the entity-memory bipartite graph one component or fragmented?
  4. Hygiene — orphan entity files, dead wikilinks, duplicate entities, missing aliases.
  5. Earned value — does the graph improve retrieval (computed by diff'ing scored runs).

Run:
    python3 evals/graph/audit.py
    python3 evals/graph/audit.py --json   # machine-readable for dashboard
"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict, Counter
import math

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
MEM_DIR = VAULT / "memories" / "2026"
ENT_DIR = VAULT / "entities"
LOG = VAULT / "evals" / "results_log.jsonl"
OUT_JSON = VAULT / "evals" / "graph" / "audit.json"


def parse_memory(p):
    text = p.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block = parts[1]
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    entities = re.findall(r"\[\[([^\]]+)\]\]", fm.get("entities", ""))
    related = re.findall(r"mem_[A-Za-z0-9_]+", fm.get("related", ""))
    return {
        "id": fm.get("id", p.stem),
        "entities": entities,
        "related": related,
        "title": fm.get("title", ""),
        "type": fm.get("type", ""),
    }


def load_memories():
    return [m for m in (parse_memory(p) for p in sorted(MEM_DIR.glob("mem_*.md"))) if m]


def parse_entity(p):
    try:
        text = p.read_text()
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    fm_block = text.split("---", 2)[1]
    name_m = re.search(r"^name:\s*\"?([^\"\n]+)\"?\s*$", fm_block, re.M)
    if not name_m:
        return None
    name = name_m.group(1).strip().strip('"').strip("'")
    type_m = re.search(r"^type:\s*(\S+)", fm_block, re.M)
    alias_m = re.search(r"^aliases:\s*\[(.*?)\]\s*$", fm_block, re.M)
    aliases = []
    if alias_m:
        aliases = re.findall(r'"([^"]+)"', alias_m.group(1))
    return {
        "name": name,
        "type": (type_m.group(1) if type_m else "unknown").strip(),
        "aliases": aliases,
        "path": str(p),
    }


def load_entities():
    return [e for e in (parse_entity(p) for p in ENT_DIR.rglob("*.md")) if e]


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = max(0, min(len(sorted_vals) - 1, int(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def audit():
    mems = load_memories()
    ents = load_entities()
    ent_by_name_low = {e["name"].lower(): e for e in ents}

    # --- Build bipartite graph ---
    mem_ids = {m["id"] for m in mems}
    entity_to_mems = defaultdict(list)   # entity name (lowercase) -> [mem_id, ...]
    mem_to_entities = {}                  # mem_id -> [entity name, ...]
    for m in mems:
        ents_low = [e.lower() for e in m["entities"]]
        mem_to_entities[m["id"]] = ents_low
        for e in ents_low:
            entity_to_mems[e].append(m["id"])

    # ============================================================
    # 1. COVERAGE
    # ============================================================
    n_mems = len(mems)
    n_with_entities = sum(1 for m in mems if m["entities"])
    n_with_related = sum(1 for m in mems if m["related"])
    ent_counts = sorted([len(m["entities"]) for m in mems])
    rel_counts = sorted([len(m["related"]) for m in mems])

    coverage = {
        "n_memories": n_mems,
        "memories_with_entities": n_with_entities,
        "pct_memories_with_entities": round(n_with_entities / n_mems, 3),
        "memories_with_related": n_with_related,
        "pct_memories_with_related": round(n_with_related / n_mems, 3),
        "entities_per_memory": {
            "p10": percentile(ent_counts, 10), "p50": percentile(ent_counts, 50),
            "p90": percentile(ent_counts, 90), "max": max(ent_counts),
            "mean": round(sum(ent_counts) / n_mems, 2),
        },
        "related_per_memory": {
            "p50": percentile(rel_counts, 50), "p90": percentile(rel_counts, 90),
            "max": max(rel_counts), "mean": round(sum(rel_counts) / n_mems, 3),
        },
    }

    # ============================================================
    # 2. DISCRIMINATION
    # ============================================================
    df = {e: len(mids) for e, mids in entity_to_mems.items()}
    df_vals = sorted(df.values(), reverse=True)
    n_entities_used = len(df)
    # IDF approx: log(N/df). High IDF = rare = discriminating.
    idfs = [math.log(n_mems / d) for d in df_vals]
    # Useful range: df between 2 and 20 inclusive (rare enough to discriminate, common enough to bridge)
    n_useful = sum(1 for d in df_vals if 2 <= d <= 20)
    n_singleton = sum(1 for d in df_vals if d == 1)
    n_hub = sum(1 for d in df_vals if d > 20)
    # How concentrated? Top-5 entities cover what % of all entity-mentions?
    total_mentions = sum(df_vals)
    top5_share = sum(df_vals[:5]) / total_mentions if total_mentions else 0

    discrimination = {
        "n_entities_in_use": n_entities_used,
        "df_distribution": {
            "p50": percentile(sorted(df_vals), 50),
            "p90": percentile(sorted(df_vals), 90),
            "max": max(df_vals),
        },
        "useful_entities (2 <= df <= 20)": n_useful,
        "singleton_entities (df=1, dead-end)": n_singleton,
        "hub_entities (df > 20, too generic)": n_hub,
        "top5_share_of_mentions": round(top5_share, 3),
        "top5_entities": [(e, df[e]) for e in sorted(df, key=df.get, reverse=True)[:5]],
    }

    # ============================================================
    # 3. CONNECTIVITY (bipartite components)
    # ============================================================
    # Treat memories and entities as one graph; an edge connects memory<->entity
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for m in mems:
        parent.setdefault(("M", m["id"]), ("M", m["id"]))
        for e in mem_to_entities[m["id"]]:
            parent.setdefault(("E", e), ("E", e))
            union(("M", m["id"]), ("E", e))
        for r in m["related"]:
            if r in mem_ids:
                parent.setdefault(("M", r), ("M", r))
                union(("M", m["id"]), ("M", r))

    components = defaultdict(lambda: {"M": 0, "E": 0})
    for node in list(parent.keys()):
        kind = node[0]
        components[find(node)][kind] += 1
    sizes = sorted(components.values(), key=lambda c: -(c["M"] + c["E"]))

    # Memories with NO entity — they're disconnected from the entity graph.
    memories_isolated = sum(1 for m in mems if not m["entities"] and not m["related"])

    connectivity = {
        "n_components": len(sizes),
        "biggest_component": sizes[0] if sizes else None,
        "biggest_component_share_of_memories": round(sizes[0]["M"] / n_mems, 3) if sizes else None,
        "memories_with_no_edges": memories_isolated,
        "components_distribution": [
            {"size": c["M"] + c["E"], "memories": c["M"], "entities": c["E"]}
            for c in sizes[:5]
        ],
    }

    # ============================================================
    # 4. HYGIENE
    # ============================================================
    # 4a. Wikilinks pointing to entities with no entity file
    referenced_entity_names = set(entity_to_mems.keys())
    have_entity_files = set(ent_by_name_low.keys())
    # Also include aliases as recognized names
    alias_to_canonical = {}
    for e in ents:
        for a in e["aliases"]:
            alias_to_canonical[a.lower()] = e["name"].lower()
    recognized = have_entity_files | set(alias_to_canonical.keys())
    dead_wikilinks = sorted([e for e in referenced_entity_names if e not in recognized])

    # 4b. Orphan entity files (file exists, 0 memories link it)
    orphan_entity_files = sorted(
        e["name"] for e in ents
        if e["name"].lower() not in entity_to_mems
        and not any(a.lower() in entity_to_mems for a in e["aliases"])
    )

    # 4c. Entities without aliases (potential disambiguation hazards if name is short)
    no_aliases = [e["name"] for e in ents if not e["aliases"]]

    # 4d. Alias collisions — same alias on multiple entity files
    alias_collisions = defaultdict(list)
    for e in ents:
        for a in e["aliases"]:
            alias_collisions[a.lower()].append(e["name"])
    collisions = {a: names for a, names in alias_collisions.items() if len(names) > 1}

    # 4e. Reciprocity of related: edges
    related_pairs = set()
    for m in mems:
        for r in m["related"]:
            if r in mem_ids:
                related_pairs.add((m["id"], r))
    reciprocal = sum(1 for a, b in related_pairs if (b, a) in related_pairs)
    one_way = len(related_pairs) - reciprocal

    hygiene = {
        "dead_wikilinks (entity referenced but no file/alias)": {
            "count": len(dead_wikilinks),
            "examples": dead_wikilinks[:10],
        },
        "orphan_entity_files (file exists, 0 memories link it)": {
            "count": len(orphan_entity_files),
            "examples": orphan_entity_files[:10],
        },
        "entities_without_aliases": len(no_aliases),
        "alias_collisions": {
            "count": len(collisions),
            "examples": dict(list(collisions.items())[:10]),
        },
        "related_edges": {
            "total": len(related_pairs),
            "reciprocal": reciprocal,
            "one_way": one_way,
        },
    }

    # ============================================================
    # 5. EARNED VALUE — diff retriever runs from results_log
    # ============================================================
    runs = []
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            if line.strip():
                runs.append(json.loads(line))
    by_name = {r["retriever"]: r for r in runs if r.get("n_questions") == 220}
    earned = {}
    if "keyword.0.2" in by_name and "graph.0.4" in by_name:
        kw, gr = by_name["keyword.0.2"], by_name["graph.0.4"]
        earned["headline"] = {
            "keyword.0.2 R@5": kw["recall_at_5"],
            "graph.0.4 R@5": gr["recall_at_5"],
            "lift_R@5": round(gr["recall_at_5"] - kw["recall_at_5"], 4),
            "keyword.0.2 R@10": kw["recall_at_10"],
            "graph.0.4 R@10": gr["recall_at_10"],
            "lift_R@10": round(gr["recall_at_10"] - kw["recall_at_10"], 4),
        }
        # Per-bucket lift
        kb, gb = kw.get("by_bucket", {}), gr.get("by_bucket", {})
        per_bucket = {}
        for b in set(kb) | set(gb):
            ks = kb.get(b, {}).get("recall_at_5")
            gs = gb.get(b, {}).get("recall_at_5")
            if ks is not None and gs is not None:
                per_bucket[b] = {"keyword": ks, "graph": gs, "lift": round(gs - ks, 3)}
        earned["per_bucket_lift_R@5"] = dict(sorted(per_bucket.items(), key=lambda kv: -kv[1]["lift"]))

    return {
        "coverage": coverage,
        "discrimination": discrimination,
        "connectivity": connectivity,
        "hygiene": hygiene,
        "earned_value": earned,
    }


def print_report(report):
    def section(title): print(f"\n{'='*60}\n  {title}\n{'='*60}")
    def kv(k, v, indent=2):
        prefix = " " * indent
        if isinstance(v, dict):
            print(f"{prefix}{k}:")
            for k2, v2 in v.items():
                kv(k2, v2, indent + 2)
        elif isinstance(v, list):
            print(f"{prefix}{k}: {v}")
        else:
            print(f"{prefix}{k}: {v}")

    section("1. COVERAGE — is the graph populated?")
    for k, v in report["coverage"].items():
        kv(k, v)

    section("2. DISCRIMINATION — are entities distinctive?")
    for k, v in report["discrimination"].items():
        kv(k, v)

    section("3. CONNECTIVITY — is the graph traversable?")
    for k, v in report["connectivity"].items():
        kv(k, v)

    section("4. HYGIENE — orphans, dead links, missing aliases")
    for k, v in report["hygiene"].items():
        kv(k, v)

    section("5. EARNED VALUE — does the graph lift retrieval?")
    for k, v in report["earned_value"].items():
        kv(k, v)


def main():
    report = audit()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
        print(f"\n(JSON also written to {OUT_JSON})")


if __name__ == "__main__":
    main()
