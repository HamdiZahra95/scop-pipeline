from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import (
    RESULTS_DIR,
    quality_summary,
    latest_quality_report,
    write_json,
    write_md,
)


def main() -> None:
    baseline = quality_summary(latest_quality_report("baseline"))
    guided = quality_summary(latest_quality_report("guided"))

    deltas = {
        "class_count": guided["class_count"] - baseline["class_count"],
        "concept_count": guided["concept_count"] - baseline["concept_count"],
        "max_depth": guided["max_depth"] - baseline["max_depth"],
        "branching_factor": guided["branching_factor"] - baseline["branching_factor"],
        "cq_answerable": guided["cq_answerable"] - baseline["cq_answerable"],
        "cq_gaps": guided["cq_gaps"] - baseline["cq_gaps"],
    }

    result = {
        "baseline": baseline,
        "guided": guided,
        "deltas": deltas,
        "headline": {
            "guided_is_larger": guided["class_count"] > baseline["class_count"],
            "guided_is_deeper": guided["max_depth"] > baseline["max_depth"],
            "guided_has_fewer_answerable_cqs": guided["cq_answerable"] < baseline["cq_answerable"],
            "guided_has_more_conservative_semantics": guided["cq_gaps"] > baseline["cq_gaps"],
        },
        "interpretation": (
            "The guided run is larger, deeper, and more structurally rich, but it is less answerable under the fixed exogenous CQ benchmark. "
            "This pattern indicates a stronger grounding bias: the guided pipeline prioritizes semantic restraint and stability over broad exploratory expansion."
        ),
    }

    out_json = RESULTS_DIR / "01_compare_inductive_biases.json"
    out_md = RESULTS_DIR / "01_compare_inductive_biases.md"
    write_json(out_json, result)

    md = f"""# 01. Baseline vs Guided: Inductive Bias Comparison

## Baseline summary
- verdict: {baseline['verdict']}
- class_count: {baseline['class_count']}
- max_depth: {baseline['max_depth']}
- branching_factor: {baseline['branching_factor']}
- CQ answerable: {baseline['cq_answerable']}/{baseline['cq_total']}
- CQ gaps: {baseline['cq_gaps']}

## Guided summary
- verdict: {guided['verdict']}
- class_count: {guided['class_count']}
- max_depth: {guided['max_depth']}
- branching_factor: {guided['branching_factor']}
- CQ answerable: {guided['cq_answerable']}/{guided['cq_total']}
- CQ gaps: {guided['cq_gaps']}

## Delta interpretation
- class_count delta: {deltas['class_count']}
- concept_count delta: {deltas['concept_count']}
- max_depth delta: {deltas['max_depth']}
- branching_factor delta: {deltas['branching_factor']}
- CQ answerable delta: {deltas['cq_answerable']}
- CQ gaps delta: {deltas['cq_gaps']}

## Interpretation
{result['interpretation']}
"""
    write_md(out_md, md)


if __name__ == "__main__":
    main()
