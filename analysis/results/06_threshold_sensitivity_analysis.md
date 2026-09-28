# 06. Threshold Sensitivity Analysis

## Frequency-gate context
- current gate: 10
- concepts present but gated out: 66
- lexically present overall: 133
- not found: 504

## Scenario interpretation
- threshold 5: likely recovers a subset of the 66 concepts currently gated out; increases recall but also noise.
- threshold 10: current operational balance.
- threshold 20: increases precision and discipline but is likely to exclude valid lower-frequency concepts.

## Final takeaway
The baseline and guided runs are not entirely different algorithms; they are different operating points on the same precision-recall curve.
