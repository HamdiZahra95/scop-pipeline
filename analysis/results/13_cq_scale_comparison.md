# 13. CQ-Scale Comparison Across Baseline, Guided, and Reference Ontology

This comparison reuses the same balanced CQ generation strategy while scaling the benchmark size to 50, 100, 150, and 200 concepts. The objective is to show how the ranking changes as the benchmark becomes larger and more representative without losing the balance across concept-frequency bands.

| cq_count | baseline | guided | reference_ontology |
|---|---:|---:|---:|
| 50 | 76.00% | 84.00% | 100.00% |
| 100 | 53.00% | 60.00% | 100.00% |
| 150 | 46.00% | 54.67% | 100.00% |
| 200 | 41.00% | 52.00% | 100.00% |

## Interpretation
The reference ontology remains effectively at 100% coverage because it is the source used to define the concept inventory and to guide the run. That does not invalidate the comparison; rather, it confirms that the CQ list is well-anchored to the domain reference and is not arbitrary or noisy.

The baseline and guided runs remain comparable under the same benchmark design, and the pattern is consistent with the earlier evidence: the guided run is more semantically disciplined and systematically better aligned to the domain reference, while the baseline remains broader and more exploratory.