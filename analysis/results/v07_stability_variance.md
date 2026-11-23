# v07. Run-to-Run Stability / Noise Floor

- Variance among reruns sharing a codehash is pure run-to-run (provider) noise; across codehashes it also reflects code evolution. 'delta_vs_noise' compares the latest guided-vs-baseline structural delta (v02) to the pooled within-code run-to-run std; exceeding ~2 sigma suggests the delta is not merely run noise. Note baseline's current-code group is small (n=2), so the pooled estimate borrows from older same-code groups.

## baseline — 1 export(s), latest code `nocode`

| code version | runs | concept-set Jaccard | edge-set Jaccard | class_count (min–max) | current |
|---|---|---|---|---|---|
| `nocode` | 1 | — | — | — | yes |

**Pooled within-code run-to-run std (noise floor):**
| metric | noise std |
|---|---|
| class_count | — |
| concept_count | — |
| max_depth | — |
| branching_factor | — |
| orphan_ratio | — |
| pct_with_property | — |
| inheritance_richness | — |
| relationship_richness | — |
| attribute_richness | — |
| leaf_ratio | — |

## guided — 1 export(s), latest code `nocode`

| code version | runs | concept-set Jaccard | edge-set Jaccard | class_count (min–max) | current |
|---|---|---|---|---|---|
| `nocode` | 1 | — | — | — | yes |

**Pooled within-code run-to-run std (noise floor):**
| metric | noise std |
|---|---|
| class_count | — |
| concept_count | — |
| max_depth | — |
| branching_factor | — |
| orphan_ratio | — |
| pct_with_property | — |
| inheritance_richness | — |
| relationship_richness | — |
| attribute_richness | — |
| leaf_ratio | — |

## Latest guided-vs-baseline delta vs run-to-run noise
| metric | Δ (guided−baseline) | noise std | exceeds 2σ noise? |
|---|---|---|---|
| class_count | +48 | None | — |
| concept_count | +48 | None | — |
| max_depth | +1 | None | — |
| branching_factor | +0.046 | None | — |
| orphan_ratio | +0.0 | None | — |
| pct_with_property | +0.007 | None | — |
| inheritance_richness | +0.0001 | None | — |
| relationship_richness | +0.0059 | None | — |
| attribute_richness | -1.115 | None | — |
| leaf_ratio | +0.0079 | None | — |

## Reading this
- **concept-set / edge-set Jaccard** across same-code reruns measures how reproducible the discovered ontology is (1.0 = identical). Lower values quantify LLM run-to-run churn.
- **exceeds 2σ noise = YES** means the guided-vs-baseline structural difference is larger than run-to-run noise would explain (more likely a real effect than stochastic). This is a heuristic, not a formal test.
- Baseline's current-code group is small (n=2); the pooled noise std borrows from older same-code groups, assuming comparable noise magnitude.