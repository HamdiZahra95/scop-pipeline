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
| coverage of generated | 0.0697 | 0.0714 | +0.0017 | guided |
| recall of gold | 0.0557 | 0.0570 | +0.0013 | guided |
| taxonomic F1 | 0.2581 | 0.1714 | -0.0867 | baseline |

### with_semantic
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.1114 | 0.1153 | +0.0039 | guided |
| recall of gold | 0.0696 | 0.0705 | +0.0009 | guided |
| taxonomic F1 | 0.2038 | 0.1915 | -0.0123 | baseline |

## ITO — ITO (manual expert curation; AI task hierarchy)

### strict
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0569 | 0.0502 | -0.0067 | baseline |
| recall of gold | 0.1057 | 0.0948 | -0.0109 | baseline |
| taxonomic F1 | 0.0923 | 0.0328 | -0.0595 | baseline |

### with_semantic
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0933 | 0.0844 | -0.0089 | baseline |
| recall of gold | 0.1231 | 0.1167 | -0.0064 | baseline |
| taxonomic F1 | 0.2041 | 0.0400 | -0.1641 | baseline |

## AIO — AIO (expert + LLM-assisted; ML model/architecture is-a) — supplementary

### strict
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0319 | 0.0304 | -0.0015 | baseline |
| recall of gold | 0.1471 | 0.1425 | -0.0046 | baseline |
| taxonomic F1 | 0.0220 | 0.0412 | +0.0192 | guided |

### with_semantic
| metric | baseline | guided | delta | winner |
|---|---|---|---|---|
| coverage of generated | 0.0707 | 0.0608 | -0.0099 | baseline |
| recall of gold | 0.1855 | 0.1765 | -0.0090 | baseline |
| taxonomic F1 | 0.0966 | 0.0896 | -0.0070 | baseline |

## Notes
- **strict** = exact + normalized-lexical matches only (conservative). **with_semantic** adds embedding matches; treat as an upper bound and check `v03_match_samples.json` for matcher precision.
- Taxonomic F1 is agreement of is-a ANCESTOR pairs in gold-id space (hierarchical/`skos:broader` agreement for CCS).
- Coverage carries a bootstrap 95% CI (see JSON). Taxonomic-F1 significance testing is deferred to the v09 stats script.
- Held-out breaks pipeline circularity but not LLM pretraining contamination; structural (is-a) agreement is reported for that reason.