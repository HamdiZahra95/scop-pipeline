# v10. Competency-Question Quality (population + gold-grounded)

A naming-robust replacement for the 12 hardcoded-slug CQs. Part~A reports functional coverage over ALL discovered classes; Part~B reports gold-grounded functional subsumption precision/recall against held-out expert ontologies (non-circular).

- baseline OWL: `scop_baseline.owl`
- guided OWL: `scop_guided.owl`
- semantic matching: on; threshold 0.85

## Part A — functional coverage rates (share of discovered classes)
| CQ archetype | baseline | guided | population |
|---|---|---|---|
| Define <X>. (skos:definition present) | 0.396 (807/2037) | 0.407 (843/2073) | base 2037 / guided 2073 |
| Describe <X>. (any rdfs:comment present) | 0.409 (834/2037) | 0.418 (866/2073) | base 2037 / guided 2073 |
| What is <X> also called? (skos:altLabel present) | 0.117 (238/2037) | 0.117 (242/2073) | base 2037 / guided 2073 |
| What kinds of <X> are there? (>=1 subclass) | 0.409 (833/2037) | 0.403 (836/2073) | base 2037 / guided 2073 |
| Is <X> a model / task / algorithm / ...? (is-a reaches an ML leaf) | 0.785 (1599/2037) | 0.742 (1538/2073) | base 2037 / guided 2073 |
| What does <X> use / optimise / produce? (subject of >=1 relation) | 0.216 (441/2037) | 0.225 (466/2073) | base 2037 / guided 2073 |
| What uses / produces / relates to <X>? (object of >=1 relation) | 0.197 (401/2037) | 0.200 (414/2073) | base 2037 / guided 2073 |

## Part B — gold-grounded functional subsumption (strict matches)
"Is <child> a kind of <parent>?" scored against held-out expert is-a pairs, conditional on both concepts being present in our ontology.

| Reference | mode | recall | precision | F1 | expert pairs | matched concepts |
|---|---|---|---|---|---|---|
| CCS | baseline | 0.171 | 0.500 | 0.255 | 35 | 128 |
| CCS | guided | 0.118 | 0.333 | 0.174 | 34 | 131 |
| ITO | baseline | 0.042 | 0.143 | 0.065 | 24 | 116 |
| ITO | guided | 0.042 | 0.125 | 0.062 | 24 | 104 |
| AIO | baseline | 0.000 | 1.000 | 0.000 | 49 | 65 |
| AIO | guided | 0.042 | 0.200 | 0.069 | 48 | 63 |

## Reading this
- **Part A** iterates real class URIs, so it is immune to the naming/placement brittleness of the 12 hardcoded CQs; each row is a coverage statistic over the whole ontology, not a single concept.
- **define / synonyms** rates reflect the `skos:definition` / `skos:altLabel` channels; a value near 0 is the S04 definition-drop defect (fixed in code, pending a re-run), consistent with v06.
- **Part B** is conditional on concept co-presence, so it measures taxonomic correctness independently of concept coverage (v03/v09). Small `expert pairs` counts mean the estimate is under-powered — read the bootstrap CIs in the JSON.
- Not circular: the answer key is a held-out expert ontology, never the guiding ontology.