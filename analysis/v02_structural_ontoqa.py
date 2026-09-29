"""
v02_structural_ontoqa.py — structural / OntoQA metrics, baseline vs guided.

Structural quality is a guidance-independent axis: is the generated hierarchy
well-shaped (deep enough but not degenerate, connected, richly related, not
tangled)? Reuses s13's compute_metrics for the shared block (class/concept
counts, depth, branching, parent/property coverage, orphans) and adds OntoQA
(Tartir et al.) schema metrics:

  * inheritance_richness   = subClassOf edges / classes  (avg is-a links/class)
  * relationship_richness  = non-isa edges / (isa + non-isa)  (schema is not a bare tree)
  * attribute_richness     = annotations / class  (labels+comments+defs+altLabels)
  * tangledness            = fraction of classes with >1 superclass
  * leaf_ratio             = leaf classes / classes

Primary comparison = latest baseline vs latest guided. A distribution block
(mean + bootstrap 95% CI + min/max across all exports of each mode) is included
as a variance/stability sanity check (note: spread also reflects code-version
differences across historical exports, not pure LLM noise).

Usage (from pipeline_v2/):
    python analysis/v02_structural_ontoqa.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
sys.path.insert(0, str(PV2 / "stages"))
from analysis import common as C
import s13_quality_gate as s13
import common as PC   # pipeline constants (CORE_PROPERTIES, ONTOLOGY_NS)

MODES = ["baseline", "guided"]


def ontoqa_additions(g) -> dict:
    from rdflib import RDF, RDFS, OWL, URIRef
    from rdflib.namespace import SKOS
    ns = PC.ONTOLOGY_NS
    classes = {s for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns)}
    parents, children = defaultdict(set), defaultdict(set)
    for c, p in g.subject_objects(RDFS.subClassOf):
        if c in classes and isinstance(p, URIRef) and str(p).startswith(ns):
            parents[c].add(p)
            children[p].add(c)
    n = len(classes) or 1
    subedges = sum(len(v) for v in parents.values())
    multi = [c for c in classes if len(parents.get(c, ())) > 1]
    leaves = [c for c in classes if not children.get(c)]

    prop_edges = 0
    for prop in PC.CORE_PROPERTIES:
        puri = URIRef(ns + prop)
        prop_edges += sum(1 for s, _ in g.subject_objects(puri)
                          if isinstance(s, URIRef))
    denom = (prop_edges + subedges) or 1

    ann = 0
    for c in classes:
        for pred in (RDFS.label, RDFS.comment, SKOS.definition, SKOS.altLabel):
            ann += sum(1 for _ in g.objects(c, pred))

    return {
        "inheritance_richness": round(subedges / n, 4),
        "relationship_richness": round(prop_edges / denom, 4),
        "attribute_richness": round(ann / n, 4),
        "tangledness": round(len(multi) / n, 4),
        "multi_parent_classes": len(multi),
        "leaf_ratio": round(len(leaves) / n, 4),
        "leaf_count": len(leaves),
        "property_edges": prop_edges,
    }


def scan(owl_path: Path) -> dict:
    g = s13.load_graph(owl_path)
    m = dict(s13.compute_metrics(g)["metrics"])   # shared s13 metrics
    m.update(ontoqa_additions(g))                 # OntoQA additions
    return m


def main():
    runs, dist = {}, {}
    for mode in MODES:
        owls = C.all_owls(mode)
        if not owls:
            runs[mode] = {"error": f"no S11 OWL exports under {C.owl_dir(mode)}"}
            print(f"[{mode}] no exports found.")
            continue
        print(f"[{mode}] scanning {len(owls)} export(s)...")
        per = []
        for o in owls:
            m = scan(o)
            m["run"] = o.name
            per.append(m)
        runs[mode] = {"n_runs": len(owls), "latest": per[-1], "per_run": per}
        num_keys = [k for k, v in per[-1].items() if isinstance(v, (int, float))]
        dist[mode] = {
            k: {**C.bootstrap_ci([p[k] for p in per]),
                "min": min(p[k] for p in per), "max": max(p[k] for p in per)}
            for k in num_keys
        }

    ok = [m for m in MODES if "error" not in runs.get(m, {})]
    comparison = {}
    if "baseline" in ok and "guided" in ok:
        bl, gl = runs["baseline"]["latest"], runs["guided"]["latest"]
        for k in bl:
            if isinstance(bl[k], (int, float)) and isinstance(gl.get(k), (int, float)):
                comparison[k] = {"baseline": bl[k], "guided": gl[k],
                                 "delta": round(gl[k] - bl[k], 4)}

    result = {
        "modes": MODES,
        "primary": {m: runs[m]["latest"] for m in ok},
        "comparison": comparison,
        "distribution_across_runs": dist,
        "runs_meta": {m: {"n_runs": runs[m]["n_runs"]} for m in ok},
        "note": "Primary = latest baseline vs latest guided. Distribution spread "
                "across historical exports also reflects code-version changes, "
                "not only LLM run-to-run noise (see v07 for a cleaner stability study).",
    }
    C.write_json(C.RESULTS_DIR / "v02_structural_ontoqa.json", result)
    C.write_md(C.RESULTS_DIR / "v02_structural_ontoqa.md", render_md(result))

    print("\n=== structural comparison (latest baseline vs guided) ===")
    for k in ("class_count", "concept_count", "max_depth", "branching_factor",
              "orphan_ratio", "inheritance_richness", "relationship_richness",
              "attribute_richness", "tangledness", "leaf_ratio"):
        if k in comparison:
            c = comparison[k]
            print(f"  {k:22s}: baseline={c['baseline']:<9} guided={c['guided']:<9} "
                  f"delta={c['delta']:+}")
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v02_structural_ontoqa.json'}"
          f"\n  {C.RESULTS_DIR / 'v02_structural_ontoqa.md'}")


def render_md(result) -> str:
    HEAD = ["class_count", "concept_count", "skeleton_count", "max_depth",
            "branching_factor", "pct_with_parent", "pct_with_property",
            "orphan_ratio", "inheritance_richness", "relationship_richness",
            "attribute_richness", "tangledness", "leaf_ratio"]
    L = ["# v02. Structural / OntoQA Quality", "",
         "Shared s13 metrics + OntoQA schema metrics. Primary comparison is the "
         "latest baseline vs the latest guided export.", "",
         "| metric | baseline | guided | delta |", "|---|---|---|---|"]
    comp = result["comparison"]
    for k in HEAD:
        if k in comp:
            c = comp[k]
            L.append(f"| {k} | {c['baseline']} | {c['guided']} | {c['delta']:+} |")
    L += ["", "## Variance across all exports (bootstrap 95% CI)",
          "| mode | metric | mean | 95% CI | min | max |", "|---|---|---|---|---|---|"]
    for m in result.get("runs_meta", {}):
        for k in ("max_depth", "branching_factor", "orphan_ratio",
                  "inheritance_richness", "relationship_richness", "tangledness"):
            d = result["distribution_across_runs"].get(m, {}).get(k)
            if d:
                L.append(f"| {m} | {k} | {d['point']} | "
                         f"[{d['lo']}, {d['hi']}] (n={d['n']}) | {d['min']} | {d['max']} |")
    L += ["", "## Notes", f"- {result['note']}",
          "- OntoQA: inheritance_richness = is-a edges / classes; "
          "relationship_richness = non-isa / (isa+non-isa); "
          "attribute_richness = annotations / class; tangledness = fraction with "
          ">1 superclass; leaf_ratio = leaves / classes."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
