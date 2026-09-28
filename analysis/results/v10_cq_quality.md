# v10. Competency-Question Quality (population + gold-grounded)

A naming-robust replacement for the 12 hardcoded-slug CQs. Part~A reports functional coverage over ALL discovered classes; Part~B reports gold-grounded functional subsumption precision/recall against held-out expert ontologies (non-circular).

- baseline OWL: `scop_baseline.owl`
- guided OWL: `scop_guided.owl`
- semantic matching: on; threshold 0.85

## Part A — functional coverage rates (share of discovered classes)
| CQ archetype | baseline | guided | population |
|---|---|---|---|
| Define <X>. (skos:definition present) | 0.392 (812/2072) | 0.400 (844/2112) | base 2072 / guided 2112 |
| Describe <X>. (any rdfs:comment present) | 0.396 (820/2072) | 0.405 (855/2112) | base 2072 / guided 2112 |
| What is <X> also called? (skos:altLabel present) | 0.115 (239/2072) | 0.115 (242/2112) | base 2072 / guided 2112 |
| What kinds of <X> are there? (>=1 subclass) | 0.419 (869/2072) | 0.415 (877/2112) | base 2072 / guided 2112 |
| Is <X> a model / task / algorithm / ...? (is-a reaches an ML leaf) | 0.756 (1567/2072) | 0.728 (1537/2112) | base 2072 / guided 2112 |
| What does <X> use / optimise / produce? (subject of >=1 relation) | 0.214 (443/2072) | 0.221 (467/2112) | base 2072 / guided 2112 |
| What uses / produces / relates to <X>? (object of >=1 relation) | 0.194 (402/2072) | 0.196 (414/2112) | base 2072 / guided 2112 |

## Part B — gold-grounded functional subsumption (strict matches)
"Is <child> a kind of <parent>?" scored against held-out expert is-a pairs, conditional on both concepts being present in our ontology.

| Reference | mode | recall | precision | F1 | expert pairs | matched concepts |
|---|---|---|---|---|---|---|
| CCS | baseline | 0.026 | 0.167 | 0.045 | 38 | 133 |
| CCS | guided | 0.154 | 0.353 | 0.214 | 39 | 138 |
| ITO | baseline | 0.080 | 0.250 | 0.121 | 25 | 117 |
| ITO | guided | 0.042 | 0.125 | 0.062 | 24 | 105 |
| AIO | baseline | 0.032 | 0.500 | 0.061 | 31 | 64 |
| AIO | guided | 0.042 | 0.200 | 0.069 | 48 | 63 |

## Reading this
- **Part A** iterates real class URIs, so it is immune to the naming/placement brittleness of the 12 hardcoded CQs; each row is a coverage statistic over the whole ontology, not a single concept.
- **define / synonyms** rates reflect the `skos:definition` / `skos:altLabel` channels; a value near 0 is the S04 definition-drop defect (fixed in code, pending a re-run), consistent with v06.
- **Part B** is conditional on concept co-presence, so it measures taxonomic correctness independently of concept coverage (v03/v09). Small `expert pairs` counts mean the estimate is under-powered — read the bootstrap CIs in the JSON.
- Not circular: the answer key is a held-out expert ontology, never the guiding ontology.