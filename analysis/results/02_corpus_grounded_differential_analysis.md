# 02. Corpus-Grounded Differential Analysis

## Reference-vs-farmed facts
- reference concepts: 710
- farmed unique concepts: 42938
- frequency gate: 10
- present and high-frequency: 67
- present but gated out: 66
- lexically present: 133
- semantic additions: 73
- not found: 504

## Definition attestation facts
- reference labels: 709
- definitions scanned: 103231
- attested in definitions: 182
- not attested: 527

## Interpretation
The frequency gate is not a minor implementation detail: it directly suppresses a meaningful slice of reference concepts. The guided run therefore becomes more semantically disciplined, but also more likely to omit valid yet low-frequency concepts. This is a classic evidence-grounding trade-off: better control, lower recall.

The analysis also suggests that the external CQ benchmark is not a neutral estimator of the true corpus fit, because it is formulated before the model has seen the corpus-supported concept inventory. That means the benchmark is structurally biased toward broader recall and against conservative grounding.
