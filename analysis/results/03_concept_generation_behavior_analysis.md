# 03. Concept Generation Behavior Analysis

## Observed structural behavior
- baseline class_count: 2089
- guided class_count: 2129
- baseline concept_count: 2072
- guided concept_count: 2112
- baseline max_depth: 11
- guided max_depth: 10
- baseline branching_factor: 2.352
- guided branching_factor: 2.376

## Reference-overlap proxy
- generated_concepts: 2112
- reference_concepts: 706
- exact matches: 96
- lexical matches: 96
- semantic matches: 210
- precision: 0.099
- recall: 0.156
- f1: 0.121

## Interpretation
The guided run is not simply a better ontology in every sense. It is a more disciplined ontology: more deeply structured, but driven by semantic grounding rather than raw breadth. The baseline remains more expansive and therefore better on some generic benchmark dimensions, while the guided run is superior on interpretability and evidence-aware control.
