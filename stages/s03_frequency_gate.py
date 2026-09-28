"""
s03_frequency_gate.py — Stage 3: bin concepts by corpus frequency (Port).

Input : latest artifacts/s02_consolidate/*.json   (list of consolidated concepts,
        each carrying `target_concept` + `corpus_frequency`)
Output: artifacts/s03_frequency_gate/<RUN_ID>__<codehash>/freq_*.jsonl
        (a versioned DIRECTORY of per-bin JSONL files; never overwritten)
LLM   : no

Port (from scripts/shared/split_paylad.py, preserved byte-identical under
legacy): sort every concept into one of seven frequency bins by
`corpus_frequency` and write one JSONL file per non-empty bin. The analytical
binning logic is unchanged; only the I/O and the gate source are rewired.

Changes from the original (allowed port categories only):
  * I/O — read the latest S02 artifact via `require_latest` instead of a
    hardcoded `gemma_payload.json`; write bins under a versioned directory via
    `common.output_dir(...)` so every run's bins are retained on disk (R21.3)
    and never overwrite a prior run's (R2.3, R1.1).
  * Shared constant — the gate boundary is sourced from `common.FREQ_GATE_DEFAULT`
    (the single documented, tunable knob, R21.1) rather than the scattered
    literal `10`. The `6-10` bin is `6..FREQ_GATE_DEFAULT` and the top bin is
    `> FREQ_GATE_DEFAULT`.
  * Manifest — one line per run reporting per-bin counts (R4.1, R4.2).
  * Exposes `run() -> Path` returning the versioned bin directory (R13.3).

Bins (R21, tasks 3): 1, 2, 3, 4, 5, 6-10, gt_10 (by `corpus_frequency`).
Contract: S04 consumes the `freq_gt_10` bin (the trusted, high-frequency core).
"""

import sys
from collections import defaultdict
from pathlib import Path

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s03_frequency_gate"

# The seven bin names, in canonical order (matches the original script).
BIN_ORDER = [
    "freq_1", "freq_2", "freq_3", "freq_4", "freq_5",
    "freq_6_to_10", "freq_gt_10", "unknown",
]


def get_bin_name(freq: int) -> str:
    """Sort a corpus frequency into its bin (Port).

    The 1..5 bins are exact; the `6_to_10` bin runs 6..FREQ_GATE_DEFAULT and the
    `gt_10` bin is everything above FREQ_GATE_DEFAULT. Both upper bins derive
    their boundary from the single documented gate constant
    (`common.FREQ_GATE_DEFAULT`, R21.1) rather than a scattered literal.
    """
    gate = C.FREQ_GATE_DEFAULT
    if freq == 1:
        return "freq_1"
    if freq == 2:
        return "freq_2"
    if freq == 3:
        return "freq_3"
    if freq == 4:
        return "freq_4"
    if freq == 5:
        return "freq_5"
    if 6 <= freq <= gate:
        return "freq_6_to_10"
    if freq > gate:
        return "freq_gt_10"
    return "unknown"


def run() -> Path:
    print(f"🚀 S03: binning concepts by corpus_frequency "
          f"(gate = FREQ_GATE_DEFAULT = {C.FREQ_GATE_DEFAULT})...")

    # ── 1. LOAD latest S02 artifact (never a hardcoded filename) ──────────
    in_path = C.require_latest("s02_consolidate", ext="json")
    print(f"📂 Loading {in_path} ...")
    data = C.load_json(in_path)
    print(f"✅ Loaded {len(data):,} consolidated concepts.")

    # ── 2. SORT into frequency bins (Port — logic unchanged in baseline) ──
    # Knowledge-guided extension (mode == "guided", R-KG): a concept that is
    # attested by the guiding reference ontology is promoted into the trusted
    # `freq_gt_10` bin even if its corpus frequency is below the gate. This
    # recovers reference concepts the corpus mentions rarely (the analysis found
    # ~66 such cases, e.g. XGBoost@9, DBSCAN@4). It is a strict SUPERSET of the
    # baseline gate: no concept is ever removed, only additionally promoted. In
    # baseline mode this block is inert, so the baseline output is unchanged.
    guided = getattr(C, "SCOP_MODE", "baseline") == "guided"
    K = None
    if guided:
        import knowledge as K  # loaded only in guided mode
        print("🧭 Guided mode: reference-attested low-frequency concepts will be "
              "promoted into freq_gt_10.")

    print(f"🔄 Sorting {len(data):,} concepts into frequency bins...")
    bins = defaultdict(list)
    recovered = 0
    for item in data:
        freq = item.get("corpus_frequency", 0)
        bin_name = get_bin_name(freq)
        if guided and bin_name != "freq_gt_10":
            name = item.get("target_concept", "")
            if name and K.is_reference_concept(name):
                item = {**item, "kg_gate_recovered": True,
                        "kg_original_bin": bin_name}
                bin_name = "freq_gt_10"
                recovered += 1
        bins[bin_name].append(item)
    if guided:
        print(f"🧭 Guided gate recovery: promoted {recovered} reference-attested "
              f"concept(s) into freq_gt_10.")

    # ── 3. WRITE every bin under a NEW versioned directory (R21.3) ────────
    run_dir = C.output_dir(STAGE, __file__)
    print(f"💾 Writing bins to {run_dir} ...")
    counts: dict[str, int] = {}
    for bin_name in BIN_ORDER:
        items = bins.get(bin_name, [])
        if not items:
            continue
        bin_path = run_dir / f"{bin_name}.jsonl"
        C.save_jsonl(bin_path, items)
        counts[bin_name] = len(items)
        print(f"✅ Saved {len(items):,} concepts to {bin_path.name}")

    # ── 4. MANIFEST: per-bin counts (R4) ──────────────────────────────────
    counts["total"] = len(data)
    counts["gate_threshold"] = C.FREQ_GATE_DEFAULT
    if guided:
        counts["kg_gate_recovered"] = recovered
        counts["mode"] = "guided"
    C.write_manifest(
        STAGE, __file__, in_path=in_path, out_path=run_dir, counts=counts,
    )
    print(f"[{STAGE}] wrote {len([b for b in counts if b.startswith('freq_')])} "
          f"bin(s) -> {run_dir}")
    return run_dir


if __name__ == "__main__":
    run()
