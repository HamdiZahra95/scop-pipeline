# S09a expert parent-edge evaluation

**Status:** final preregistered headline analysis
**Comparison:** `fallback` → `full`
**Uncertain policy:** `incorrect`
**Review ready:** `True`
**Primary protocol compliant:** `True`
**Headline inference ready:** `True`

## Inter-reviewer agreement before adjudication

- correctness rows: 301
- raw agreement: 0.7708
- Cohen's kappa: 0.5778
- Fleiss' kappa (10 raters): 0.4233
- Mean pairwise Cohen's kappa: 0.4269

## Paired results

| population | n | control correct | treatment correct | risk difference (95% CI) | repairs | regressions | exact McNemar p | joint rule |
|---|---:|---:|---:|---|---:|---:|---:|---|
| changed parents (primary estimand) | 113 | 0.531 | 0.6814 | 0.1504 [0.0265, 0.2655] | 34 | 17 | 0.024093 | True |
| all sampled (secondary) | 188 | 0.6383 | 0.7287 | 0.0904 [0.0213, 0.1649] | 34 | 17 | 0.024093 | True |

## Interpretation boundary

Two complete independent reviews, separate adjudication, and every prespecified primary-analysis check are ready for headline inference.

Concept-level uncertainty conditional on one frozen S09 input and the selected replicate; it does not establish generalization to another corpus, domain, model family, or complete pipeline run.

A positive headline result requires protocol/review readiness, a confidence interval above zero, and exact McNemar `p < .05`. A null result is not evidence of equivalence.
