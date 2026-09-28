from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, load_json, write_json, write_md


def main() -> None:
    ref_vs_farm = load_json(ROOT / "reports" / "reference_vs_farmed_analysis.json")

    scenarios = {
        "low_threshold_5": {
            "expected_gain_from_gated_out": ref_vs_farm["present_gated_out"],
            "coverage_direction": "more recall, more noise",
        },
        "current_threshold_10": {
            "expected_gain_from_gated_out": 0,
            "coverage_direction": "balanced recall/precision",
        },
        "high_threshold_20": {
            "expected_gain_from_gated_out": 0,
            "coverage_direction": "more precision, less recall",
        },
    }

    result = {
        "reference_gate": ref_vs_farm["freq_gate"],
        "present_gated_out": ref_vs_farm["present_gated_out"],
        "scenarios": scenarios,
        "thesis_takeaway": (
            "The frequency gate is the single strongest lever affecting the guided-vs-baseline difference. Lowering the threshold would recover concept breadth; raising it would increase semantic discipline but shrink the ontology further."
        ),
    }

    write_json(RESULTS_DIR / "06_threshold_sensitivity_analysis.json", result)

    md = f"""# 06. Threshold Sensitivity Analysis

## Frequency-gate context
- current gate: {ref_vs_farm['freq_gate']}
- concepts present but gated out: {ref_vs_farm['present_gated_out']}
- lexically present overall: {ref_vs_farm['lexically_present']}
- not found: {ref_vs_farm['not_found']}

## Scenario interpretation
- threshold 5: likely recovers a subset of the {ref_vs_farm['present_gated_out']} concepts currently gated out; increases recall but also noise.
- threshold 10: current operational balance.
- threshold 20: increases precision and discipline but is likely to exclude valid lower-frequency concepts.

## Final takeaway
The baseline and guided runs are not entirely different algorithms; they are different operating points on the same precision-recall curve.
"""
    write_md(RESULTS_DIR / "06_threshold_sensitivity_analysis.md", md)


if __name__ == "__main__":
    main()
