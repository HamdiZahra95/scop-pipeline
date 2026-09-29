# 11. Balanced CQ Evaluation Against Both Runs

## Objective
This evaluation scores the baseline and guided ontology runs against the same corpus-grounded, frequency-balanced CQ benchmark. The comparison focuses on concept coverage under a shared benchmark rather than generic CQ counts alone.

## Overall coverage
- baseline coverage: 76.00%
- guided coverage: 84.00%
- delta: 8.00%
- winner: guided

## By frequency band
### high_frequency
- baseline: 11/16 = 68.75%
- guided: 14/16 = 87.50%

### medium_frequency
- baseline: 15/18 = 83.33%
- guided: 16/18 = 88.89%

### low_frequency_important
- baseline: 12/16 = 75.00%
- guided: 12/16 = 75.00%

## Interpretation
The benchmark is deliberately balanced across concept-frequency bands so that the broader exploratory run does not gain an unfair advantage merely by covering more generic terms. The side-by-side comparison therefore makes the trade-off more meaningful: broader recall is weighed against grounded coverage and disciplined retention across concept bands.