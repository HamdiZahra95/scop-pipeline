"""
v07_stability_variance.py — run-to-run stability / noise floor (no LLM).

v09's CIs capture concept-sampling uncertainty within a single pair of
ontologies; they do NOT capture pipeline stochasticity (the LLM is deterministic
in config but the provider is not perfectly reproducible). This script measures
that stochasticity directly from the existing S11 exports.

Key idea: an export's filename is ``<RUN_ID>__<codehash8>.owl``. Reruns that
share a codehash used IDENTICAL stage code, so their differences are pure
run-to-run noise; different codehashes reflect code evolution. So we group by
codehash and report:
  * per code-version group (n>=2): metric spread (std, CV) + mean pairwise
    Jaccard of the discovered concept-slug set and the is-a edge set,
  * a POOLED within-code run-to-run std per metric (the noise floor),
  * "delta vs noise": whether the latest guided-vs-baseline structural deltas
    (from v02) exceed ~2x that run-to-run noise.

Usage (from pipeline_v2/):
    python analysis/v07_stability_variance.py
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
sys.path.insert(0, str(PV2 / "stages"))
from analysis import common as C
import s13_quality_gate as s13
from analysis import v02_structural_ontoqa as v2

MODES = ["baseline", "guided"]
# Exclude degenerate/partial exports (interrupted runs, smoke tests) that carry
# only a skeleton-sized class set; they are not representative pipeline outputs
# and would pollute the run-to-run noise estimate. Real runs have >1000 classes.
MIN_CLASSES = 200
KEY_METRICS = ["class_count", "concept_count", "max_depth", "branching_factor",
               "orphan_ratio", "pct_with_property", "inheritance_richness",
               "relationship_richness", "attribute_richness", "leaf_ratio"]


def parse_name(owl_path: Path):
    stem = owl_path.name[:-4] if owl_path.name.endswith(".owl") else owl_path.name
    run_id, _, code = stem.partition("__")
    return run_id, (code or "nocode")


def extract_sets(g):
    from rdflib import RDF, RDFS, OWL, URIRef
    ns = C.ONTOLOGY_NS
    classes = {str(s) for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns)}
    concept_slugs = {C.local_name(c) for c in classes
                     if C.local_name(c) not in C.SKELETON_SLUGS}
    edges = set()
    for c, p in g.subject_objects(RDFS.subClassOf):
        if (str(c) in classes and isinstance(p, URIRef) and str(p).startswith(ns)
                and C.local_name(c) not in C.SKELETON_SLUGS):
            edges.add((C.local_name(c), C.local_name(p)))
    return concept_slugs, edges


def _stats(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    n = len(vals)
    if n == 0:
        return None
    mean = sum(vals) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4),
            "min": round(min(vals), 4), "max": round(max(vals), 4),
            "cv": round(std / mean, 4) if mean else 0.0}


def _mean_pairwise_jaccard(sets):
    if len(sets) < 2:
        return None
    js = []
    for a, b in combinations(sets, 2):
        u = len(a | b)
        js.append((len(a & b) / u) if u else 1.0)
    return round(sum(js) / len(js), 4)


def _pooled_within_std(groups, key):
    """Pooled within-code-version std for a metric (the run-to-run noise floor)."""
    num, dof = 0.0, 0
    for runs in groups.values():
        vals = [r["metrics"].get(key) for r in runs
                if isinstance(r["metrics"].get(key), (int, float))]
        if len(vals) >= 2:
            m = sum(vals) / len(vals)
            num += sum((x - m) ** 2 for x in vals)
            dof += len(vals) - 1
    return round(math.sqrt(num / dof), 4) if dof > 0 else None


def scan_export(owl_path: Path):
    g = s13.load_graph(owl_path)
    metrics = dict(s13.compute_metrics(g)["metrics"])
    metrics.update(v2.ontoqa_additions(g))
    cslugs, edges = extract_sets(g)
    return metrics, cslugs, edges


def main():
    per_mode = {}
    for mode in MODES:
        p = PV2 / ("artifacts/s11_export_owl" if mode == "baseline" else "runs/guided/artifacts/s11_export_owl")
        owls = sorted(p.glob("*.owl")) if p.exists() else []
        if not owls:
            owls = C.all_owls(mode)
        groups = defaultdict(list)
        skipped = []
        for owl in owls:
            run_id, code = parse_name(owl)
            metrics, cslugs, edges = scan_export(owl)
            if metrics.get("class_count", 0) < MIN_CLASSES:
                skipped.append(owl.name)
                continue
            groups[code].append({"run_id": run_id, "run": owl.name,
                                  "metrics": metrics, "cslugs": cslugs,
                                  "edges": edges})
        latest_code = parse_name(owls[-1])[1] if owls else None
        per_mode[mode] = {"groups": groups, "skipped": skipped,
                          "latest_code": latest_code, "n_exports": len(owls)}
        print(f"[{mode}] {len(owls)} exports, {len(groups)} code version(s), "
              f"{len([g for g in groups.values() if len(g) >= 2])} with >=2 runs"
              f"{'; skipped ' + str(len(skipped)) if skipped else ''}")

    # ── assemble report ─────────────────────────────────────────────────────
    report = {"modes": MODES, "min_classes": MIN_CLASSES, "modes_detail": {}}
    for mode in MODES:
        g = per_mode[mode]["groups"]
        code_groups = {}
        for code, runs in sorted(g.items(), key=lambda kv: -len(kv[1])):
            entry = {"n_runs": len(runs),
                     "runs": [r["run_id"] for r in runs],
                     "is_current_code": code == per_mode[mode]["latest_code"]}
            if len(runs) >= 2:
                entry["concept_set_jaccard"] = _mean_pairwise_jaccard(
                    [r["cslugs"] for r in runs])
                entry["edge_set_jaccard"] = _mean_pairwise_jaccard(
                    [r["edges"] for r in runs])
                entry["metric_spread"] = {
                    k: _stats([r["metrics"].get(k) for r in runs])
                    for k in KEY_METRICS}
            code_groups[code] = entry
        report["modes_detail"][mode] = {
            "n_exports": per_mode[mode]["n_exports"],
            "latest_code": per_mode[mode]["latest_code"],
            "skipped": per_mode[mode]["skipped"],
            "code_groups": code_groups,
            "pooled_within_code_std": {k: _pooled_within_std(g, k)
                                       for k in KEY_METRICS},
        }

    # ── delta vs noise (uses v02 comparison if available) ───────────────────
    delta_vs_noise = {}
    v02_path = C.RESULTS_DIR / "v02_structural_ontoqa.json"
    if v02_path.is_file():
        comp = C.load_json(v02_path).get("comparison", {})
        base_noise = report["modes_detail"]["baseline"]["pooled_within_code_std"]
        guid_noise = report["modes_detail"]["guided"]["pooled_within_code_std"]
        for k in KEY_METRICS:
            if k not in comp:
                continue
            delta = comp[k]["delta"]
            noises = [x for x in (base_noise.get(k), guid_noise.get(k))
                      if x is not None]
            noise = max(noises) if noises else None
            if noise is None:
                exceeds = None                      # noise not estimable
            elif noise == 0:
                exceeds = abs(delta) > 0             # metric is perfectly stable
            else:
                exceeds = abs(delta) > 2 * noise
            delta_vs_noise[k] = {
                "delta_guided_minus_baseline": delta,
                "run_to_run_noise_std": noise,
                "exceeds_2sigma_noise": exceeds,
            }
    report["delta_vs_noise"] = delta_vs_noise
    report["note"] = ("Variance among reruns sharing a codehash is pure run-to-run "
                      "(provider) noise; across codehashes it also reflects code "
                      "evolution. 'delta_vs_noise' compares the latest "
                      "guided-vs-baseline structural delta (v02) to the pooled "
                      "within-code run-to-run std; exceeding ~2 sigma suggests the "
                      "delta is not merely run noise. Note baseline's current-code "
                      "group is small (n=2), so the pooled estimate borrows from "
                      "older same-code groups.")

    C.write_json(C.RESULTS_DIR / "v07_stability_variance.json", report)
    C.write_md(C.RESULTS_DIR / "v07_stability_variance.md", render_md(report))

    print("\n=== run-to-run stability (current code group) ===")
    for mode in MODES:
        md = report["modes_detail"][mode]
        cur = md["code_groups"].get(md["latest_code"], {})
        print(f"  {mode} [{md['latest_code']}] n={cur.get('n_runs')}: "
              f"concept-set Jaccard={cur.get('concept_set_jaccard')}, "
              f"edge-set Jaccard={cur.get('edge_set_jaccard')}")
    if delta_vs_noise:
        print("\n=== delta vs run-to-run noise (structural) ===")
        for k, d in delta_vs_noise.items():
            print(f"  {k:22s}: delta={d['delta_guided_minus_baseline']:+} "
                  f"noise_std={d['run_to_run_noise_std']} "
                  f"exceeds_2sigma={d['exceeds_2sigma_noise']}")
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v07_stability_variance.json'}"
          f"\n  {C.RESULTS_DIR / 'v07_stability_variance.md'}")


def render_md(report) -> str:
    L = ["# v07. Run-to-Run Stability / Noise Floor", "",
         f"- {report['note']}", ""]
    for mode in report["modes"]:
        md = report["modes_detail"][mode]
        L.append(f"## {mode} — {md['n_exports']} export(s), latest code "
                 f"`{md['latest_code']}`")
        if md["skipped"]:
            L.append(f"- skipped (<{report['min_classes']} classes): "
                     f"{len(md['skipped'])}")
        L.append("\n| code version | runs | concept-set Jaccard | edge-set Jaccard | class_count (min–max) | current |")
        L.append("|---|---|---|---|---|---|")
        for code, e in md["code_groups"].items():
            if e["n_runs"] >= 2:
                cc = e["metric_spread"]["class_count"]
                L.append(f"| `{code}` | {e['n_runs']} | {e['concept_set_jaccard']} "
                         f"| {e['edge_set_jaccard']} | {cc['min']:.0f}–{cc['max']:.0f} "
                         f"| {'yes' if e['is_current_code'] else ''} |")
            else:
                L.append(f"| `{code}` | 1 | — | — | — | "
                         f"{'yes' if e['is_current_code'] else ''} |")
        L.append("\n**Pooled within-code run-to-run std (noise floor):**")
        L.append("| metric | noise std |")
        L.append("|---|---|")
        for k in KEY_METRICS:
            v = md["pooled_within_code_std"].get(k)
            L.append(f"| {k} | {v if v is not None else '—'} |")
        L.append("")
    if report.get("delta_vs_noise"):
        L.append("## Latest guided-vs-baseline delta vs run-to-run noise")
        L.append("| metric | Δ (guided−baseline) | noise std | exceeds 2σ noise? |")
        L.append("|---|---|---|---|")
        for k, d in report["delta_vs_noise"].items():
            ex = d["exceeds_2sigma_noise"]
            flag = "—" if ex is None else ("YES" if ex else "no")
            L.append(f"| {k} | {d['delta_guided_minus_baseline']:+} | "
                     f"{d['run_to_run_noise_std']} | {flag} |")
        L.append("")
    L += ["## Reading this",
          "- **concept-set / edge-set Jaccard** across same-code reruns measures "
          "how reproducible the discovered ontology is (1.0 = identical). Lower "
          "values quantify LLM run-to-run churn.",
          "- **exceeds 2σ noise = YES** means the guided-vs-baseline structural "
          "difference is larger than run-to-run noise would explain (more likely a "
          "real effect than stochastic). This is a heuristic, not a formal test.",
          "- Baseline's current-code group is small (n=2); the pooled noise std "
          "borrows from older same-code groups, assuming comparable noise magnitude."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
