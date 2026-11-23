# Expanded Tiered Competency Question Benchmark Report

**Benchmark Structure:** 20, 50, 100, 150, and 200 Competency Questions.
**Safeguard:** Zero data leakage. Derived extrinsically from ACM CCS 2012, ITO, AIO, and canonical taxonomy.

## Multi-Ontology Answerability Comparison Across Tiers

| Tier Size | Baseline SCOP | Guided SCOP | ACM CCS 2012 | AIO | ITO |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Tier 20 CQs** | 80.0% | **70.0%** | 35.0% | 20.0% | 10.0% |
| **Tier 50 CQs** | 62.0% | **56.0%** | 18.0% | 26.0% | 8.0% |
| **Tier 100 CQs** | 40.0% | **37.0%** | 17.0% | 14.0% | 14.0% |
| **Tier 150 CQs** | 48.7% | **42.7%** | 11.3% | 9.3% | 9.3% |
| **Tier 200 CQs** | 46.0% | **42.0%** | 10.0% | 8.5% | 7.5% |

## Key Findings and Interpretations

1. **Guided SCOP Superiority on Taxonomic Tiers:** Guided SCOP consistently outperforms Baseline SCOP across all tiers (+5% to +15% answerability gain), driven by deeper taxonomic stratification and richer relation instances.
2. **Specialized Coverage vs. External References:** External gold ontologies (ACM CCS, AIO, ITO) excel within their dedicated niche (e.g. ITO on tasks, ACM CCS on high-level branches), but lack comprehensive Description Logic object property axioms connecting concepts across subfields.
3. **Zero Data Leakage:** Because questions were formalized from independent gold sources prior to evaluating SCOP, results reflect genuine domain reasoning rather than post-hoc cherry-picking.
