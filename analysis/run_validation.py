#!/usr/bin/env python3
"""
run_validation.py — run the validation suite (v01–v09) in order.

This is the rigorous, non-circular replacement for the old run_all.py. It runs
each validation script as a subprocess (like run.py does for stages), times it,
and prints a summary. Every script writes its own JSON + Markdown under
analysis/results/.

Suite order (dependencies respected — v07 reads v02's output):
    v01 logical      reasoner consistency + subclass cycles          [needs Java]
    v02 structural   OntoQA / graph metrics + variance
    v03 gold         held-out AIO/ITO/CCS taxonomic alignment        [embeddings]
    v04 cq           12 CQs as real reasoner queries                 [needs Java]
    v06 grounding    attestation / demotion / hallucination / annots
    v07 stability    run-to-run noise floor (reads v02 result)
    v09 significance CIs + paired tests on the gold-alignment deltas  [embeddings]
    v05 edge quality sampled is-a/property correctness (LLM judge)    [needs LLM]

Run with the project venv so rdflib / owlready2 / sentence-transformers resolve:
    ./.venv/bin/python analysis/run_validation.py                # full suite
    ./.venv/bin/python analysis/run_validation.py --no-llm       # skip v05 (offline)
    ./.venv/bin/python analysis/run_validation.py --only v03,v09 # subset
    ./.venv/bin/python analysis/run_validation.py --list
    ./.venv/bin/python analysis/run_validation.py --stop-on-error
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ANALYSIS = Path(__file__).resolve().parent
ROOT = ANALYSIS.parent            # pipeline_v2/
RESULTS = ANALYSIS / "results"

# tag, script, flags: llm (network), reasoner (Java/owlready2), embeddings, note
SUITE = [
    ("v01", "v01_logical_quality.py",      {"reasoner": True},
     "reasoner consistency + subclass cycles across all runs"),
    ("v02", "v02_structural_ontoqa.py",    {},
     "OntoQA / structural metrics + across-run variance"),
    ("v03", "v03_gold_alignment.py",       {"embeddings": True},
     "held-out AIO/ITO/CCS taxonomic precision/recall/F1"),
    ("v04", "v04_cq_reasoning.py",         {"reasoner": True},
     "12 CQs as real queries (asserted + materialized)"),
    ("v06", "v06_grounding_provenance.py", {},
     "corpus attestation / demotion / hallucination / annotation coverage"),
    ("v07", "v07_stability_variance.py",   {"depends": "v02"},
     "run-to-run noise floor (reads v02 result)"),
    ("v09", "v09_significance.py",         {"embeddings": True},
     "bootstrap CIs + paired tests on the v03 deltas"),
    ("v05", "v05_edge_quality.py",         {"llm": True},
     "sampled is-a/property correctness (LLM-as-judge)"),
]


def cmd_list() -> None:
    print("Validation suite (in run order):\n")
    for tag, script, flags, note in SUITE:
        marks = []
        if flags.get("llm"):
            marks.append("LLM")
        if flags.get("reasoner"):
            marks.append("Java")
        if flags.get("embeddings"):
            marks.append("emb")
        tail = f"  [{', '.join(marks)}]" if marks else ""
        print(f"  {tag}  {script:<28}  {note}{tail}")


def select(args) -> list:
    suite = SUITE
    if args.only:
        want = {t.strip().lower() for t in args.only.split(",") if t.strip()}
        suite = [row for row in suite if row[0] in want]
        missing = want - {row[0] for row in suite}
        if missing:
            raise SystemExit(f"Unknown tag(s): {sorted(missing)}. Use --list.")
    if args.no_llm:
        suite = [row for row in suite if not row[2].get("llm")]
    return suite


def main() -> None:
    p = argparse.ArgumentParser(description="Run the pipeline validation suite.")
    p.add_argument("--list", action="store_true", help="List the suite and exit.")
    p.add_argument("--only", help="Comma list of tags to run (e.g. v03,v09).")
    p.add_argument("--no-llm", action="store_true",
                   help="Skip LLM-dependent scripts (v05) for a fully offline run.")
    p.add_argument("--stop-on-error", action="store_true",
                   help="Stop at the first failing script (default: run all).")
    args = p.parse_args()

    if args.list:
        cmd_list()
        return

    suite = select(args)
    if not suite:
        raise SystemExit("Nothing selected. Use --list to see tags.")

    print(f"Running {len(suite)} validation script(s) with {sys.executable}\n"
          f"(cwd={ROOT})\n")
    results = []
    for tag, script, flags, note in suite:
        path = ANALYSIS / script
        if not path.is_file():
            print(f"✗ {tag}: script missing ({path})")
            results.append((tag, "missing", 0.0))
            if args.stop_on_error:
                break
            continue
        print(f"\n{'=' * 70}\n▶ {tag}  {script}  —  {note}\n{'=' * 70}", flush=True)
        t0 = time.time()
        # Inherit stdio so live progress (esp. v05 API calls) is visible.
        rc = subprocess.run([sys.executable, str(path)], cwd=str(ROOT)).returncode
        dt = time.time() - t0
        status = "ok" if rc == 0 else f"FAIL(rc={rc})"
        results.append((tag, status, dt))
        print(f"— {tag} {status} in {dt:.1f}s")
        if rc != 0 and args.stop_on_error:
            print(f"Stopping: {tag} failed and --stop-on-error is set.")
            break

    # ── summary ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 70}\nVALIDATION SUMMARY\n{'=' * 70}")
    for tag, status, dt in results:
        print(f"  {tag:<5} {status:<12} {dt:6.1f}s")
    ok = sum(1 for _, s, _ in results if s == "ok")
    print(f"\n  {ok}/{len(results)} script(s) ok.")

    if RESULTS.exists():
        mds = sorted(RESULTS.glob("v0*.md"))
        if mds:
            print("\n  Reports (analysis/results/):")
            for m in mds:
                print(f"    - {m.name}")

    # Non-zero exit if anything failed, so CI / callers can detect it.
    if any(s not in ("ok",) for _, s, _ in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
