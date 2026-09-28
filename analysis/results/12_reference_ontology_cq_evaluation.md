# 12. Guidance Ontology CQ Evaluation

This evaluation checks the same balanced CQ concept set against the ontology actually used as the guidance source during the knowledge-guided run.

- ontology: ML_Ontology.ttl
- total concepts: 50
- covered concepts: 50
- coverage rate: 100.00%

## by band
### high_frequency
- covered: 16/16 = 100.00%

### medium_frequency
- covered: 18/18 = 100.00%

### low_frequency_important
- covered: 16/16 = 100.00%

## match distribution
- exact: 50
- lexical: 0
- semantic: 0
- none: 0

## interpretation
The ontology used to guide the run covers the balanced CQ concept set almost completely, which is expected because it is the explicit domain reference used to anchor the guided pipeline. This also explains why the guided run can appear more disciplined and more semantically aligned to the benchmark than the unconstrained baseline.