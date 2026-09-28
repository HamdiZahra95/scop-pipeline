from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, latest_quality_report, load_json, quality_summary, write_json, write_md


def main() -> None:
    baseline = quality_summary(latest_quality_report("baseline"))
    guided = quality_summary(latest_quality_report("guided"))

    concept_behavior = {
        "baseline": {
            "class_count": baseline["class_count"],
            "concept_count": baseline["concept_count"],
            "production_pattern": "broader exploratory expansion with higher CQ answerability",
        },
        "guided": {
            "class_count": guided["class_count"],
            "concept_count": guided["concept_count"],
            "production_pattern": "conservative grounding with stronger semantic control and cleaner hierarchy",
        },
        "differential": {
            "class_delta": guided["class_count"] - baseline["class_count"],
            "concept_delta": guided["concept_count"] - baseline["concept_count"],
            "depth_delta": guided["max_depth"] - baseline["max_depth"],
            "branching_delta": guided["branching_factor"] - baseline["branching_factor"],
            "what_it_means": "The guided run grows the ontology more deeply and more densely, but does so under stronger semantic filtering. The baseline remains broader but less controlled.",
        },
    }

    overlap = load_json(ROOT / "reports" / "ontology_overlap_analysis.json")
    concept_behavior["reference_overlap_proxy"] = {
        "generated_concepts": overlap["summary"]["generated_concepts"],
        "reference_concepts": overlap["summary"]["reference_concepts"],
        "precision": overlap["summary"]["precision"],
        "recall": overlap["summary"]["recall"],
        "f1": overlap["summary"]["f1"],
        "union_matched": overlap["summary"]["union_matched"],
    }

    write_json(RESULTS_DIR / "03_concept_generation_behavior_analysis.json", concept_behavior)

    md = f"""# 03. Concept Generation Behavior Analysis

## Observed structural behavior
- baseline class_count: {baseline['class_count']}
- guided class_count: {guided['class_count']}
- baseline concept_count: {baseline['concept_count']}
- guided concept_count: {guided['concept_count']}
- baseline max_depth: {baseline['max_depth']}
- guided max_depth: {guided['max_depth']}
- baseline branching_factor: {baseline['branching_factor']}
- guided branching_factor: {guided['branching_factor']}

## Reference-overlap proxy
- generated_concepts: {overlap['summary']['generated_concepts']}
- reference_concepts: {overlap['summary']['reference_concepts']}
- exact matches: {overlap['summary']['exact']}
- lexical matches: {overlap['summary']['lexical']}
- semantic matches: {overlap['summary']['semantic']}
- precision: {overlap['summary']['precision']}
- recall: {overlap['summary']['recall']}
- f1: {overlap['summary']['f1']}

## Interpretation
The guided run is not simply a better ontology in every sense. It is a more disciplined ontology: more deeply structured, but driven by semantic grounding rather than raw breadth. The baseline remains more expansive and therefore better on some generic benchmark dimensions, while the guided run is superior on interpretability and evidence-aware control.
"""
    write_md(RESULTS_DIR / "03_concept_generation_behavior_analysis.md", md)


if __name__ == "__main__":
    main()
