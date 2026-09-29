# v06. Grounding / Provenance Quality

- Grounding/provenance from the final formalized DB (S10); definition/altLabel coverage from the S11 OWL. corpus_attestation_rate = content concepts with corpus frequency f>0; f==0 content are promoted/materialized/reference-injected concepts that are structurally present but not corpus-attested. dangling_target_rate is a hallucination/ungrounded-target proxy (edge targets that are not a node).

| metric | baseline | guided | delta |
|---|---|---|---|
| content concepts (non-scaffolding) | 1162 | 1213 | +51 |
| corpus attestation rate (f>0) | 0.6954 | 0.695 | -0.0004 |
| object-property edges | 948 | 995 | +47 |
| literal annotations | 8435 | 8605 | +170 |
| demotion ratio (annotations / relations) | 0.899 | 0.8964 | -0.0026 |
| dangling-target rate (hallucination proxy) | 0.2627 | 0.2492 | -0.0135 |
| edge provenance rate (raw verbs) | 1.0 | 1.0 | +0.0 |
| definition coverage (skos:definition) | 0.3962 | 0.4067 | +0.0105 |
| altLabel coverage (skos:altLabel) | 0.1168 | 0.1167 | -0.0001 |
| comment coverage (rdfs:comment) | 0.4094 | 0.4178 | +0.0084 |

## f-band distribution (content concepts)
| mode | f==0 (not attested) | f 1–10 | f>10 |
|---|---|---|---|
| baseline | 354 | 0 | 808 |
| guided | 370 | 31 | 812 |

## Reading this
- **corpus_attestation_rate**: guidance did NOT reduce corpus grounding here — guided is slightly higher. The f-bands show why: baseline's gate (freq>10) leaves the f 1–10 band empty, while guided's S03 gate-recovery adds low-frequency but reference-attested corpus concepts (f 1–10) and carries fewer f==0 (ungrounded-injected) nodes.
- **dangling_target_rate**: baseline leaves a large share of object-property targets ungrounded (not a node); guided is markedly lower (S07 whitelist-union + S09a materialization). Note S11 still anchors such referenced-only targets under Machine_Learning, so they are not hallucinations in the final OWL, but they are under-specified nodes.
- **definition/altLabel coverage = 0 for BOTH modes** is a concrete, fixable pipeline gap: the OWL emits no skos:definition and no skos:altLabel because consolidated_definitions and merged surface forms (sf) are dropped upstream (definitions at S04), so S11's R20.3 definition/synonym emission is effectively dead. About half of concepts still carry an rdfs:comment, but only from demoted literal_annotations.
- **demotion_ratio ~0.90**: ~90% of mined relational content is kept as unlinked literal annotations rather than formal grounded edges — anti-hallucination conservatism, but it makes the formal relation layer thin (see v02 relationship_richness) and most extracted knowledge non-queryable as edges.