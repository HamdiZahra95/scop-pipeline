# 04. Semantic Fidelity Analysis

## Overlap proxy
- exact matches: 96
- lexical matches: 96
- semantic matches: 210
- union matched: 210
- precision: 0.099
- recall: 0.156
- f1: 0.121

## Coverage proxy
- presented in high-frequency set: 67
- present but gated out: 66
- lexically present: 133
- semantically additional: 73
- not found: 504

## Interpretation
The overlap statistics show that the project does not achieve high recall against a fixed external ontology, but that is not equivalent to saying the generated ontology is semantically poor. The guided strategy is intentionally more conservative. It privileges evidence-backed concepts over raw breadth, which is exactly the right trade-off for a grounded ontology-generation workflow.
