"""
v05_edge_quality.py — sampled edge correctness via LLM-as-judge.

Structural soundness (v01/v02) and gold agreement (v03) don't tell you whether a
specific is-a placement or relation is actually TRUE. This samples edges from
each ontology (baseline, guided) and asks the guarded LLM to judge correctness
against a rubric, reporting per-mode precision with bootstrap CIs.

Judged:
  * is-a edges: for a sampled (child, parent), is child genuinely a KIND OF parent?
  * object-property edges: for a sampled (subject, property, target), is the
    relation true/plausible in an ML ontology?

Source: the latest S10 formalized DB per mode (readable concept names,
taxonomy_parent for is-a, props for object properties).

*** IMPORTANT CAVEAT ***
LLM-as-judge is a WEAK, BIASED evaluator: the judge shares a model family with
the pipeline, so it may share its blind spots; verdicts are indicative, not
ground truth. Every judgment is saved to results/v05_edge_samples.json so a human
can later re-label a subset and compute agreement (Cohen's kappa). Do not report
these numbers as validated accuracy.

Deterministic (temperature 0 + fixed seed) and cached via common.call_llm, so
re-runs are free and reproducible. Requires GOOGLE_API_KEY in .env.

Usage (from pipeline_v2/):
    python analysis/v05_edge_quality.py
    python analysis/v05_edge_quality.py --isa 80 --prop 60 --batch 10
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
from analysis import common as C
import common as PC   # pipeline common: call_llm, exceptions

STAGE = "v05_edge_quality"
MODES = ["baseline", "guided"]
META = "__meta__"

PROP_GLOSS = {
    "hasComponent": "has as a component/part", "processesData": "processes the data",
    "transforms": "transforms", "learnsFrom": "learns from", "optimizes": "optimizes",
    "producesOutput": "produces as output", "integrates": "integrates with",
    "organizes": "organizes", "selects": "selects", "modifies": "modifies",
    "evaluates": "evaluates", "hasPurpose": "has the purpose of",
    "hasCharacteristic": "has the characteristic",
}


class EdgeVerdict(BaseModel):
    index: int
    verdict: str = Field(default="unsure")   # correct | incorrect | unsure
    reason: str = Field(default="")


class EdgeVerdicts(BaseModel):
    verdicts: List[EdgeVerdict] = Field(default_factory=list)


def latest_stage_json(mode: str, stage: str):
    base = (C.ROOT / "artifacts" if mode == "baseline"
            else C.ROOT / "runs" / mode / "artifacts") / stage
    files = sorted(base.glob("*.json")) if base.exists() else []
    return files[-1] if files else None


def _is_scaffolding(name, data):
    return bool(C.slug(name) in C.SKELETON_SLUGS
                or data.get("is_skeleton") or data.get("is_intermediary"))


def sample_edges(db: dict, n_isa: int, n_prop: int, seed: int):
    isa, prop = [], []
    for name, data in db.items():
        if name == META or not isinstance(data, dict):
            continue
        if _is_scaffolding(name, data):
            continue
        p = data.get("taxonomy_parent")
        if p and p != "owl:Thing" and p != name:
            isa.append((name, p))
        for prop_name, targets in (data.get("props") or {}).items():
            for tgt in (targets or {}):
                if tgt and tgt != name:
                    prop.append((name, prop_name, tgt))
    rnd = random.Random(seed)
    rnd.shuffle(isa)
    rnd.shuffle(prop)
    return isa[:n_isa], prop[:n_prop]


def _judge(prompt: str, tag: str):
    key = f"{tag}_" + hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]
    parsed = PC.call_llm(prompt, cache_key=key, schema=EdgeVerdicts, stage=STAGE,
                         temperature=0)
    return {v.index: v for v in parsed.verdicts}


def judge_isa(pairs, batch, mode):
    results = []
    for i in range(0, len(pairs), batch):
        chunk = pairs[i:i + batch]
        lines = "\n".join(f'{j}. Is "{c}" genuinely a KIND OF (subclass of) "{p}"?'
                          for j, (c, p) in enumerate(chunk))
        prompt = (
            "You are an expert machine-learning ontologist judging is-a "
            "(subclass) placements. For each item decide whether the CHILD is "
            "genuinely a KIND OF the PARENT (true subsumption) — NOT merely "
            "part-of, used-by, related-to, or an instance-of. Be strict.\n\n"
            f"{lines}\n\n"
            'Return strictly JSON: {"verdicts": [{"index": 0, '
            '"verdict": "correct|incorrect|unsure", "reason": "<=12 words"}]}')
        try:
            vmap = _judge(prompt, f"isa_{mode}")
        except (PC.MalformedResponse, RuntimeError):
            vmap = {}
        for j, (c, p) in enumerate(chunk):
            v = vmap.get(j)
            results.append({"mode": mode, "kind": "is_a", "child": c, "parent": p,
                            "verdict": (v.verdict if v else "unsure").lower(),
                            "reason": (v.reason if v else "")[:120]})
    return results


def judge_prop(triples, batch, mode):
    results = []
    for i in range(0, len(triples), batch):
        chunk = triples[i:i + batch]
        lines = "\n".join(
            f'{j}. "{s}" {PROP_GLOSS.get(pr, pr)} "{t}".'
            for j, (s, pr, t) in enumerate(chunk))
        prompt = (
            "You are an expert machine-learning ontologist judging whether "
            "relational statements are TRUE/plausible in an ML domain ontology. "
            "For each statement decide correct/incorrect/unsure.\n\n"
            f"{lines}\n\n"
            'Return strictly JSON: {"verdicts": [{"index": 0, '
            '"verdict": "correct|incorrect|unsure", "reason": "<=12 words"}]}')
        try:
            vmap = _judge(prompt, f"prop_{mode}")
        except (PC.MalformedResponse, RuntimeError):
            vmap = {}
        for j, (s, pr, t) in enumerate(chunk):
            v = vmap.get(j)
            results.append({"mode": mode, "kind": "property", "subject": s,
                            "property": pr, "target": t,
                            "verdict": (v.verdict if v else "unsure").lower(),
                            "reason": (v.reason if v else "")[:120]})
    return results


def summarize(judgments, mode, kind):
    rows = [r for r in judgments if r["mode"] == mode and r["kind"] == kind]
    correct = sum(1 for r in rows if r["verdict"] == "correct")
    incorrect = sum(1 for r in rows if r["verdict"] == "incorrect")
    unsure = sum(1 for r in rows if r["verdict"] not in ("correct", "incorrect"))
    decided = correct + incorrect
    indicators = ([1] * correct) + ([0] * incorrect)   # precision excludes unsure
    ci = C.bootstrap_ci(indicators) if indicators else {"point": None, "lo": None, "hi": None, "n": 0}
    return {
        "sampled": len(rows), "correct": correct, "incorrect": incorrect,
        "unsure": unsure,
        "precision_excl_unsure": round(correct / decided, 4) if decided else None,
        "precision_ci": [ci["lo"], ci["hi"]],
        "correct_rate_incl_unsure": round(correct / len(rows), 4) if rows else None,
        "unsure_rate": round(unsure / len(rows), 4) if rows else None,
    }


def main():
    ap = argparse.ArgumentParser(description="LLM-as-judge edge quality (v05).")
    ap.add_argument("--isa", type=int, default=60, help="is-a edges sampled per mode.")
    ap.add_argument("--prop", type=int, default=40, help="property edges sampled per mode.")
    ap.add_argument("--batch", type=int, default=10, help="edges per LLM call.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    all_judgments = []
    try:
        for mode in MODES:
            s10 = latest_stage_json(mode, "s10_formalize_properties")
            if not s10:
                print(f"[{mode}] no S10 artifact; skipping.")
                continue
            db = C.load_json(s10)
            isa, prop = sample_edges(db, args.isa, args.prop, args.seed)
            print(f"[{mode}] {s10.name}: judging {len(isa)} is-a + {len(prop)} "
                  f"property edges (LLM judge, cached)...")
            all_judgments += judge_isa(isa, args.batch, mode)
            all_judgments += judge_prop(prop, args.batch, mode)
    except PC.QuotaExhausted as e:
        print(f"[v05] daily LLM quota exhausted mid-run: {e}\n"
              f"Partial judgments cached; re-run to resume. Writing partial results.")

    summary = {mode: {"is_a": summarize(all_judgments, mode, "is_a"),
                      "property": summarize(all_judgments, mode, "property")}
               for mode in MODES}
    comparison = {}
    for kind in ("is_a", "property"):
        b = summary["baseline"][kind].get("precision_excl_unsure")
        g = summary["guided"][kind].get("precision_excl_unsure")
        comparison[kind] = {"baseline": b, "guided": g,
                            "delta": (round(g - b, 4) if (b is not None and g is not None) else None)}

    result = {
        "config": {"isa": args.isa, "prop": args.prop, "batch": args.batch,
                   "seed": args.seed, "model": getattr(PC, "GEMINI_MODEL", "?"),
                   "judge": "LLM-as-judge (single model, no human validation)"},
        "summary": summary,
        "comparison": comparison,
        "caveat": "LLM-as-judge only: the judge shares a model family with the "
                  "pipeline and may share its biases; verdicts are INDICATIVE, not "
                  "validated accuracy. Judgments saved to v05_edge_samples.json for "
                  "a future human kappa subset. Precision excludes 'unsure'.",
    }
    C.write_json(C.RESULTS_DIR / "v05_edge_quality.json", result)
    C.write_json(C.RESULTS_DIR / "v05_edge_samples.json", all_judgments)
    C.write_md(C.RESULTS_DIR / "v05_edge_quality.md", render_md(result))

    print("\n=== judged precision (excl. unsure) ===")
    for mode in MODES:
        for kind in ("is_a", "property"):
            s = summary[mode][kind]
            print(f"  {mode:8s} {kind:8s}: prec={s['precision_excl_unsure']} "
                  f"(correct {s['correct']}/{s['correct'] + s['incorrect']}, "
                  f"unsure {s['unsure']}/{s['sampled']})")
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v05_edge_quality.json'}"
          f"\n  {C.RESULTS_DIR / 'v05_edge_quality.md'}"
          f"\n  {C.RESULTS_DIR / 'v05_edge_samples.json'}")


def render_md(result) -> str:
    L = ["# v05. Edge Quality (LLM-as-judge)", "",
         f"- judge model: `{result['config']['model']}`; "
         f"is-a sampled: {result['config']['isa']}/mode; "
         f"property sampled: {result['config']['prop']}/mode; seed {result['config']['seed']}",
         "", f"> **Caveat.** {result['caveat']}", "",
         "## Judged precision (excludes 'unsure')",
         "| mode | edge type | precision | 95% CI | correct/decided | unsure |",
         "|---|---|---|---|---|---|"]
    for mode in result["summary"]:
        for kind in ("is_a", "property"):
            s = result["summary"][mode][kind]
            L.append(f"| {mode} | {kind} | {s['precision_excl_unsure']} | "
                     f"{s['precision_ci']} | "
                     f"{s['correct']}/{s['correct'] + s['incorrect']} | "
                     f"{s['unsure']}/{s['sampled']} |")
    L += ["", "## Baseline vs guided (unpaired; different sampled edges)",
          "| edge type | baseline | guided | delta |", "|---|---|---|---|"]
    for kind in ("is_a", "property"):
        c = result["comparison"][kind]
        L.append(f"| {kind} | {c['baseline']} | {c['guided']} | "
                 f"{c['delta'] if c['delta'] is not None else '—'} |")
    L += ["", "## Reading this",
          "- **precision excludes 'unsure'** = correct / (correct + incorrect); "
          "the unsure column shows how often the judge abstained.",
          "- Baseline vs guided is **unpaired** (different sampled edges from "
          "different ontologies); treat deltas as indicative, and cross-check with "
          "the held-out taxonomic agreement in v03/v09.",
          "- These are LLM verdicts, not ground truth. `v05_edge_samples.json` "
          "holds every judgment for a human re-labeling / Cohen's-kappa pass."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
