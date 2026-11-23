# v10. Competency-Question Quality (population + gold-grounded)

A naming-robust replacement for the 12 hardcoded-slug CQs. Part~A reports functional coverage over ALL discovered classes; Part~B reports gold-grounded functional subsumption precision/recall against held-out expert ontologies (non-circular).

- baseline OWL: `scop_baseline.owl`
- guided OWL: `scop_guided.owl`
- semantic matching: on; threshold 0.85

## Part A — functional coverage rates (share of discovered classes)
| CQ archetype | baseline | guided | population |
|---|---|---|---|
| Define <X>. (skos:definition present) | 0.408 (807/1976) | 0.416 (842/2024) | base 1976 / guided 2024 |
| Describe <X>. (any rdfs:comment present) | 0.422 (834/1976) | 0.427 (865/2024) | base 1976 / guided 2024 |
| What is <X> also called? (skos:altLabel present) | 0.120 (238/1976) | 0.120 (242/2024) | base 1976 / guided 2024 |
| What kinds of <X> are there? (>=1 subclass) | 0.411 (812/1976) | 0.403 (816/2024) | base 1976 / guided 2024 |
| Is <X> a model / task / algorithm / ...? (is-a reaches an ML leaf) | 0.793 (1567/1976) | 0.750 (1517/2024) | base 1976 / guided 2024 |
| What does <X> use / optimise / produce? (subject of >=1 relation) | 0.223 (441/1976) | 0.230 (466/2024) | base 1976 / guided 2024 |
| What uses / produces / relates to <X>? (object of >=1 relation) | 0.203 (401/1976) | 0.204 (414/2024) | base 1976 / guided 2024 |

## Part B — gold-grounded functional subsumption (strict matches)
"Is <child> a kind of <parent>?" scored against held-out expert is-a pairs, conditional on both concepts being present in our ontology.

| Reference | mode | recall | precision | F1 | expert pairs | matched concepts |
|---|---|---|---|---|---|---|
| CCS | baseline | 0.167 | 0.500 | 0.250 | 36 | 132 |
| CCS | guided | 0.111 | 0.333 | 0.167 | 36 | 135 |
| ITO | baseline | 0.038 | 0.143 | 0.061 | 26 | 121 |
| ITO | guided | 0.035 | 0.125 | 0.054 | 29 | 122 |
| AIO | baseline | 0.018 | 1.000 | 0.036 | 55 | 70 |
| AIO | guided | 0.036 | 0.200 | 0.061 | 56 | 71 |

## Reading this
- **Part A** iterates real class URIs, so it is immune to the naming/placement brittleness of the 12 hardcoded CQs; each row is a coverage statistic over the whole ontology, not a single concept.
- **define / synonyms** rates reflect the `skos:definition` / `skos:altLabel` channels; a value near 0 is the S04 definition-drop defect (fixed in code, pending a re-run), consistent with v06.
- **Part B** is conditional on concept co-presence, so it measures taxonomic correctness independently of concept coverage (v03/v09). Small `expert pairs` counts mean the estimate is under-powered — read the bootstrap CIs in the JSON.
- Not circular: the answer key is a held-out expert ontology, never the guiding ontology.