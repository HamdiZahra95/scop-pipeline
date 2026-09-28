# v04. Competency Questions as Real Reasoner Queries

- Real graph/reasoner CQ queries (S12 logic), not substring matching. 'materialized' makes PROPERTY_AXIOMS inverse/symmetric/transitive semantics explicit in rdflib (faithful proxy for DL property inference); a CQ gained_by_inference is answerable by entailment. CQ12 consistency uses HermiT on the latest export; stability sweep is asserted-only (CQ12 uninformative there).

## Rollup
| mode | asserted answerable | materialized answerable | consistency |
|---|---|---|---|
| baseline | 11/12 | 11/12 | consistent |
| guided | 11/12 | 11/12 | consistent |

## Per-CQ (asserted → materialized)
| CQ | category | baseline | guided |
|---|---|---|---|
| CQ1 What are the subtypes of unsupervised learning? | subsumption | answerable | answerable |
| CQ2 Which concepts are a kind of ML model? | subsumption | answerable | answerable |
| CQ3 Is every concept reachable from a top-level domain? | subsumption-coverage | answerable | answerable |
| CQ4 What does an algorithm optimize? | object-property | answerable | answerable |
| CQ5 What optimizes cross-entropy / loss functions? | object-property-targeted | answerable | answerable |
| CQ6 Which models perform classification? | object-property-crossleaf | gap | gap |
| CQ7 What are the components of a neural network? | object-property-transitive | answerable | answerable |
| CQ8 Given an objective, which algorithms optimize it? | inverse-property | answerable | answerable |
| CQ9 What data does a model learn from, and what processes it? | inverse-property | answerable | answerable |
| CQ10 What is the definition of gradient descent? | annotation | answerable | answerable |
| CQ11 What alternative labels does a concept carry? | annotation | answerable | answerable |
| CQ12 Is the ontology consistent and are top-level domains disjoint? | disjointness-consistency | answerable | answerable |

## Answerability stability across healthy runs (asserted)
| CQ | baseline rate (n=1) | guided rate (n=1) |
|---|---|---|
| CQ1 | 1.0 | 1.0 |
| CQ2 | 1.0 | 1.0 |
| CQ3 | 1.0 | 1.0 |
| CQ4 | 1.0 | 1.0 |
| CQ5 | 1.0 | 1.0 |
| CQ6 | 0.0 | 0.0 |
| CQ7 | 1.0 | 1.0 |
| CQ8 | 1.0 | 1.0 |
| CQ9 | 1.0 | 1.0 |
| CQ10 | 1.0 | 1.0 |
| CQ11 | 1.0 | 1.0 |
| CQ12 | 0.0 | 0.0 |

## Reading this
- **asserted → materialized**: status on the asserted graph, then after making declared inverse/transitive/symmetric semantics explicit. *(by inference)* = the CQ is answerable only via entailment.
- **stability rate** = fraction of healthy runs where the CQ was answerable (1.0 = always). CQ12 is ~0 here because the sweep skips the reasoner; see the rollup for the real CQ12 verdict.
- A gap is a coverage gap (empty result), not a logical failure (only CQ12 inconsistency is gate-blocking).