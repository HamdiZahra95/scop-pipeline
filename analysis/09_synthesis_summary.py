from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import RESULTS_DIR, write_md


def main() -> None:
    md = """# 09. Integrated Thesis-Level Synthesis

## Core conclusion
The baseline and guided runs are not two versions of the same ontology objective. They are two different operating points on the same ontology-generation problem:

- the baseline run prioritizes broader concept discovery and higher CQ answerability,
- the guided run prioritizes semantic grounding, structural discipline, and evidence-aware control.

## The real trade-off
The guided pipeline is not universally better, but it is better when the central concern is ontology reliability rather than raw breadth. It filters the concept space more aggressively, which makes the ontology more stable, more explainable, and more faithful to the reference evidence structure.

The baseline pipeline remains useful when the objective is broader conceptual recall, including lower-frequency or less strongly grounded terms. However, the cost is greater semantic drift and lower discipline.

## Why the CQ comparison is incomplete
The competency-question tests are useful as a secondary sanity check, but they are not a sufficient primary comparator. They are defined externally to the corpus and therefore tend to reward the broader, less filtered run. They do not capture whether the preserved concepts are the ones that the corpus, the reference ontology, and the domain evidence actually support.

## Thesis-ready formulation
A more defensible thesis statement is:

> The guided pipeline improves ontology quality by prioritizing semantic grounding and process control, while the baseline pipeline preserves broader concept recall. The two runs therefore trade precision against recall, and the appropriate choice depends on whether the objective is controlled ontology construction or exploratory concept discovery.

## Practical interpretation
If the thesis goal is to argue that knowledge guidance improves ontology quality, the evidence should be framed around ground truth fidelity, structural consistency, provenance, and semantic discipline rather than generic CQ count comparisons alone.
"""
    write_md(RESULTS_DIR / "09_synthesis_summary.md", md)


if __name__ == "__main__":
    main()
