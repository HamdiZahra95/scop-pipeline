# Held-out gold ontologies (evaluation only)

These are **human-curated reference ontologies used ONLY for evaluation**. They
are deliberately kept here, under `analysis/gold/`, and **never** placed in
`seed/` — the pipeline must not be able to consume them as guidance. The
knowledge-guided run is guided solely by `seed/ML_Ontology.ttl`; these three are
independent, held-out references so that agreement with them is not an artifact
of the same generative process (they break the circularity of evaluating against
the guiding ontology).

Retrieved: 2026-08-31.

| Ontology | File | Source | Curation | Format / hierarchy | Stats (as retrieved) |
|---|---|---|---|---|---|
| Artificial Intelligence Ontology (AIO) | `aio.owl` | https://github.com/berkeleybop/artificial-intelligence-ontology (`aio.owl`, main) | Expert curation + LLM-assisted structural updates | RDF/XML OWL, `rdfs:subClassOf` | 442 classes, 442 subClassOf edges, 461 labelled nodes |
| ACM Computing Classification System 2012 | `acm_ccs2012_skos.xml` | https://github.com/cli99/acm-ccs (`ACMComputingClassificationSystemSKOSTaxonomy.xml`), an unmodified copy of the ACM CCS 2012 SKOS release (https://dl.acm.org/ccs) | Pure institutional human curation (ACM committee) | SKOS RDF/XML, poly-hierarchy via `skos:broader`; concept URIs under `http://totem.semedica.com/taxonomy/` | 2,299 skos:Concept, 2,390 skos:broader edges, 2,299 prefLabels |
| Intelligence Task Ontology (ITO) | `ITO.owl` (full) + `ito-ai-process.json` (task tree) | https://github.com/OpenBioLink/ITO (`ITO.owl.zip`, `ai-process.json`) | Manual expert curation | OWL (`rdfs:subClassOf`); JSON is a nested `{name, children}` task tree | full: 16,283 classes, 29,774 subClassOf edges; ai-process tree: lightweight task backbone |

## Roles in the evaluation
- **AIO** — richest content overlap with our generated ontology (models,
  networks, layers, training strategies, preprocessing): used for strict is-a
  taxonomic precision/recall/F1. Caveat: AIO's own construction was LLM-assisted,
  so it is treated as a *supplementary* reference, not the primary anti-circularity anchor.
- **ACM CCS** — purest human curation; used for upper/mid taxonomy and domain
  placement. `skos:broader` is "subfield-of", not strict is-a, so scored as
  ancestor-set (hierarchical) agreement rather than exact is-a.
- **ITO** — manual expert curation of AI tasks/benchmarks; used for the task-layer
  checks and a few externally-authored competency questions. The lightweight
  `ito-ai-process.json` task tree is preferred at runtime; the full `ITO.owl`
  (124 MB) is available for broader coverage but is heavy to parse.


## Reproduce
```
# from analysis/gold/
curl -sSL -o aio.owl               https://raw.githubusercontent.com/berkeleybop/artificial-intelligence-ontology/main/aio.owl
curl -sSL -o acm_ccs2012_skos.xml  https://raw.githubusercontent.com/cli99/acm-ccs/master/ACMComputingClassificationSystemSKOSTaxonomy.xml
curl -sSL -o ITO.owl.zip           https://raw.githubusercontent.com/OpenBioLink/ITO/master/ITO.owl.zip && python3 -c "import zipfile; zipfile.ZipFile('ITO.owl.zip').extractall('.')"
curl -sSL -o ito-ai-process.json   https://raw.githubusercontent.com/OpenBioLink/ITO/master/ai-process.json
```
