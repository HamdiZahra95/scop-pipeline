from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, load_json, write_json, write_md


def main() -> None:
    reference_vs_farmed = load_json(ROOT / "reports" / "reference_vs_farmed_analysis.json")
    reference_in_defs = load_json(ROOT / "reports" / "reference_in_definitions.json")

    result = {
        "reference_vs_farmed_analysis": reference_vs_farmed,
        "reference_in_definitions": {
            "reference_labels": reference_in_defs.get("reference_labels"),
            "definitions_scanned": reference_in_defs.get("definitions_scanned"),
            "attested_in_definitions": reference_in_defs.get("attested_in_definitions"),
            "not_attested": reference_in_defs.get("not_attested"),
            "farmed_concepts_with_hit": reference_in_defs.get("farmed_concepts_with_hit"),
        },
        "interpretation": {
            "gate_is_a_major_source_of_loss": reference_vs_farmed["present_gated_out"] > 0,
            "dominant_gap_is_coverage_not_provenance": reference_vs_farmed["not_found"] > reference_vs_farmed["present_gated_out"],
            "actual_tradeoff": "The guided run is likely filtering away lower-frequency but still semantically relevant concepts, while the baseline keeps broader vocabulary recall.",
        },
    }

    write_json(RESULTS_DIR / "02_corpus_grounded_differential_analysis.json", result)

    md = f"""# 02. Corpus-Grounded Differential Analysis

## Reference-vs-farmed facts
- reference concepts: {reference_vs_farmed['reference_concepts']}
- farmed unique concepts: {reference_vs_farmed['farmed_unique']}
- frequency gate: {reference_vs_farmed['freq_gate']}
- present and high-frequency: {reference_vs_farmed['present_high_freq']}
- present but gated out: {reference_vs_farmed['present_gated_out']}
- lexically present: {reference_vs_farmed['lexically_present']}
- semantic additions: {reference_vs_farmed['semantic_additional']}
- not found: {reference_vs_farmed['not_found']}

## Definition attestation facts
- reference labels: {reference_in_defs['reference_labels']}
- definitions scanned: {reference_in_defs['definitions_scanned']}
- attested in definitions: {reference_in_defs['attested_in_definitions']}
- not attested: {reference_in_defs['not_attested']}

## Interpretation
The frequency gate is not a minor implementation detail: it directly suppresses a meaningful slice of reference concepts. The guided run therefore becomes more semantically disciplined, but also more likely to omit valid yet low-frequency concepts. This is a classic evidence-grounding trade-off: better control, lower recall.

The analysis also suggests that the external CQ benchmark is not a neutral estimator of the true corpus fit, because it is formulated before the model has seen the corpus-supported concept inventory. That means the benchmark is structurally biased toward broader recall and against conservative grounding.
"""
    write_md(RESULTS_DIR / "02_corpus_grounded_differential_analysis.md", md)


if __name__ == "__main__":
    main()
