# v09. Significance of the Gold-Alignment Deltas

- bootstrap resamples: 2000; seed 42; semantic threshold 0.85
- CIs reflect sampling over the concept/pair population within the single latest baseline/guided ontologies, NOT LLM run-to-run variance (see v07). recall = paired (McNemar + paired bootstrap); coverage = unpaired (different concept sets); taxonomic F1 = paired weighted cluster bootstrap over covered gold concepts.

## CCS — ACM CCS 2012 (institutional human curation; skos:broader)

### strict
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0738 [0.0627, 0.0854] | 0.0758 [0.0653, 0.0871] | +0.0019 [-0.0144, 0.0178] | unpaired boot | False |
| recall of gold | 0.0579 [0.0487, 0.0679] | 0.06 [0.0509, 0.07] | +0.0022 [-0.0035, 0.0074] | McNemar p=0.5224 | False |
| taxonomic F1 | 0.0714 [0.0, 0.2222] | 0.1667 [0.027, 0.3153] | +0.0952 [-0.1165, 0.2853] | paired boot p=0.348 | False |

### with_semantic
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.1149 [0.1009, 0.1284] | 0.1207 [0.1075, 0.1359] | +0.0059 [-0.0137, 0.0256] | unpaired boot | False |
| recall of gold | 0.0687 [0.0583, 0.0796] | 0.0731 [0.0622, 0.0839] | +0.0043 [-0.0017, 0.0104] | McNemar p=0.1934 | False |
| taxonomic F1 | 0.1205 [0.0175, 0.2647] | 0.1854 [0.0613, 0.3206] | +0.0649 [-0.1163, 0.235] | paired boot p=0.5 | False |

## ITO — ITO (manual expert curation; AI task hierarchy)

### strict
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0565 [0.0468, 0.0666] | 0.0507 [0.0417, 0.0601] | -0.0058 [-0.0197, 0.008] | unpaired boot | False |
| recall of gold | 0.1067 [0.0884, 0.1249] | 0.0957 [0.0784, 0.1121] | -0.0109 [-0.0201, -0.0018] | McNemar p=0.0357 | True |
| taxonomic F1 | 0.1194 [0.0, 0.3846] | 0.0323 [0.0, 0.2353] | -0.0871 [-0.3, 0.0126] | paired boot p=0.366 | False |

### with_semantic
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0922 [0.0796, 0.1047] | 0.0857 [0.0739, 0.0975] | -0.0065 [-0.0236, 0.0109] | unpaired boot | False |
| recall of gold | 0.1231 [0.103, 0.1422] | 0.1176 [0.0985, 0.1367] | -0.0055 [-0.0146, 0.0036] | McNemar p=0.3075 | False |
| taxonomic F1 | 0.16 [0.0204, 0.4082] | 0.04 [0.0, 0.1967] | -0.12 [-0.3381, 0.0] | paired boot p=0.054 | False |

## AIO — AIO (expert + LLM-assisted; ML model/architecture is-a) — supplementary

### strict
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.0309 [0.0241, 0.0386] | 0.0298 [0.0227, 0.0374] | -0.0011 [-0.0115, 0.0093] | unpaired boot | False |
| recall of gold | 0.1448 [0.1131, 0.1787] | 0.1425 [0.1109, 0.1765] | -0.0023 [-0.0204, 0.0158] | McNemar p=1.0 | False |
| taxonomic F1 | 0.069 [0.0, 0.2449] | 0.0417 [0.0, 0.2195] | -0.0273 [-0.2222, 0.1935] | paired boot p=0.981 | False |

### with_semantic
| metric | baseline (95% CI) | guided (95% CI) | Δ (95% CI) | test | significant |
|---|---|---|---|---|---|
| coverage | 0.069 [0.0584, 0.0801] | 0.0616 [0.0516, 0.0724] | -0.0075 [-0.0223, 0.0074] | unpaired boot | False |
| recall of gold | 0.181 [0.1471, 0.2195] | 0.181 [0.1471, 0.2172] | +0.0 [-0.0181, 0.0181] | McNemar p=1.0 | False |
| taxonomic F1 | 0.1923 [0.0274, 0.4196] | 0.1159 [0.0116, 0.3] | -0.0764 [-0.2994, 0.1338] | paired boot p=0.476 | False |

## Reading this
- Δ = guided − baseline. **significant** = the 95% CI of the difference excludes 0 (for recall, also cross-check McNemar p<0.05).
- A non-significant Δ means the observed baseline/guided gap is within sampling noise over concepts — do not claim a winner on that metric.
- Coverage is unpaired (the runs discover different concept sets), so it has no McNemar test; recall and taxonomic F1 are paired.