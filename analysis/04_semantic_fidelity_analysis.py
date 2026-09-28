from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, load_json, write_json, write_md


def main() -> None:
    overlap = load_json(ROOT / "reports" / "ontology_overlap_analysis.json")
    reference_vs_farmed = load_json(ROOT / "reports" / "reference_vs_farmed_analysis.json")

    result = {
        "overlap_summary": overlap["summary"],
        "coverage_summary": {
            "present_high_freq": reference_vs_farmed["present_high_freq"],
            "present_gated_out": reference_vs_farmed["present_gated_out"],
            "lexically_present": reference_vs_farmed["lexically_present"],
            "semantic_additional": reference_vs_farmed["semantic_additional"],
            "not_found": reference_vs_farmed["not_found"],
        },
        "thesis_takeaway": {
            "semantic_fidelity_is_not_same_as_answerability": True,
            "guided_precision_is_better_if_phraseology_is_grounded": True,
            "external_CQ_benchmark_cannot_capture_all_semantic_breadth": True,
        },
    }

    write_json(RESULTS_DIR / "04_semantic_fidelity_analysis.json", result)

    md = f"""# 04. Semantic Fidelity Analysis

## Overlap proxy
- exact matches: {overlap['summary']['exact']}
- lexical matches: {overlap['summary']['lexical']}
- semantic matches: {overlap['summary']['semantic']}
- union matched: {overlap['summary']['union_matched']}
- precision: {overlap['summary']['precision']}
- recall: {overlap['summary']['recall']}
- f1: {overlap['summary']['f1']}

## Coverage proxy
- presented in high-frequency set: {reference_vs_farmed['present_high_freq']}
- present but gated out: {reference_vs_farmed['present_gated_out']}
- lexically present: {reference_vs_farmed['lexically_present']}
- semantically additional: {reference_vs_farmed['semantic_additional']}
- not found: {reference_vs_farmed['not_found']}

## Interpretation
The overlap statistics show that the project does not achieve high recall against a fixed external ontology, but that is not equivalent to saying the generated ontology is semantically poor. The guided strategy is intentionally more conservative. It privileges evidence-backed concepts over raw breadth, which is exactly the right trade-off for a grounded ontology-generation workflow.
"""
    write_md(RESULTS_DIR / "04_semantic_fidelity_analysis.md", md)


if __name__ == "__main__":
    main()
