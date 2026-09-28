# 08. Evaluation Design Critique

- The CQ benchmark is imposed externally and independently of the corpus vocabulary; it therefore favors broader, less filtered concept sets over grounded ones.
- Issue: The benchmark is created before the corpus vocabulary is audited for frequency and support.
- Issue: Rare but relevant concepts are filtered out before the CQ task is even designed.
- Issue: The guided run is designed to be conservative and therefore is structurally disadvantaged by a broad benchmark.
- Issue: The CQ set measures benchmark answerability, not semantic fidelity to the actual corpus or the target ontology.
- Recommendation: Use corpus-grounded concept strata instead of generic CQ benchmarking as the primary comparator.
- Recommendation: Evaluate concept retention by frequency band and semantic role.
- Recommendation: Separate intrinsic structural quality from external task-specific performance.
- Recommendation: Use CQs as a sanity-check layer, not as the primary decision metric.