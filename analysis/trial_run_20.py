#!/usr/bin/env python3
"""
trial_run_20.py — High-speed demonstration runner on the 20 most frequent concepts.

Executes both Baseline and Guided pipelines across stages S04 through S12 in an
isolated sandbox (runs/trial_20/), measuring exact stage-by-stage wall-clock timing.
Never touches production thesis artifacts or code.
"""

import os
import sys
import time
import json
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))

import common as C

# Stage modules
import s04_extract_properties as S04
import s05_rescue_untreated as S05
import s06_clean_vocab as S06
import s07_ground_to_master as S07
import s08_build_taxonomy as S08
import s09_qa_repair as S09
import s09a_taxonomy_rehome as S09a
import s10_formalize_properties as S10
import s11_export_owl as S11
import s12_quality_gate as S12

TRIAL_DIR = ROOT / "runs" / "trial_20"

def setup_trial_inputs(target_artifacts_dir: Path, target_caches_dir: Path) -> tuple[Path, list[str]]:
    """Symlink S02, seed caches, and extract top 20 concepts into a trial S03 frequency bin."""
    # 1. Symlink S02 so S07 can read the master concepts list
    s02_source_dir = ROOT / "artifacts" / "s02_consolidate"
    s02_target_dir = target_artifacts_dir / "s02_consolidate"
    s02_target_dir.mkdir(parents=True, exist_ok=True)
    for s02_file in s02_source_dir.glob("*.json"):
        symlink = s02_target_dir / s02_file.name
        if not symlink.exists():
            symlink.symlink_to(s02_file)

    # 2. Seed S05 and S09a cache from repository caches
    for stage_name in ["s05_rescue_untreated", "s09a_taxonomy_rehome"]:
        dest_stage = target_caches_dir / stage_name
        dest_stage.mkdir(parents=True, exist_ok=True)
        for base_dir in [ROOT / "caches" / stage_name, ROOT / "runs" / "guided" / "caches" / stage_name]:
            if base_dir.exists():
                for cfile in base_dir.glob("*.json"):
                    if not (dest_stage / cfile.name).exists():
                        shutil.copy2(cfile, dest_stage / cfile.name)

    # 3. Extract top 20 concepts from S02
    latest_s02 = sorted(s02_source_dir.glob("*.json"))[-1]
    with open(latest_s02, "r", encoding="utf-8") as f:
        s02_data = json.load(f)

    top20 = sorted(s02_data, key=lambda x: x["corpus_frequency"], reverse=True)[:20]
    concept_names = [x["target_concept"] for x in top20]

    # 4. Create isolated S03 bin
    s03_dir = target_artifacts_dir / "s03_frequency_gate" / "trial_top20__mock0000"
    s03_dir.mkdir(parents=True, exist_ok=True)
    bin_file = s03_dir / "freq_gt_10.jsonl"
    C.save_jsonl(bin_file, top20)
    return s03_dir, concept_names

