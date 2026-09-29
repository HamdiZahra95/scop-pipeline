# v02. Structural / OntoQA Quality

Shared s13 metrics + OntoQA schema metrics. Primary comparison is the latest baseline vs the latest guided export.

| metric | baseline | guided | delta |
|---|---|---|---|
| class_count | 2054 | 2090 | +36 |
| concept_count | 2037 | 2073 | +36 |
| skeleton_count | 17 | 17 | +0 |
| max_depth | 10 | 10 | +0 |
| branching_factor | 2.411 | 2.444 | +0.033 |
| pct_with_parent | 1.0 | 1.0 | +0.0 |
| pct_with_property | 0.217 | 0.2253 | +0.0083 |
| orphan_ratio | 0.0 | 0.0 | +0.0 |
| inheritance_richness | 0.9976 | 0.9976 | +0.0 |
| relationship_richness | 0.3159 | 0.3231 | +0.0072 |
| attribute_richness | 39.1855 | 38.3445 | -0.841 |
| tangledness | 0.0 | 0.0 | +0.0 |
| leaf_ratio | 0.5862 | 0.5919 | +0.0057 |

## Variance across all exports (bootstrap 95% CI)
| mode | metric | mean | 95% CI | min | max |
|---|---|---|---|---|---|
| baseline | max_depth | 10.0 | [10.0, 10.0] (n=1) | 10 | 10 |
| baseline | branching_factor | 2.411 | [2.411, 2.411] (n=1) | 2.411 | 2.411 |
| baseline | orphan_ratio | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| baseline | inheritance_richness | 0.9976 | [0.9976, 0.9976] (n=1) | 0.9976 | 0.9976 |
| baseline | relationship_richness | 0.3159 | [0.3159, 0.3159] (n=1) | 0.3159 | 0.3159 |
| baseline | tangledness | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| guided | max_depth | 10.0 | [10.0, 10.0] (n=1) | 10 | 10 |
| guided | branching_factor | 2.444 | [2.444, 2.444] (n=1) | 2.444 | 2.444 |
| guided | orphan_ratio | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| guided | inheritance_richness | 0.9976 | [0.9976, 0.9976] (n=1) | 0.9976 | 0.9976 |
| guided | relationship_richness | 0.3231 | [0.3231, 0.3231] (n=1) | 0.3231 | 0.3231 |
| guided | tangledness | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |

## Notes
- Primary = latest baseline vs latest guided. Distribution spread across historical exports also reflects code-version changes, not only LLM run-to-run noise (see v07 for a cleaner stability study).
- OntoQA: inheritance_richness = is-a edges / classes; relationship_richness = non-isa / (isa+non-isa); attribute_richness = annotations / class; tangledness = fraction with >1 superclass; leaf_ratio = leaves / classes.