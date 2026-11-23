# v02. Structural / OntoQA Quality

Shared s13 metrics + OntoQA schema metrics. Primary comparison is the latest baseline vs the latest guided export.

| metric | baseline | guided | delta |
|---|---|---|---|
| class_count | 1993 | 2041 | +48 |
| concept_count | 1976 | 2024 | +48 |
| skeleton_count | 17 | 17 | +0 |
| max_depth | 10 | 11 | +1 |
| branching_factor | 2.398 | 2.444 | +0.046 |
| pct_with_parent | 1.0 | 1.0 | +0.0 |
| pct_with_property | 0.2237 | 0.2307 | +0.007 |
| orphan_ratio | 0.0 | 0.0 | +0.0 |
| inheritance_richness | 0.9975 | 0.9976 | +0.0001 |
| relationship_richness | 0.3224 | 0.3283 | +0.0059 |
| attribute_richness | 40.3512 | 39.2362 | -1.115 |
| tangledness | 0.0 | 0.0 | +0.0 |
| leaf_ratio | 0.584 | 0.5919 | +0.0079 |

## Variance across all exports (bootstrap 95% CI)
| mode | metric | mean | 95% CI | min | max |
|---|---|---|---|---|---|
| baseline | max_depth | 10.0 | [10.0, 10.0] (n=1) | 10 | 10 |
| baseline | branching_factor | 2.398 | [2.398, 2.398] (n=1) | 2.398 | 2.398 |
| baseline | orphan_ratio | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| baseline | inheritance_richness | 0.9975 | [0.9975, 0.9975] (n=1) | 0.9975 | 0.9975 |
| baseline | relationship_richness | 0.3224 | [0.3224, 0.3224] (n=1) | 0.3224 | 0.3224 |
| baseline | tangledness | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| guided | max_depth | 11.0 | [11.0, 11.0] (n=1) | 11 | 11 |
| guided | branching_factor | 2.444 | [2.444, 2.444] (n=1) | 2.444 | 2.444 |
| guided | orphan_ratio | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| guided | inheritance_richness | 0.9976 | [0.9976, 0.9976] (n=1) | 0.9976 | 0.9976 |
| guided | relationship_richness | 0.3283 | [0.3283, 0.3283] (n=1) | 0.3283 | 0.3283 |
| guided | tangledness | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |

## Notes
- Primary = latest baseline vs latest guided. Distribution spread across historical exports also reflects code-version changes, not only LLM run-to-run noise (see v07 for a cleaner stability study).
- OntoQA: inheritance_richness = is-a edges / classes; relationship_richness = non-isa / (isa+non-isa); attribute_richness = annotations / class; tangledness = fraction with >1 superclass; leaf_ratio = leaves / classes.