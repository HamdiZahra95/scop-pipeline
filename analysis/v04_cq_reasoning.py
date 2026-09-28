"""
v04_cq_reasoning.py — competency questions as REAL queries, comparatively.

The hasty analysis scripts scored CQs by substring presence. This runs the 12
competency questions as actual graph/reasoner queries (reusing the pipeline's own
S12 evaluate_cqs logic) on BOTH the baseline and guided ontologies, and adds two
things S12's single-run gate does not:

  1. ASSERTED vs MATERIALIZED. Some CQs need inference (CQ7 transitive
     hasComponent; CQ8/CQ9 inverse properties). S12 queries the asserted graph
     only. Here we also build a materialized graph that makes the axioms declared
     in common.PROPERTY_AXIOMS explicit — inverse edges, symmetric edges, and the
     transitive closure of transitive properties — deterministically in rdflib
     (a faithful, fast proxy for a DL reasoner's property-value inference). A CQ
     that is a gap on the asserted graph but answerable after materialization is
     answerable BY ENTAILMENT: the axioms support it even if the edge is not
     asserted.
  2. STABILITY. The asserted CQ evaluation is run across every healthy export of
     each mode, reporting the per-CQ answerable-rate (does answerability flip
     run-to-run?).

CQ12 (consistency) uses HermiT via S12.check_consistency on the latest export of
each mode; it is not part of the stability sweep (reasoner cost).

Usage (from pipeline_v2/):
    python analysis/v04_cq_reasoning.py
    python analysis/v04_cq_reasoning.py --no-stability
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
sys.path.insert(0, str(PV2 / "stages"))
from analysis import common as C
import s12_quality_gate as s12
import common as PC

from rdflib import Graph, URIRef, RDF, OWL

MODES = ["baseline", "guided"]
MIN_CLASSES = 200
_STUB_CONS = {"status": "unchecked", "inconsistent_classes": [],
              "reasoner_error": "skipped (stability sweep, no reasoner)"}


def _n_classes(g) -> int:
    ns = PC.ONTOLOGY_NS
    return sum(1 for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns))


def materialize(g):
    """Make the PROPERTY_AXIOMS-declared semantics explicit (inverse, symmetric,
    transitive closure) in a copy of the graph. Deterministic rdflib entailment,
    not a DL reasoner, but faithful to the axiom box S11 emits."""
    ns = PC.ONTOLOGY_NS
    mg = Graph()
    for t in g:
        mg.add(t)
    added = 0
    for prop, spec in PC.PROPERTY_AXIOMS.items():
        p = URIRef(ns + prop)
        chars = spec.get("characteristics", []) or []
        inv = spec.get("inverse")
        if inv:
            ip = URIRef(ns + inv)
            for s, o in list(g.subject_objects(p)):
                if (o, ip, s) not in mg:
                    mg.add((o, ip, s)); added += 1
        if "Symmetric" in chars:
            for s, o in list(g.subject_objects(p)):
                if (o, p, s) not in mg:
                    mg.add((o, p, s)); added += 1
    for prop, spec in PC.PROPERTY_AXIOMS.items():
        if "Transitive" in (spec.get("characteristics", []) or []):
            p = URIRef(ns + prop)
            adj = defaultdict(set)
            for s, o in mg.subject_objects(p):
                adj[s].add(o)
            for s in list(adj):
                seen, stack = set(adj[s]), list(adj[s])
                while stack:
                    x = stack.pop()
                    for y in adj.get(x, ()):
                        if y != s and y not in seen:
                            seen.add(y); stack.append(y)
                for y in seen:
                    if (s, p, y) not in mg:
                        mg.add((s, p, y)); added += 1
    return mg, added


def main():
    ap = argparse.ArgumentParser(description="Comparative CQ reasoning (v04).")
    ap.add_argument("--no-stability", action="store_true")
    args = ap.parse_args()

    per_mode = {}
    for mode in MODES:
        owl = C.latest_owl(mode)
        print(f"[{mode}] {owl.name}: querying 12 CQs (asserted + materialized) "
              f"+ reasoner consistency...")
        g = s12.load_graph(owl)
        cons = s12.check_consistency(owl)
        asserted = {c["id"]: c for c in s12.evaluate_cqs(g, cons)}
        mg, added = materialize(g)
        materialized = {c["id"]: c for c in s12.evaluate_cqs(mg, cons)}
        per_mode[mode] = {"owl": owl.name, "consistency": cons["status"],
                          "materialized_edges_added": added,
                          "asserted": asserted, "materialized": materialized}
        na = sum(1 for c in asserted.values() if c["status"] == "answerable")
        nm = sum(1 for c in materialized.values() if c["status"] == "answerable")
        print(f"    answerable: asserted {na}/12, materialized {nm}/12 "
              f"(+{added} entailed edges)")

    # ── per-CQ comparative table ────────────────────────────────────────────
    ids = [f"CQ{i}" for i in range(1, 13)]
    cq_meta = {c["id"]: {"question": c["question"], "category": c["category"]}
               for c in per_mode["baseline"]["asserted"].values()}
    comparison = []
    for cid in ids:
        row = {"id": cid, "question": cq_meta.get(cid, {}).get("question"),
               "category": cq_meta.get(cid, {}).get("category")}
        for mode in MODES:
            row[f"{mode}_asserted"] = per_mode[mode]["asserted"][cid]["status"]
            row[f"{mode}_materialized"] = per_mode[mode]["materialized"][cid]["status"]
        # answerable-by-entailment only (gap asserted -> answerable materialized)
        row["gained_by_inference"] = {
            m: (per_mode[m]["asserted"][cid]["status"] != "answerable"
                and per_mode[m]["materialized"][cid]["status"] == "answerable")
            for m in MODES}
        comparison.append(row)

    rollup = {m: {
        "asserted_answerable": sum(1 for c in per_mode[m]["asserted"].values()
                                   if c["status"] == "answerable"),
        "materialized_answerable": sum(1 for c in per_mode[m]["materialized"].values()
                                       if c["status"] == "answerable"),
        "consistency": per_mode[m]["consistency"],
    } for m in MODES}

    # ── stability across healthy runs (asserted, no reasoner) ───────────────
    stability = {}
    if not args.no_stability:
        for mode in MODES:
            per_cq = defaultdict(list)
            n_used = 0
            for owl in C.all_owls(mode):
                g = s12.load_graph(owl)
                if _n_classes(g) < MIN_CLASSES:
                    continue
                n_used += 1
                for c in s12.evaluate_cqs(g, _STUB_CONS):
                    per_cq[c["id"]].append(1 if c["status"] == "answerable" else 0)
            stability[mode] = {
                "runs_used": n_used,
                "answerable_rate": {cid: round(sum(v) / len(v), 3)
                                    for cid, v in sorted(per_cq.items())},
            }
            print(f"[{mode}] stability over {n_used} healthy run(s) computed.")

    result = {
        "modes": MODES,
        "rollup": rollup,
        "comparison": comparison,
        "stability": stability,
        "note": "Real graph/reasoner CQ queries (S12 logic), not substring matching. "
                "'materialized' makes PROPERTY_AXIOMS inverse/symmetric/transitive "
                "semantics explicit in rdflib (faithful proxy for DL property "
                "inference); a CQ gained_by_inference is answerable by entailment. "
                "CQ12 consistency uses HermiT on the latest export; stability sweep "
                "is asserted-only (CQ12 uninformative there).",
    }
    C.write_json(C.RESULTS_DIR / "v04_cq_reasoning.json", result)
    C.write_md(C.RESULTS_DIR / "v04_cq_reasoning.md", render_md(result))
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v04_cq_reasoning.json'}"
          f"\n  {C.RESULTS_DIR / 'v04_cq_reasoning.md'}")


def render_md(result) -> str:
    L = ["# v04. Competency Questions as Real Reasoner Queries", "",
         f"- {result['note']}", "",
         "## Rollup", "| mode | asserted answerable | materialized answerable | consistency |",
         "|---|---|---|---|"]
    for m in result["modes"]:
        r = result["rollup"][m]
        L.append(f"| {m} | {r['asserted_answerable']}/12 | "
                 f"{r['materialized_answerable']}/12 | {r['consistency']} |")
    L += ["", "## Per-CQ (asserted → materialized)",
          "| CQ | category | baseline | guided |", "|---|---|---|---|"]
    for row in result["comparison"]:
        def cell(m):
            a = row[f"{m}_asserted"]
            mm = row[f"{m}_materialized"]
            arrow = f"{a} → {mm}" if a != mm else a
            star = " *(by inference)*" if row["gained_by_inference"][m] else ""
            return arrow + star
        L.append(f"| {row['id']} {row['question']} | {row['category']} "
                 f"| {cell('baseline')} | {cell('guided')} |")
    if result["stability"]:
        L += ["", "## Answerability stability across healthy runs (asserted)",
              "| CQ | " + " | ".join(f"{m} rate (n={result['stability'][m]['runs_used']})"
                                     for m in result["modes"]) + " |",
              "|---|" + "|".join(["---"] * len(result["modes"])) + "|"]
        ids = [f"CQ{i}" for i in range(1, 13)]
        for cid in ids:
            cells = [str(result["stability"][m]["answerable_rate"].get(cid, "—"))
                     for m in result["modes"]]
            L.append(f"| {cid} | " + " | ".join(cells) + " |")
    L += ["", "## Reading this",
          "- **asserted → materialized**: status on the asserted graph, then after "
          "making declared inverse/transitive/symmetric semantics explicit. "
          "*(by inference)* = the CQ is answerable only via entailment.",
          "- **stability rate** = fraction of healthy runs where the CQ was "
          "answerable (1.0 = always). CQ12 is ~0 here because the sweep skips the "
          "reasoner; see the rollup for the real CQ12 verdict.",
          "- A gap is a coverage gap (empty result), not a logical failure "
          "(only CQ12 inconsistency is gate-blocking)."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
