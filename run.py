#!/usr/bin/env python3
"""
run.py — flexible stage runner for pipeline_v2.

Lets you run one stage, a range, a subset, or the whole trunk — with a single
shared RUN_ID across the group so their outputs are grouped in the manifest.

The canonical stage order:
    01 s01_seed_concepts
    02 s02_consolidate
    03 s03_frequency_gate
    04 s04_extract_properties
    05 s05_rescue_untreated
    06 s06_clean_vocab
    07 s07_ground_to_master
    08 s08_build_taxonomy
    09 s09_qa_repair
    10 s10_formalize_properties
    11 s11_export_owl

USAGE (run from pipeline_v2/):
    python run.py --list                 # show stages and their status
    python run.py --only 04              # run just stage 04
    python run.py --only s04_extract_properties   # same, by name
    python run.py --from 04              # run 04 through the end
    python run.py --to 06                # run from the start through 06
    python run.py --from 04 --to 07      # run the inclusive range 04..07
    python run.py --steps 02,04,07       # run exactly these, in that order
    python run.py --all                  # run the whole trunk
    python run.py --from 08 --label myexp  # tag this run's RUN_ID with a label
    python run.py --from 05 --dry-run    # print what WOULD run, don't run it

Notes:
- A shared RUN_ID is generated once and passed to every stage in the group, so
  all their output files (and manifest lines) share the same timestamp prefix.
- Stops on the first stage that fails (non-zero exit).
- This runner NEVER deletes anything; outputs are versioned by common.py.
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES_DIR = ROOT / "stages"

# Canonical ordered list of stage module basenames (without .py).
STAGES = [
    "s01_seed_concepts",
    "s02_consolidate",
    "s03_frequency_gate",
    "s04_extract_properties",
    "s05_rescue_untreated",
    "s06_clean_vocab",
    "s07_ground_to_master",
    "s08_build_taxonomy",
    "s09_qa_repair",
    "s10_taxonomy_rehome",
    "s11_formalize_properties",
    "s12_export_owl",
    "s13_quality_gate",
]


def _index_of(token: str) -> int:
    """Resolve '04', '09a', 's04', or a full stage name to its list index.

    Stages are matched by their SHORT CODE (the part between the leading 's' and
    the first '_', e.g. '09a' for s09a_taxonomy_rehome), NOT by list position —
    inserting s09a means codes no longer equal indices, so a numeric token like
    '10' means "the stage whose code is 10", not "the 10th stage".
    """
    t = token.strip()
    tok = t.lower().lstrip("s")

    def _code(name: str) -> str:
        return name.split("_", 1)[0].lstrip("s").lower()   # "s09a_..." -> "09a"

    # 1) full name or exact prefix match.
    for i, name in enumerate(STAGES):
        if name == t or name.startswith(t):
            return i
    # 2) short-code match, with zero-padding so "9" matches code "09".
    for i, name in enumerate(STAGES):
        c = _code(name)
        if c == tok or (tok.isdigit() and c == tok.zfill(2)):
            return i
    raise SystemExit(f"Unknown stage: '{token}'. Use --list to see valid stages.")


def _artifacts_root(mode: str | None = None) -> Path:
    """Artifacts root for the active mode."""
    m = mode or os.getenv("SCOP_MODE", "baseline").strip().lower() or "baseline"
    return ROOT / "runs" / m / "artifacts"


def _artifact_status(stage: str, mode: str | None = None) -> str:
    d = _artifacts_root(mode=mode) / stage
    if not d.exists():
        return "—"
    files = sorted(p for p in d.iterdir() if p.is_file())
    if not files:
        subdirs = sorted(p for p in d.iterdir() if p.is_dir())
        if subdirs:
            return f"{len(subdirs)} run(s), latest: {subdirs[-1].name}"
        return "—"
    return f"{len(files)} run(s), latest: {files[-1].name}"


def cmd_list(mode: str = "baseline") -> None:
    print(f"Stage order and artifact status (mode={mode}):\n")
    for j, name in enumerate(STAGES, start=1):
        print(f"  {j:02d}  {name:<28}  {_artifact_status(name, mode=mode)}")


def select(args) -> list[str]:
    """Turn CLI args into an ordered list of stage names to run."""
    if args.all:
        return list(STAGES)
    if args.steps:
        idxs = [_index_of(tok) for tok in args.steps.split(",") if tok.strip()]
        return [STAGES[i] for i in idxs]
    if args.only:
        return [STAGES[_index_of(args.only)]]
    start = _index_of(args.frm) if args.frm else 0
    end = _index_of(args.to) if args.to else len(STAGES) - 1
    if start > end:
        raise SystemExit(f"--from ({args.frm}) is after --to ({args.to}).")
    return STAGES[start:end + 1]


def main() -> None:
    p = argparse.ArgumentParser(description="Flexible pipeline_v2 stage runner.")
    p.add_argument("--list", action="store_true", help="List stages + status and exit.")
    p.add_argument("--all", action="store_true", help="Run the whole trunk.")
    p.add_argument("--only", help="Run exactly one stage (e.g. 04 or s04_extract_properties).")
    p.add_argument("--from", dest="frm", help="Start stage (inclusive).")
    p.add_argument("--to", help="End stage (inclusive).")
    p.add_argument("--steps", help="Comma list of stages, run in the given order (e.g. 02,04,07).")
    p.add_argument("--label", help="Optional label appended to this run's RUN_ID.")
    p.add_argument("--seed-file", default="lean_checkpoint.jsonl", help="Seed filename in data/seed/ (default: lean_checkpoint.jsonl)")
    p.add_argument("--mode", choices=["baseline", "guided"], default="baseline",
                   help="Run mode: 'baseline' (default, historical layout) or "
                        "'guided' (knowledge-guided, isolated under runs/guided/).")
    p.add_argument("--dry-run", action="store_true", help="Show what would run, don't run.")
    args = p.parse_args()

    # Make the chosen mode visible to this process (for --list status) AND to the
    # stage subprocesses (via the env passed to subprocess.run below).
    os.environ["SCOP_MODE"] = args.mode

    if args.list:
        cmd_list(mode=args.mode)
        return

    to_run = select(args)
    if not to_run:
        raise SystemExit("Nothing selected. Use --all, --only, --from/--to, or --steps.")

    # One shared RUN_ID for the whole group, so their outputs line up.
    label = f"_{args.label}" if args.label else ""
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + label

    print(f"MODE   = {args.mode}")
    print(f"RUN_ID = {run_id}")
    print("Will run, in order:")
    for name in to_run:
        print(f"   -> {name}")
    if args.dry_run:
        print("\n[dry-run] Nothing executed.")
        return

    env = dict(os.environ)
    env["RUN_ID"] = run_id
    env["SCOP_MODE"] = args.mode   # stages inherit the run mode via common.py
    env["SCOP_SEED_FILE"] = args.seed_file

    for name in to_run:
        script = STAGES_DIR / f"{name}.py"
        if not script.exists():
            raise SystemExit(f"Stage script missing: {script}")
        print(f"\n{'='*60}\n▶ {name}\n{'='*60}")
        result = subprocess.run([sys.executable, str(script)], env=env, cwd=str(ROOT))
        if result.returncode != 0:
            raise SystemExit(f"✗ Stage '{name}' failed (exit {result.returncode}). Stopping.")

    print(f"\n✓ Done. Ran {len(to_run)} stage(s) under RUN_ID={run_id}.")


if __name__ == "__main__":
    main()
