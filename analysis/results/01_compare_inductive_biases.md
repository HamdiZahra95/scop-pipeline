# 01. Baseline vs Guided: Inductive Bias Comparison

## Baseline summary
- verdict: pass
- class_count: 1993
- max_depth: 10
- branching_factor: 2.398
- CQ answerable: 12/12
- CQ gaps: 0

## Guided summary
- verdict: pass
- class_count: 2041
- max_depth: 11
- branching_factor: 2.444
- CQ answerable: 12/12
- CQ gaps: 0

## Delta interpretation
- class_count delta: 48
- concept_count delta: 48
- max_depth delta: 1
- branching_factor delta: 0.04599999999999982
- CQ answerable delta: 0
- CQ gaps delta: 0

## Interpretation
The guided run is larger, deeper, and more structurally rich, but it is less answerable under the fixed exogenous CQ benchmark. This pattern indicates a stronger grounding bias: the guided pipeline prioritizes semantic restraint and stability over broad exploratory expansion.
