"""
s01_seed_concepts.py — Stage 1: copy + validate the frozen seed.

Input : seed/lean_checkpoint.jsonl        (schema: {id, concept_name, definition})
Output: artifacts/s01_seed_concepts/<RUN_ID>__<codehash>.jsonl   (never overwritten)
LLM   : no

Purpose: give the pipeline a real, hashable, immutable starting artifact while
keeping seed/ pristine. See REBUILD_PLAN.md §3 (S01).
"""

import os
import sys
from pathlib import Path

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s01_seed_concepts"
REQUIRED_KEYS = {"id", "concept_name", "definition"}


def run():
    seed_filename = os.getenv("SCOP_SEED_FILE", "lean_checkpoint.jsonl").strip() or "lean_checkpoint.jsonl"
    seed_file = C.SEED / seed_filename
    if not seed_file.exists():
        raise FileNotFoundError(
            f"Seed not found at {seed_file}. Copy it into seed/ first "
            f"(see REBUILD_PLAN.md §2)."
        )

    rows = C.load_jsonl(seed_file)

    # Validate schema; count malformed rows (kept out of the output).
    valid, malformed = [], 0
    for r in rows:
        if isinstance(r, dict) and REQUIRED_KEYS.issubset(r.keys()):
            valid.append(r)
        else:
            malformed += 1

    out_path = C.output_path(STAGE, __file__, ext="jsonl")
    C.save_jsonl(out_path, valid)

    C.write_manifest(
        STAGE, __file__, in_path=seed_file, out_path=out_path,
        counts={
            "records_in": len(rows),
            "records_valid": len(valid),
            "records_malformed": malformed,
            "unique_concept_names": len({r["concept_name"] for r in valid}),
        },
    )
    print(f"[{STAGE}] wrote {len(valid)} validated records -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
