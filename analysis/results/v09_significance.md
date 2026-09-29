# v09. Significance of the Gold-Alignment Deltas

- bootstrap resamples: 2000; seed 42; semantic threshold 0.85
- CIs reflect sampling over the concept/pair population within the single latest baseline/guided ontologies, NOT LLM run-to-run variance (see v07). recall = paired (McNemar + paired bootstrap); coverage = unpaired (different concept sets); taxonomic F1 = paired weighted cluster bootstrap over covered gold concepts.

## CCS — ACM CCS 2012 (institutional human curation; skos:broader)

### strict
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0697 [0.0594, 0.081] | 0.0714 [0.0603, 0.0825] | +0.0017 [-0.0135, 0.0182] | unpaired boot | False |
| recall of gold | 0.0557 [0.0465, 0.0648] | 0.057 [0.0474, 0.0666] | +0.0013 [-0.0039, 0.0065] | McNemar p=0.7493 | False |
| taxonomic F1 | 0.2581 [0.0563, 0.5045] | 0.1714 [0.0, 0.3448] | -0.0866 [-0.3675, 0.1672] | paired boot p=0.538 | False |

### with_semantic
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.1114 [0.0987, 0.1252] | 0.1153 [0.1013, 0.1293] | +0.0039 [-0.0155, 0.0238] | unpaired boot | False |
| recall of gold | 0.0696 [0.0596, 0.08] | 0.0705 [0.0605, 0.0809] | +0.0009 [-0.0048, 0.0065] | McNemar p=0.8854 | False |
| taxonomic F1 | 0.2038 [0.0615, 0.3699] | 0.1915 [0.0617, 0.3333] | -0.0123 [-0.2073, 0.1805] | paired boot p=0.925 | False |

## ITO — ITO (manual expert curation; AI task hierarchy)

### strict
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0569 [0.0466, 0.0682] | 0.0502 [0.041, 0.0598] | -0.0068 [-0.0214, 0.0078] | unpaired boot | False |
| recall of gold | 0.1057 [0.0875, 0.124] | 0.0948 [0.0784, 0.113] | -0.0109 [-0.0201, -0.0018] | McNemar p=0.0357 | True |
| taxonomic F1 | 0.0923 [0.0, 0.4] | 0.0328 [0.0, 0.2381] | -0.0595 [-0.3, 0.0123] | paired boot p=0.714 | False |

### with_semantic
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0933 [0.08, 0.1065] | 0.0844 [0.0724, 0.096] | -0.0089 [-0.0269, 0.0087] | unpaired boot | False |
| recall of gold | 0.1231 [0.1039, 0.1422] | 0.1167 [0.0985, 0.1358] | -0.0064 [-0.0155, 0.0018] | McNemar p=0.2295 | False |
| taxonomic F1 | 0.2041 [0.0385, 0.4426] | 0.04 [0.0, 0.1928] | -0.1641 [-0.3548, -0.0244] | paired boot p=0.024 | True |

## AIO — AIO (expert + LLM-assisted; ML model/architecture is-a) — supplementary

### strict
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0319 [0.0245, 0.0398] | 0.0304 [0.0236, 0.0381] | -0.0015 [-0.0126, 0.0091] | unpaired boot | False |
| recall of gold | 0.1471 [0.1154, 0.181] | 0.1425 [0.1109, 0.1787] | -0.0045 [-0.0204, 0.009] | McNemar p=0.7539 | False |
| taxonomic F1 | 0.022 [0.0, 0.0896] | 0.0412 [0.0, 0.2169] | +0.0193 [-0.0484, 0.1951] | paired boot p=1.0 | False |

### with_semantic
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0707 [0.0599, 0.0825] | 0.0608 [0.0507, 0.0709] | -0.0099 [-0.025, 0.0057] | unpaired boot | False |
| recall of gold | 0.1855 [0.1493, 0.2217] | 0.1765 [0.1425, 0.2127] | -0.009 [-0.0271, 0.009] | McNemar p=0.4545 | False |
| taxonomic F1 | 0.0966 [0.0, 0.2727] | 0.0896 [0.0, 0.2817] | -0.007 [-0.1491, 0.1604] | paired boot p=0.908 | False |

## Reading this
- Δ = guided − baseline. **significant** = the 95% CI of the difference excludes 0 (for recall, also cross-check McNemar p<0.05).
- A non-significant Δ means the observed baseline/guided gap is within sampling noise over concepts — do not claim a winner on that metric.
- Coverage is unpaired (the runs discover different concept sets), so it has no McNemar test; recall and taxonomic F1 are paired.