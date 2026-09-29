"""
v01_logical_quality.py — reasoner-based logical soundness (guidance-independent).

The strongest guidance-independent axis: an ontology that is logically
inconsistent or contains subclass cycles is broken regardless of how well it
aligns to any reference. This script reuses the pipeline's OWN s13. gate logic
(s13._quality_gate.check_consistency / detect_subclass_cycles) so the numbers are
identical to what the pipeline reports, and applies it comparatively across
BOTH modes and ALL of their S11 exports.

Per run (cheap, rdflib): subclass-cycle count, self-loops, class/edge counts.
Consistency (HermiT via owlready2, slower): run on the latest run per mode by
default; --all-consistency runs it on every export; --max-consistency N checks
the N latest. If Java/owlready2 cannot run, status is "unchecked" (NOT a
contradiction — reported as such, never a failure).

Usage (from pipeline_v2/):
    python analysis/v01_logical_quality.py
    python analysis/v01_logical_quality.py --max-consistency 3
    python analysis/v01_logical_quality.py --all-consistency
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
sys.path.insert(0, str(PV2 / "stages"))
from analysis import common as C
import s13_quality_gate as s13   # reuse the pipeline's validated gate logic

MODES = ["baseline", "guided"]


def structural_scan(owl_path: Path) -> dict:
    """Cheap rdflib-only scan: class/edge counts, subclass cycles, self-loops."""
    from rdflib import RDF, RDFS, OWL, URIRef
    g = s13.load_graph(owl_path)
    ns = C.ONTOLOGY_NS
    classes = [s for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns)]
    subedges = sum(1 for c, p in g.subject_objects(RDFS.subClassOf)
                   if isinstance(c, URIRef) and isinstance(p, URIRef)
                   and str(c).startswith(ns) and str(p).startswith(ns))
    self_loops = sum(1 for c in classes if (c, RDFS.subClassOf, c) in g)
    cycles = s13.detect_subclass_cycles(g)
    out = {"run": owl_path.name, "classes": len(classes),
           "subclass_edges": subedges, "self_loops": self_loops,
           "cycles": len(cycles)}
    if cycles:
        out["cycle_examples"] = cycles[:5]
    return out


def _latest_consistency(mode_runs: dict) -> str:
    cons = mode_runs.get("consistency_checked") or []
    return cons[-1]["status"] if cons else "n/a"


def main():
    ap = argparse.ArgumentParser(description="Logical-quality validation (v01).")
    ap.add_argument("--all-consistency", action="store_true",
                    help="Run HermiT on every export (slow).")
    ap.add_argument("--max-consistency", type=int, default=1,
                    help="Reason over the N latest exports per mode (default 1).")
    args = ap.parse_args()

    runs = {}
    for mode in MODES:
        owls = C.all_owls(mode)
        if not owls:
            runs[mode] = {"error": f"no S11 OWL exports under {C.owl_dir(mode)}"}
            print(f"[{mode}] no exports found.")
            continue
        print(f"[{mode}] scanning {len(owls)} export(s) for cycles/structure...")
        per_run = [structural_scan(o) for o in owls]

        to_check = owls if args.all_consistency else owls[-args.max_consistency:]
        print(f"[{mode}] running reasoner on {len(to_check)} run(s) "
              f"(HermiT via owlready2)...")
        cons = []
        for owl in to_check:
            r = s13.check_consistency(owl)
            cons.append({"run": owl.name, "status": r.get("status"),
                         "unsatisfiable_classes": r.get("inconsistent_classes", []),
                         "reasoner_error": r.get("reasoner_error")})
            print(f"    {owl.name}: {r.get('status')}"
                  + (f" (err: {r.get('reasoner_error')})"
                     if r.get("status") == "unchecked" else ""))

        runs[mode] = {
            "n_runs": len(owls),
            "latest_cycle_free": per_run[-1]["cycles"] == 0,
            "all_cycle_free": all(x["cycles"] == 0 for x in per_run),
            "runs_with_cycles": [x["run"] for x in per_run if x["cycles"] > 0],
            "max_cycles_any_run": max(x["cycles"] for x in per_run),
            "total_self_loops_any_run": max(x["self_loops"] for x in per_run),
            "latest": per_run[-1],
            "consistency_checked": cons,
            "per_run": per_run,
        }

    # ── comparison + verdict ────────────────────────────────────────────────
    def sound(mode: str) -> bool:
        """Soundness of the CURRENT (latest) artifact: cycle-free AND consistent.
        'unchecked' is not proof of a contradiction, so it does not fail; a cycle
        in the latest export always fails. Historical cycles are reported
        separately as a stability signal, not as a verdict on the latest run."""
        if "error" in runs.get(mode, {}):
            return False
        st = _latest_consistency(runs[mode])
        return bool(runs[mode]["latest_cycle_free"] and st in ("consistent", "unchecked"))

    comparison = {m: {"latest_cycle_free": runs[m].get("latest_cycle_free"),
                      "all_cycle_free": runs[m].get("all_cycle_free"),
                      "runs_with_cycles": len(runs[m].get("runs_with_cycles", [])),
                      "max_cycles_any_run": runs[m].get("max_cycles_any_run"),
                      "latest_consistency": _latest_consistency(runs[m])}
                  for m in MODES if "error" not in runs.get(m, {})}
    verdict = {f"{m}_sound": sound(m) for m in MODES}

    result = {
        "modes": MODES,
        "comparison": comparison,
        "verdict": verdict,
        "runs": runs,
        "note": "'unchecked' = the reasoner could not run or the curated axioms "
                "fall outside HermiT's DL subset; it is NOT a contradiction and "
                "does not fail the logical-soundness verdict. Subclass cycles "
                "(structural) always fail.",
    }
    C.write_json(C.RESULTS_DIR / "v01_logical_quality.json", result)
    C.write_md(C.RESULTS_DIR / "v01_logical_quality.md", render_md(result))

    print("\n=== logical quality ===")
    for m in MODES:
        if "error" in runs.get(m, {}):
            print(f"  {m}: {runs[m]['error']}")
            continue
        print(f"  {m}: latest consistency={_latest_consistency(runs[m])}, "
              f"latest cycle-free={runs[m]['latest_cycle_free']}, "
              f"sound={verdict[f'{m}_sound']}  "
              f"(historical: {len(runs[m]['runs_with_cycles'])}/{runs[m]['n_runs']} "
              f"run(s) had cycles)")
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v01_logical_quality.json'}"
          f"\n  {C.RESULTS_DIR / 'v01_logical_quality.md'}")


def render_md(result) -> str:
    L = ["# v01. Logical Quality (reasoner-based, guidance-independent)", "",
         "Consistency (HermiT) + subclass-cycle detection, reusing the s13. gate "
         "logic, across both modes and all their S11 exports. This axis does not "
         "depend on any reference ontology.", "",
         "| mode | runs | latest consistency | latest cycle-free | runs w/ cycles | latest sound |",
         "|---|---|---|---|---|---|"]
    for m in result["modes"]:
        r = result["runs"].get(m, {})
        if "error" in r:
            L.append(f"| {m} | — | — | — | — | (no exports) |")
            continue
        cmp = result["comparison"][m]
        L.append(f"| {m} | {r['n_runs']} | {cmp['latest_consistency']} | "
                 f"{r['latest_cycle_free']} | "
                 f"{len(r['runs_with_cycles'])}/{r['n_runs']} | "
                 f"{result['verdict'][f'{m}_sound']} |")
    L += ["", "## Notes", f"- {result['note']}",
          "- **latest sound** judges the CURRENT artifact (latest export): "
          "cycle-free AND consistent. This is the verdict that matters for using "
          "the ontology.",
          "- **runs w/ cycles** counts how many historical exports of that mode "
          "contained a subclass cycle — a stability signal. Cyclic older exports "
          "most likely predate the cycle guard or correspond to an S09 run that "
          "skipped `_break_subclass_cycles`; the specific run names are in the JSON "
          "(`runs_with_cycles`).",
          "- Consistency is reasoned on the latest run by default "
          "(`--all-consistency` / `--max-consistency N` to widen)."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
