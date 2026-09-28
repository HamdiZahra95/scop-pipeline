# v02. Structural / OntoQA Quality

Shared S12 metrics + OntoQA schema metrics. Primary comparison is the latest baseline vs the latest guided export.

| metric | baseline | guided | delta |
|---|---|---|---|
| class_count | 2089 | 2129 | +40 |
| concept_count | 2072 | 2112 | +40 |
| skeleton_count | 17 | 17 | +0 |
| max_depth | 11 | 10 | -1 |
| branching_factor | 2.352 | 2.376 | +0.024 |
| pct_with_parent | 1.0 | 1.0 | +0.0 |
| pct_with_property | 0.2138 | 0.2216 | +0.0078 |
| orphan_ratio | 0.0 | 0.0 | +0.0 |
| inheritance_richness | 0.9976 | 0.9977 | +0.0001 |
| relationship_richness | 0.3131 | 0.3194 | +0.0063 |
| attribute_richness | 38.6769 | 37.6726 | -1.0043 |
| tangledness | 0.0 | 0.0 | +0.0 |
| leaf_ratio | 0.5759 | 0.5801 | +0.0042 |

## Variance across all exports (bootstrap 95% CI)
| mode | metric | mean | 95% CI | min | max |
|---|---|---|---|---|---|
| baseline | max_depth | 11.0 | [11.0, 11.0] (n=1) | 11 | 11 |
| baseline | branching_factor | 2.352 | [2.352, 2.352] (n=1) | 2.352 | 2.352 |
| baseline | orphan_ratio | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| baseline | inheritance_richness | 0.9976 | [0.9976, 0.9976] (n=1) | 0.9976 | 0.9976 |
| baseline | relationship_richness | 0.3131 | [0.3131, 0.3131] (n=1) | 0.3131 | 0.3131 |
| baseline | tangledness | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| guided | max_depth | 10.0 | [10.0, 10.0] (n=1) | 10 | 10 |
| guided | branching_factor | 2.376 | [2.376, 2.376] (n=1) | 2.376 | 2.376 |
| guided | orphan_ratio | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |
| guided | inheritance_richness | 0.9977 | [0.9977, 0.9977] (n=1) | 0.9977 | 0.9977 |
| guided | relationship_richness | 0.3194 | [0.3194, 0.3194] (n=1) | 0.3194 | 0.3194 |
| guided | tangledness | 0.0 | [0.0, 0.0] (n=1) | 0.0 | 0.0 |

## Notes
- Primary = latest baseline vs latest guided. Distribution spread across historical exports also reflects code-version changes, not only LLM run-to-run noise (see v07 for a cleaner stability study).
- OntoQA: inheritance_richness = is-a edges / classes; relationship_richness = non-isa / (isa+non-isa); attribute_richness = annotations / class; tangledness = fraction with >1 superclass; leaf_ratio = leaves / classes.