def run_pipeline_for_mode(mode: str) -> tuple[dict[str, float], dict]:
    print("\n" + "=" * 75)
    print(f"  STARTING TRIAL RUN (20 CONCEPTS) — MODE: {mode.upper()}")
    print("=" * 75)

    mode_root = TRIAL_DIR / mode
    artifacts_dir = mode_root / "artifacts"
    caches_dir = mode_root / "caches"
    reports_dir = mode_root / "reports"
    logs_dir = mode_root / "logs"

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    caches_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Set generous 200s timeout as requested to handle LLM load spikes
    os.environ["S08_TIMEOUT"] = "200"
    os.environ["S09_TIMEOUT"] = "200"
    os.environ["LLM_REQUEST_TIMEOUT"] = "200"
    os.environ["ORPHAN_BATCH"] = "10"
    S08.S08_TIMEOUT = 200.0
    S09.S09_TIMEOUT = 200.0
    S09.ORPHAN_BATCH = 10

    # Ensure stale failed S09 batch caches are cleared for clean 10-item execution
    s09_cache = caches_dir / "s09_qa_repair"
    if s09_cache.exists():
        shutil.rmtree(s09_cache)

    # Dynamically point common.py to this trial sandbox
    C.ARTIFACTS = artifacts_dir
    C.CACHES = caches_dir
    C.REPORTS = reports_dir
    C.LOGS = logs_dir
    C.SCOP_MODE = mode
    os.environ["SCOP_MODE"] = mode

    # Clear in-memory LLM caches cache dict in common.py so it reloads from trial cache
    C._LLM_CACHES.clear()

    # Set distinct RUN_ID
    run_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    C.RUN_ID = f"{run_timestamp}_trial_{mode}"
    os.environ["RUN_ID"] = C.RUN_ID

    # Setup top 20 concepts in S03 bin + symlink S02 + seed caches
    setup_trial_inputs(artifacts_dir, caches_dir)

    stage_timings: dict[str, float] = {}

    def timed_run(stage_name: str, fn, *args, **kwargs):
        t0 = time.monotonic()
        print(f"\n▶ [{stage_name}] Starting...", flush=True)
        result = fn(*args, **kwargs)
        elapsed = time.monotonic() - t0
        stage_timings[stage_name] = elapsed
        print(f"✔ [{stage_name}] Finished in {elapsed:.2f}s", flush=True)
        return result

    # Execute pipeline stages S04 through S12
    timed_run("S04_mine_relations", S04.run)
    timed_run("S05_rescue_untreated", S05.run)
    timed_run("S06_clean_vocab", S06.run)
    timed_run("S07_ground_targets", S07.run)
    timed_run("S08_build_taxonomy", S08.run)
    timed_run("S09_qa_repair", S09.run)
    timed_run("S09a_rehome_taxonomy", S09a.run)
    timed_run("S10_formalize_props", S10.run)
    owl_path = timed_run("S11_export_owl", S11.run)
    report_path = timed_run("S12_reasoner_gate", S12.run, owl_path=owl_path, include_tiered_benchmark=False)

    summary_metrics = {}
    if report_path and Path(report_path).is_file():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                rep = json.load(f)
            summary_metrics = {
                "owl_classes": rep.get("metrics", {}).get("classes_total"),
                "tree_depth": rep.get("metrics", {}).get("max_taxonomy_depth"),
                "consistency": rep.get("consistency", {}).get("status"),
                "cq_pass_rate": f"{sum(1 for q in rep.get('competency_questions', []) if q.get('status') == 'answerable')}/{len(rep.get('competency_questions', []))}"
            }
        except Exception:
            pass

    return stage_timings, summary_metrics

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run SCOP 20-concept demonstration")
    parser.add_argument("--mode", choices=["all", "baseline", "guided"], default="all",
                        help="Run mode: 'baseline', 'guided', or 'all' (default)")
    args = parser.parse_args()

    total_start = time.monotonic()
    print(f"🚀 Initializing SCOP 20-Concept Demonstration (Mode: {args.mode.upper()})...")

    # Clean previous trial artifacts while preserving caches for instant resume
    modes_to_clean = ["baseline", "guided"] if args.mode == "all" else [args.mode]
    for m in modes_to_clean:
        for sub in ("artifacts", "reports", "logs"):
            d = TRIAL_DIR / m / sub
            if d.exists():
                shutil.rmtree(d)
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)

    base_timings, base_metrics = {}, {}
    guided_timings, guided_metrics = {}, {}
    base_total, guided_total = 0.0, 0.0

    # 1. Run Baseline
    if args.mode in ("all", "baseline"):
        t_base = time.monotonic()
        base_timings, base_metrics = run_pipeline_for_mode("baseline")
        base_total = time.monotonic() - t_base

    # 2. Run Guided
    if args.mode in ("all", "guided"):
        t_guided = time.monotonic()
        guided_timings, guided_metrics = run_pipeline_for_mode("guided")
        guided_total = time.monotonic() - t_guided

    total_wall = time.monotonic() - total_start

    # Summary table
    print("\n" + "=" * 80)
    print("        SCOP 20-CONCEPT TRIAL RUN TIMING & METRICS REPORT")
    print("=" * 80)
    print(f"{'Pipeline Stage':<28} | {'Baseline Time':<18} | {'Guided Time':<18}")
    print("-" * 80)
    all_stages = list(base_timings.keys()) or list(guided_timings.keys())
    for stg in all_stages:
        b_sec = f"{base_timings.get(stg, 0.0):.2f}s" if base_timings else "—"
        g_sec = f"{guided_timings.get(stg, 0.0):.2f}s" if guided_timings else "—"
        print(f"{stg:<28} | {b_sec:<18} | {g_sec:<18}")
    print("-" * 80)
    print(f"{'TOTAL PIPELINE EXECUTION':<28} | {base_total:.2f}s ({base_total/60:.2f}m)      | {guided_total:.2f}s ({guided_total/60:.2f}m)")
    print("=" * 80)
    print("Generated Ontology Metrics (Top 20 Concepts):")
    if base_metrics:
        print(f"  [Baseline] OWL Classes: {base_metrics.get('owl_classes')}, Depth: {base_metrics.get('tree_depth')}, Consistency: {base_metrics.get('consistency')}, CQs: {base_metrics.get('cq_pass_rate')}")
    if guided_metrics:
        print(f"  [Guided]   OWL Classes: {guided_metrics.get('owl_classes')}, Depth: {guided_metrics.get('tree_depth')}, Consistency: {guided_metrics.get('consistency')}, CQs: {guided_metrics.get('cq_pass_rate')}")
    print("-" * 80)
    print(f"Overall Wall-Clock: {total_wall:.2f} seconds ({total_wall/60:.2f} minutes)")
    if args.mode in ("all", "baseline"):
        print(f"  • Baseline OWL: {TRIAL_DIR / 'baseline' / 'artifacts' / 's11_export_owl'}")
    if args.mode in ("all", "guided"):
        print(f"  • Guided OWL  : {TRIAL_DIR / 'guided'   / 'artifacts' / 's11_export_owl'}")
    print("=" * 80)

if __name__ == "__main__":
    main()
