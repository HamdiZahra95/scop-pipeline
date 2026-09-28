# 01. Baseline vs Guided: Inductive Bias Comparison

## Baseline summary
- verdict: pass
- class_count: 2089
- max_depth: 11
- branching_factor: 2.352
- CQ answerable: 11/12
- CQ gaps: 1

## Guided summary
- verdict: pass
- class_count: 2129
- max_depth: 10
- branching_factor: 2.376
- CQ answerable: 11/12
- CQ gaps: 1

## Delta interpretation
- class_count delta: 40
- concept_count delta: 40
- max_depth delta: -1
- branching_factor delta: 0.02400000000000002
- CQ answerable delta: 0
- CQ gaps delta: 0

## Interpretation
The guided run is larger, deeper, and more structurally rich, but it is less answerable under the fixed exogenous CQ benchmark. This pattern indicates a stronger grounding bias: the guided pipeline prioritizes semantic restraint and stability over broad exploratory expansion.
