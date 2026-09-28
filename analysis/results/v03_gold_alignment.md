# v03. Held-out Gold-Standard Alignment

Compares the generated baseline and guided ontologies against three **held-out, human-curated** reference ontologies the pipeline never used as guidance. This breaks the circularity of evaluating against the guiding ontology.

- threshold (semantic): 0.85
- semantic matching: on
- baseline OWL: `scop_baseline.owl`
- guided OWL: `scop_guided.owl`

## CCS — ACM CCS 2012 (institutional human curation; skos:broader)

### strict
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0738 | 0.0758 | +0.0020 | guided |
| recall of gold | 0.0579 | 0.0600 | +0.0021 | guided |
| taxonomic F1 | 0.0714 | 0.1667 | +0.0953 | guided |

### with_semantic
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.1149 | 0.1207 | +0.0058 | guided |
| recall of gold | 0.0687 | 0.0731 | +0.0044 | guided |
| taxonomic F1 | 0.1205 | 0.1854 | +0.0649 | guided |

## ITO — ITO (manual expert curation; AI task hierarchy)

### strict
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0565 | 0.0507 | -0.0058 | baseline |
| recall of gold | 0.1067 | 0.0957 | -0.0110 | baseline |
| taxonomic F1 | 0.1194 | 0.0323 | -0.0871 | baseline |

### with_semantic
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0922 | 0.0857 | -0.0065 | baseline |
| recall of gold | 0.1231 | 0.1176 | -0.0055 | baseline |
| taxonomic F1 | 0.1600 | 0.0400 | -0.1200 | baseline |

## AIO — AIO (expert + LLM-assisted; ML model/architecture is-a) — supplementary

### strict
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0309 | 0.0298 | -0.0011 | baseline |
| recall of gold | 0.1448 | 0.1425 | -0.0023 | baseline |
| taxonomic F1 | 0.0690 | 0.0417 | -0.0273 | baseline |

### with_semantic
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0690 | 0.0616 | -0.0074 | baseline |
| recall of gold | 0.1810 | 0.1810 | +0.0000 | tie |
| taxonomic F1 | 0.1923 | 0.1159 | -0.0764 | baseline |

## Notes
- **strict** = exact + normalized-lexical matches only (conservative). **with_semantic** adds embedding matches; treat as an upper bound and check `v03_match_samples.json` for matcher precision.
- Taxonomic F1 is agreement of is-a ANCESTOR pairs in gold-id space (hierarchical/`skos:broader` agreement for CCS).
- Coverage carries a bootstrap 95% CI (see JSON). Taxonomic-F1 significance testing is deferred to the v09 stats script.
- Held-out breaks pipeline circularity but not LLM pretraining contamination; structural (is-a) agreement is reported for that reason.