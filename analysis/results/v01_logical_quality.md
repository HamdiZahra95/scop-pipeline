# v01. Logical Quality (reasoner-based, guidance-independent)

Consistency (HermiT) + subclass-cycle detection, reusing the s13. gate logic, across both modes and all their S11 exports. This axis does not depend on any reference ontology.

| mode | runs | latest consistency | latest cycle-free | runs w/ cycles | latest sound |
|---|---|---|---|---|---|
| baseline | 1 | consistent | True | 0/1 | True |
| guided | 1 | consistent | True | 0/1 | True |

## Notes
- 'unchecked' = the reasoner could not run or the curated axioms fall outside HermiT's DL subset; it is NOT a contradiction and does not fail the logical-soundness verdict. Subclass cycles (structural) always fail.
- **latest sound** judges the CURRENT artifact (latest export): cycle-free AND consistent. This is the verdict that matters for using the ontology.
- **runs w/ cycles** counts how many historical exports of that mode contained a subclass cycle — a stability signal. Cyclic older exports most likely predate the cycle guard or correspond to an S09 run that skipped `_break_subclass_cycles`; the specific run names are in the JSON (`runs_with_cycles`).
- Consistency is reasoned on the latest run by default (`--all-consistency` / `--max-consistency N` to widen).