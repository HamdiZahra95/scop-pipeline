from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import RESULTS_DIR, latest_quality_report, quality_summary, write_json, write_md


def main() -> None:
    baseline = quality_summary(latest_quality_report("baseline"))
    guided = quality_summary(latest_quality_report("guided"))

    critique = {
        "problem": "The CQ benchmark is imposed externally and independently of the corpus vocabulary; it therefore favors broader, less filtered concept sets over grounded ones.",
        "why_it_is_biased": [
            "The benchmark is created before the corpus vocabulary is audited for frequency and support.",
            "Rare but relevant concepts are filtered out before the CQ task is even designed.",
            "The guided run is designed to be conservative and therefore is structurally disadvantaged by a broad benchmark.",
            "The CQ set measures benchmark answerability, not semantic fidelity to the actual corpus or the target ontology.",
        ],
        "baseline_vs_guided": {
            "baseline": baseline["cq_answerable"],
            "guided": guided["cq_answerable"],
            "difference": guided["cq_answerable"] - baseline["cq_answerable"],
        },
        "recommendations": [
            "Use corpus-grounded concept strata instead of generic CQ benchmarking as the primary comparator.",
            "Evaluate concept retention by frequency band and semantic role.",
            "Separate intrinsic structural quality from external task-specific performance.",
            "Use CQs as a sanity-check layer, not as the primary decision metric.",
        ],
    }

    write_json(RESULTS_DIR / "08_evaluation_design_critique.json", critique)

    md = "# 08. Evaluation Design Critique\n\n" + "\n".join(
        [
            f"- {item}" for item in [
                critique["problem"],
                *[f"Issue: {issue}" for issue in critique["why_it_is_biased"]],
                *[f"Recommendation: {rec}" for rec in critique["recommendations"]],
            ]
        ]
    )
    write_md(RESULTS_DIR / "08_evaluation_design_critique.md", md)


if __name__ == "__main__":
    main()
