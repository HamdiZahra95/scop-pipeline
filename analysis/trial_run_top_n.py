#!/usr/bin/env python3
"""
trial_run.py — High-speed demonstration runner on top frequent concepts.

Executes Baseline and/or Guided pipelines across stages S04 through S13 in an
isolated sandbox (runs/trial_<N>/), measuring exact stage-by-stage wall-clock timing
and formal ontology metrics (HermiT consistency, CQ pass rate, tree depth).
Never touches production thesis artifacts or master code.
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

# Stage modules (canonical S04-S13)
import s04_extract_properties as S04
import s05_rescue_untreated as S05
import s06_clean_vocab as S06
import s07_ground_to_master as S07
import s08_build_taxonomy as S08
import s09_qa_repair as S09
import s10_taxonomy_rehome as S10
import s11_formalize_properties as S11
import s12_export_owl as S12
import s13_quality_gate as S13


def get_trial_dir(top_n: int) -> Path:
    return ROOT / "runs" / f"trial_{top_n}"


def setup_trial_inputs(target_artifacts_dir: Path, target_caches_dir: Path, top_n: int = 10) -> tuple[Path, list[str]]:
    """Symlink S02, seed caches, and extract top N concepts into a trial S03 frequency bin."""
    # 1. Symlink S02 so S07 can read the master concepts list
    s02_source_dir = ROOT / "artifacts" / "s02_consolidate"
    s02_target_dir = target_artifacts_dir / "s02_consolidate"
    s02_target_dir.mkdir(parents=True, exist_ok=True)

    s02_files = sorted(s02_source_dir.glob("*.json")) if s02_source_dir.exists() else []
    if not s02_files:
        raise FileNotFoundError(
            f"No consolidated concepts found in {s02_source_dir}. "
            "Please ensure S02 artifact is available before running trial."
        )

    for s02_file in s02_files:
        symlink = s02_target_dir / s02_file.name
        if not symlink.exists():
            symlink.symlink_to(s02_file)

    # 2. Start with a completely clean, empty cache directory (no pre-existing cache)
    # The trial run executes live from zero against the active LLM provider.
    pass

    # 3. Extract top N concepts from S02
    latest_s02 = s02_files[-1]
    with open(latest_s02, "r", encoding="utf-8") as f:
        s02_data = json.load(f)

    top_concepts = sorted(s02_data, key=lambda x: x.get("corpus_frequency", 0), reverse=True)[:top_n]
    concept_names = [x["target_concept"] for x in top_concepts]

    # 4. Create isolated S03 bin
    s03_dir = target_artifacts_dir / "s03_frequency_gate" / f"trial_top{top_n}__mock0000"
    s03_dir.mkdir(parents=True, exist_ok=True)
    bin_file = s03_dir / "freq_gt_10.jsonl"
    C.save_jsonl(bin_file, top_concepts)
    return s03_dir, concept_names


def run_pipeline_for_mode(mode: str, top_n: int = 10) -> tuple[dict[str, float], dict]:
    print("\n" + "=" * 78)
    print(f"  STARTING TRIAL RUN ({top_n} CONCEPTS) — MODE: {mode.upper()}")
    print("=" * 78)

    trial_dir = get_trial_dir(top_n)
    mode_root = trial_dir / mode
    artifacts_dir = mode_root / "artifacts"
    caches_dir = mode_root / "caches"
    reports_dir = mode_root / "reports"
    logs_dir = mode_root / "logs"

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    caches_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Set generous 200s timeout to handle LLM load spikes
    os.environ["S08_TIMEOUT"] = "200"
    os.environ["S09_TIMEOUT"] = "200"
    os.environ["LLM_REQUEST_TIMEOUT"] = "200"
    os.environ["ORPHAN_BATCH"] = "10"
    S08.S08_TIMEOUT = 200.0
    S09.S09_TIMEOUT = 200.0
    S09.ORPHAN_BATCH = 10

    # Ensure stale failed S09 batch caches are cleared for clean execution
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

    # Clear in-memory LLM cache dict in common.py so it reloads from trial cache
    C._LLM_CACHES.clear()

    # Set distinct RUN_ID
    run_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    C.RUN_ID = f"{run_timestamp}_trial_{mode}"
    os.environ["RUN_ID"] = C.RUN_ID

    # Setup top N concepts in S03 bin + symlink S02 + seed caches
    setup_trial_inputs(artifacts_dir, caches_dir, top_n=top_n)

    stage_timings: dict[str, float] = {}

    def timed_run(stage_name: str, fn, *args, **kwargs):
        t0 = time.monotonic()
        print(f"\n▶ [{stage_name}] Starting...", flush=True)
        result = fn(*args, **kwargs)
        elapsed = time.monotonic() - t0
        stage_timings[stage_name] = elapsed
        print(f"✔ [{stage_name}] Finished in {elapsed:.2f}s", flush=True)
        return result

    # Execute pipeline stages S04 through S13
    timed_run("S04_extract_properties", S04.run)
    timed_run("S05_rescue_untreated", S05.run)
    timed_run("S06_clean_vocab", S06.run)
    timed_run("S07_ground_to_master", S07.run)
    timed_run("S08_build_taxonomy", S08.run)
    timed_run("S09_qa_repair", S09.run)
    timed_run("S10_taxonomy_rehome", S10.run)
    timed_run("S11_formalize_properties", S11.run)
    owl_path = timed_run("S12_export_owl", S12.run)
    report_path = timed_run("S13_quality_gate", S13.run, owl_path=owl_path, include_tiered_benchmark=False)

    summary_metrics = {}
    if report_path and Path(report_path).is_file():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                rep = json.load(f)
            cqs = rep.get("competency_questions", {})
            cq_list = cqs.get("results", []) if isinstance(cqs, dict) else rep.get("competency_questions", [])
            total_cq = cqs.get("total", len(cq_list)) if isinstance(cqs, dict) else len(cq_list)
            ans_cq = cqs.get("answerable", sum(1 for q in cq_list if q.get("status") == "answerable")) if isinstance(cqs, dict) else sum(1 for q in cq_list if q.get("status") == "answerable")

            summary_metrics = {
                "owl_classes": rep.get("metrics", {}).get("class_count") or rep.get("metrics", {}).get("classes_total"),
                "tree_depth": rep.get("metrics", {}).get("max_depth") or rep.get("metrics", {}).get("max_taxonomy_depth"),
                "consistency": rep.get("consistency", {}).get("status"),
                "cq_pass_rate": f"{ans_cq}/{total_cq}"
            }
        except Exception as e:
            print(f"Warning: could not parse summary metrics from {report_path}: {e}")

    return stage_timings, summary_metrics


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run SCOP Top-N Concept Trial Demonstration")
    parser.add_argument("--top", "-n", type=int, default=10,
                        help="Number of top frequent concepts to evaluate (default: 10)")
    parser.add_argument("--mode", choices=["all", "baseline", "guided"], default="all",
                        help="Run mode: 'baseline', 'guided', or 'all' (default: 'all')")
    args = parser.parse_args()

    trial_dir = get_trial_dir(args.top)
    total_start = time.monotonic()
    print(f"🚀 Initializing SCOP Top-{args.top} Trial Demonstration (Mode: {args.mode.upper()})...")

    # Clean previous trial artifacts and caches so every run starts 100% fresh from zero
    modes_to_clean = ["baseline", "guided"] if args.mode == "all" else [args.mode]
    for m in modes_to_clean:
        for sub in ("artifacts", "reports", "logs", "caches"):
            d = trial_dir / m / sub
            if d.exists():
                shutil.rmtree(d)
    trial_dir.mkdir(parents=True, exist_ok=True)

    base_timings, base_metrics = {}, {}
    guided_timings, guided_metrics = {}, {}
    base_total, guided_total = 0.0, 0.0

    # 1. Run Baseline
    if args.mode in ("all", "baseline"):
        t_base = time.monotonic()
        base_timings, base_metrics = run_pipeline_for_mode("baseline", top_n=args.top)
        base_total = time.monotonic() - t_base

    # 2. Run Guided
    if args.mode in ("all", "guided"):
        t_guided = time.monotonic()
        guided_timings, guided_metrics = run_pipeline_for_mode("guided", top_n=args.top)
        guided_total = time.monotonic() - t_guided

    total_wall = time.monotonic() - total_start

    # Summary table
    print("\n" + "=" * 80)
    print(f"        SCOP TOP-{args.top} CONCEPT TRIAL RUN TIMING & METRICS REPORT")
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
    print(f"Generated Ontology Metrics (Top {args.top} Concepts):")
    if base_metrics:
        print(f"  [Baseline] OWL Classes: {base_metrics.get('owl_classes')}, Depth: {base_metrics.get('tree_depth')}, Consistency: {base_metrics.get('consistency')}, CQs: {base_metrics.get('cq_pass_rate')}")
    if guided_metrics:
        print(f"  [Guided]   OWL Classes: {guided_metrics.get('owl_classes')}, Depth: {guided_metrics.get('tree_depth')}, Consistency: {guided_metrics.get('consistency')}, CQs: {guided_metrics.get('cq_pass_rate')}")
    print("-" * 80)
    print(f"Overall Wall-Clock: {total_wall:.2f} seconds ({total_wall/60:.2f} minutes)")
    if args.mode in ("all", "baseline"):
        print(f"  • Baseline OWL: {trial_dir / 'baseline' / 'artifacts' / 's12_export_owl'}")
    if args.mode in ("all", "guided"):
        print(f"  • Guided OWL  : {trial_dir / 'guided'   / 'artifacts' / 's12_export_owl'}")
    print("=" * 80)


if __name__ == "__main__":
    main()
