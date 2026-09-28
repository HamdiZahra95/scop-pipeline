# v05. Edge Quality (LLM-as-judge)

- judge model: `gemma-4-31b-it`; is-a sampled: 60/mode; property sampled: 40/mode; seed 42

> **Caveat.** LLM-as-judge only: the judge shares a model family with the pipeline and may share its biases; verdicts are INDICATIVE, not validated accuracy. Judgments saved to v05_edge_samples.json for a future human kappa subset. Precision excludes 'unsure'.

## Judged precision (excludes 'unsure')
| mode | edge type | precision | 95% CI | correct/decided | unsure |
|---|---|---|---|---|---|
| baseline | is_a | 0.8333 | [0.7333, 0.9167] | 50/60 | 0/60 |
| baseline | property | 0.5385 | [0.3846, 0.6923] | 21/39 | 1/40 |
| guided | is_a | 0.8333 | [0.7333, 0.9167] | 50/60 | 0/60 |
| guided | property | 0.6154 | [0.4615, 0.7692] | 24/39 | 1/40 |

## Baseline vs guided (unpaired; different sampled edges)
| edge type | baseline | guided | delta |
|---|---|---|---|
| is_a | 0.8333 | 0.8333 | 0.0 |
| property | 0.5385 | 0.6154 | 0.0769 |

## Reading this
- **precision excludes 'unsure'** = correct / (correct + incorrect); the unsure column shows how often the judge abstained.
- Baseline vs guided is **unpaired** (different sampled edges from different ontologies); treat deltas as indicative, and cross-check with the held-out taxonomic agreement in v03/v09.
- These are LLM verdicts, not ground truth. `v05_edge_samples.json` holds every judgment for a human re-labeling / Cohen's-kappa pass.