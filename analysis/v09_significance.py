"""
v09_significance.py — statistical significance for the gold-alignment deltas.

Point deltas (v03) are not evidence on their own. This puts error bars and tests
on the baseline-vs-guided differences, per gold and per match regime:

  * recall_of_gold  — PAIRED over the gold's concept universe (each gold concept
    is covered-by-baseline / covered-by-guided): McNemar exact test + paired
    bootstrap 95% CI of the difference.
  * coverage_of_generated — UNPAIRED (the two runs have different concept sets):
    per-mode bootstrap CIs + an independent-bootstrap CI of the difference.
  * taxonomic F1 — PAIRED weighted cluster bootstrap over the union of covered
    gold concepts (a pair (a,d) is weighted by draw-count w_a * w_d): per-mode
    CIs, difference CI, and a two-sided bootstrap p-value.

IMPORTANT SCOPE: these CIs quantify uncertainty from the finite concept/pair
SAMPLE within the single latest baseline/guided ontologies — i.e. "would the
difference survive a different but similar set of concepts?". They do NOT capture
LLM run-to-run variance; that is v07's job (it uses the multiple exports).

Usage (from pipeline_v2/):
    python analysis/v09_significance.py
    python analysis/v09_significance.py --boot 5000 --threshold 0.80
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import Counter
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
from analysis import common as C
from analysis import v03_gold_alignment as v3

MODES = ["baseline", "guided"]
GOLDS = ["ccs", "ito", "aio"]
SEED = 42


# ── small stats helpers ─────────────────────────────────────────────────────
def _percentile_ci(vals, alpha=0.05):
    if not vals:
        return [0.0, 0.0]
    s = sorted(vals)
    n = len(s)
    lo = s[int((alpha / 2) * n)]
    hi = s[min(int((1 - alpha / 2) * n), n - 1)]
    return [round(lo, 4), round(hi, 4)]


def _binom_two_sided(k, n, p=0.5):
    """Exact two-sided binomial p-value (for McNemar on the discordant pairs)."""
    if n == 0:
        return 1.0
    probs = [math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(n + 1)]
    obs = probs[k]
    return min(1.0, sum(pr for pr in probs if pr <= obs + 1e-12))


def mcnemar(b, u):
    b01 = sum(1 for i in range(len(b)) if b[i] == 1 and u[i] == 0)
    b10 = sum(1 for i in range(len(b)) if b[i] == 0 and u[i] == 1)
    n = b01 + b10
    return {"base_only": b01, "guided_only": b10, "discordant": n,
            "p_value": round(_binom_two_sided(min(b01, b10), n), 4)}


def _indep_diff_ci(a, b, boot, seed):
    """Independent (unpaired) bootstrap CI of mean(b) - mean(a)."""
    ra, rb = random.Random(seed), random.Random(seed + 9973)
    na, nb = len(a), len(b)
    diffs = []
    for _ in range(boot):
        sa = sum(a[ra.randrange(na)] for _ in range(na)) / na
        sb = sum(b[rb.randrange(nb)] for _ in range(nb)) / nb
        diffs.append(sb - sa)
    return _percentile_ci(diffs)


def _paired_prop(b, u, boot):
    """Paired bootstrap for two aligned binary vectors: per-vector CIs + diff CI."""
    d = [u[i] - b[i] for i in range(len(b))]
    bc = C.bootstrap_ci(b, n=boot, seed=SEED)
    uc = C.bootstrap_ci(u, n=boot, seed=SEED)
    dc = C.bootstrap_ci(d, n=boot, seed=SEED)
    return {
        "baseline": {"point": round(sum(b) / len(b), 4), "ci": [bc["lo"], bc["hi"]]},
        "guided": {"point": round(sum(u) / len(u), 4), "ci": [uc["lo"], uc["hi"]]},
        "diff": {"point": round((sum(u) - sum(b)) / len(b), 4),
                 "ci": [dc["lo"], dc["hi"]],
                 "significant": bool(dc["lo"] > 0 or dc["hi"] < 0), "paired": True},
    }


def _weighted_f1_bootstrap(PAb, GAb, PAg, GAg, U, boot, seed):
    interb, interg = PAb & GAb, PAg & GAg

    def f1_sets(PA, inter, GA):
        prec = len(inter) / len(PA) if PA else 0.0
        rec = len(inter) / len(GA) if GA else 0.0
        return (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

    pt_b, pt_g = f1_sets(PAb, interb, GAb), f1_sets(PAg, interg, GAg)
    N = len(U)
    if N == 0:
        z = {"point": 0.0, "ci": [0.0, 0.0]}
        return {"baseline": z, "guided": z,
                "diff": {"point": 0.0, "ci": [0.0, 0.0],
                         "p_two_sided": 1.0, "significant": False}}

    def wf1(PA, inter, GA, w):
        def ws(pairs):
            s = 0
            for a, d in pairs:
                wa = w.get(a, 0)
                if wa:
                    wd = w.get(d, 0)
                    if wd:
                        s += wa * wd
            return s
        tp, pa, ga = ws(inter), ws(PA), ws(GA)
        prec = tp / pa if pa else 0.0
        rec = tp / ga if ga else 0.0
        return (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

    rnd = random.Random(seed)
    fb, fg, diffs = [], [], []
    for _ in range(boot):
        w = Counter(U[rnd.randrange(N)] for _ in range(N))
        a, b = wf1(PAb, interb, GAb, w), wf1(PAg, interg, GAg, w)
        fb.append(a); fg.append(b); diffs.append(b - a)
    p = 2 * min(sum(1 for x in diffs if x <= 0),
                sum(1 for x in diffs if x >= 0)) / len(diffs)
    ci = _percentile_ci(diffs)
    return {
        "baseline": {"point": round(pt_b, 4), "ci": _percentile_ci(fb)},
        "guided": {"point": round(pt_g, 4), "ci": _percentile_ci(fg)},
        "diff": {"point": round(pt_g - pt_b, 4), "ci": ci,
                 "p_two_sided": round(min(1.0, p), 4),
                 "significant": bool(ci[0] > 0 or ci[1] < 0)},
    }


def main():
    ap = argparse.ArgumentParser(description="Significance tests for v03 deltas.")
    ap.add_argument("--boot", type=int, default=2000, help="Bootstrap resamples.")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--no-semantic", action="store_true")
    args = ap.parse_args()
    use_semantic = not args.no_semantic

    print("Loading golds + latest exports...")
    golds = {n: C.load_gold(n) for n in GOLDS}
    model = C.load_embedding_model() if use_semantic else None
    gens = {m: v3.load_generated(C.latest_owl(m)) for m in MODES}

    results = {}
    for gname in GOLDS:
        gold = golds[gname]
        per_mode = {}
        for m in MODES:
            concepts, parents, matches = v3.matches_for(
                gens[m], gold, use_semantic=use_semantic,
                threshold=args.threshold, model=model)
            per_mode[m] = (concepts, parents, matches)

        results[gname] = {}
        for regime in ("strict", "with_semantic"):
            maps = {m: v3.gen2gold_map(per_mode[m][0], per_mode[m][2], regime)
                    for m in MODES}
            sets = {m: v3.ancestor_sets(per_mode[m][0], per_mode[m][1], gold, maps[m])
                    for m in MODES}
            covered = {m: sets[m][0] for m in MODES}
            PA = {m: sets[m][1] for m in MODES}
            GA = {m: sets[m][2] for m in MODES}

            # recall_of_gold — paired over ALL gold concepts
            ids = list(gold.concepts)
            b = [1 if g in covered["baseline"] else 0 for g in ids]
            u = [1 if g in covered["guided"] else 0 for g in ids]
            recall_block = _paired_prop(b, u, args.boot)
            recall_block["mcnemar"] = mcnemar(b, u)

            # coverage_of_generated — unpaired (different concept universes)
            cb = [1 if c in maps["baseline"] else 0 for c in per_mode["baseline"][0]]
            cg = [1 if c in maps["guided"] else 0 for c in per_mode["guided"][0]]
            cbci = C.bootstrap_ci(cb, n=args.boot, seed=SEED)
            cgci = C.bootstrap_ci(cg, n=args.boot, seed=SEED)
            dci = _indep_diff_ci(cb, cg, args.boot, SEED)
            coverage_block = {
                "baseline": {"point": round(sum(cb) / len(cb), 4),
                             "ci": [cbci["lo"], cbci["hi"]]},
                "guided": {"point": round(sum(cg) / len(cg), 4),
                           "ci": [cgci["lo"], cgci["hi"]]},
                "diff": {"point": round(sum(cg) / len(cg) - sum(cb) / len(cb), 4),
                         "ci": dci, "significant": bool(dci[0] > 0 or dci[1] < 0),
                         "paired": False},
            }

            # taxonomic F1 — paired weighted cluster bootstrap over covered union
            U = sorted(covered["baseline"] | covered["guided"])
            f1_block = _weighted_f1_bootstrap(PA["baseline"], GA["baseline"],
                                              PA["guided"], GA["guided"],
                                              U, args.boot, SEED)

            results[gname][regime] = {
                "coverage_of_generated": coverage_block,
                "recall_of_gold": recall_block,
                "taxonomic_f1": f1_block,
            }
            fd = f1_block["diff"]
            print(f"  {gname}/{regime}: taxF1 Δ={fd['point']:+.3f} "
                  f"CI[{fd['ci'][0]:+.3f},{fd['ci'][1]:+.3f}] p={fd['p_two_sided']} "
                  f"sig={fd['significant']}")

    out = {
        "config": {"boot": args.boot, "threshold": args.threshold,
                   "use_semantic": use_semantic, "seed": SEED},
        "golds": {n: {"blurb": v3.GOLD_BLURB[n], "concepts": len(golds[n].concepts)}
                  for n in GOLDS},
        "results": results,
        "note": "CIs reflect sampling over the concept/pair population within the "
                "single latest baseline/guided ontologies, NOT LLM run-to-run "
                "variance (see v07). recall = paired (McNemar + paired bootstrap); "
                "coverage = unpaired (different concept sets); taxonomic F1 = paired "
                "weighted cluster bootstrap over covered gold concepts.",
    }
    C.write_json(C.RESULTS_DIR / "v09_significance.json", out)
    C.write_md(C.RESULTS_DIR / "v09_significance.md", render_md(out))
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v09_significance.json'}"
          f"\n  {C.RESULTS_DIR / 'v09_significance.md'}")


def render_md(out) -> str:
    L = ["# v09. Significance of the Gold-Alignment Deltas", "",
         f"- bootstrap resamples: {out['config']['boot']}; seed {out['config']['seed']}; "
         f"semantic threshold {out['config']['threshold']}",
         f"- {out['note']}", ""]
    for gname in GOLDS:
        L.append(f"## {gname.upper()} — {out['golds'][gname]['blurb']}")
        for regime in ("strict", "with_semantic"):
            r = out["results"][gname][regime]
            L.append(f"\n### {regime}")
            L.append("| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |")
            L.append("|---|---|---|---|---|---|")
            cov = r["coverage_of_generated"]
            rec = r["recall_of_gold"]
            f1 = r["taxonomic_f1"]
            L.append(f"| coverage | {cov['baseline']['point']} {cov['baseline']['ci']} "
                     f"| {cov['guided']['point']} {cov['guided']['ci']} "
                     f"| {cov['diff']['point']:+} {cov['diff']['ci']} "
                     f"| unpaired boot | {cov['diff']['significant']} |")
            L.append(f"| recall of gold | {rec['baseline']['point']} {rec['baseline']['ci']} "
                     f"| {rec['guided']['point']} {rec['guided']['ci']} "
                     f"| {rec['diff']['point']:+} {rec['diff']['ci']} "
                     f"| McNemar p={rec['mcnemar']['p_value']} | {rec['diff']['significant']} |")
            L.append(f"| taxonomic F1 | {f1['baseline']['point']} {f1['baseline']['ci']} "
                     f"| {f1['guided']['point']} {f1['guided']['ci']} "
                     f"| {f1['diff']['point']:+} {f1['diff']['ci']} "
                     f"| paired boot p={f1['diff']['p_two_sided']} | {f1['diff']['significant']} |")
        L.append("")
    L += ["## Reading this",
          "- Δ = guided − baseline. **significant** = the 95% CI of the difference "
          "excludes 0 (for recall, also cross-check McNemar p<0.05).",
          "- A non-significant Δ means the observed baseline/guided gap is within "
          "sampling noise over concepts — do not claim a winner on that metric.",
          "- Coverage is unpaired (the runs discover different concept sets), so it "
          "has no McNemar test; recall and taxonomic F1 are paired."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
