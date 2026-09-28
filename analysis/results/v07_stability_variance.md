# v07. Run-to-Run Stability / Noise Floor

- Variance among reruns sharing a codehash is pure run-to-run (provider) noise; across codehashes it also reflects code evolution. 'delta_vs_noise' compares the latest guided-vs-baseline structural delta (v02) to the pooled within-code run-to-run std; exceeding ~2 sigma suggests the delta is not merely run noise. Note baseline's current-code group is small (n=2), so the pooled estimate borrows from older same-code groups.

## baseline — 20 export(s), latest code `eb24b73e`
- skipped (<200 classes): 7

| code version | runs | concept-set Jaccard | edge-set Jaccard | class_count (min–max) | current |
|---|---|---|---|---|---|
| `738c1fce` | 4 | 1.0 | 0.9935 | 1585–1585 |  |
| `5a7111f4` | 4 | 0.977 | 0.8245 | 1585–1641 |  |
| `eb24b73e` | 2 | 0.9753 | 0.8692 | 1641–1666 | yes |
| `2ecbbeaa` | 1 | — | — | — |  |
| `6a90b3ce` | 1 | — | — | — |  |
| `13681e7f` | 1 | — | — | — |  |

**Pooled within-code run-to-run std (noise floor):**
| metric | noise std |
|---|---|
| class_count | 22.1956 |
| concept_count | 22.1956 |
| max_depth | 0.0 |
| branching_factor | 0.1448 |
| orphan_ratio | 0.0569 |
| pct_with_property | 0.0041 |
| inheritance_richness | 0.0034 |
| relationship_richness | 0.004 |
| attribute_richness | 0.0807 |
| leaf_ratio | 0.0129 |

## guided — 4 export(s), latest code `15832df2`

| code version | runs | concept-set Jaccard | edge-set Jaccard | class_count (min–max) | current |
|---|---|---|---|---|---|
| `15832df2` | 4 | 0.9998 | 0.996 | 2121–2122 | yes |

**Pooled within-code run-to-run std (noise floor):**
| metric | noise std |
|---|---|
| class_count | 0.5 |
| concept_count | 0.5 |
| max_depth | 0.0 |
| branching_factor | 0.0025 |
| orphan_ratio | 0.0 |
| pct_with_property | 0.0 |
| inheritance_richness | 0.0002 |
| relationship_richness | 0.0001 |
| attribute_richness | 0.001 |
| leaf_ratio | 0.0003 |

## Latest guided-vs-baseline delta vs run-to-run noise
| metric | Δ (guided−baseline) | noise std | exceeds 2σ noise? |
|---|---|---|---|
| class_count | +40 | 22.1956 | no |
| concept_count | +40 | 22.1956 | no |
| max_depth | -1 | 0.0 | YES |
| branching_factor | +0.024 | 0.1448 | no |
| orphan_ratio | +0.0 | 0.0569 | no |
| pct_with_property | +0.0078 | 0.0041 | no |
| inheritance_richness | +0.0001 | 0.0034 | no |
| relationship_richness | +0.0063 | 0.004 | no |
| attribute_richness | -1.0043 | 0.0807 | YES |
| leaf_ratio | +0.0042 | 0.0129 | no |

## Reading this
- **concept-set / edge-set Jaccard** across same-code reruns measures how reproducible the discovered ontology is (1.0 = identical). Lower values quantify LLM run-to-run churn.
- **exceeds 2σ noise = YES** means the guided-vs-baseline structural difference is larger than run-to-run noise would explain (more likely a real effect than stochastic). This is a heuristic, not a formal test.
- Baseline's current-code group is small (n=2); the pooled noise std borrows from older same-code groups, assuming comparable noise magnitude.