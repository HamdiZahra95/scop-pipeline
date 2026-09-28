# S09a parent-edge expert review

Judge every row independently. Do not infer or request which experimental condition
produced an edge. The competing edge may appear elsewhere in a different order.

## Labels

- **correctness:** `correct | incorrect | uncertain`. Select `correct` only when the concept
  is genuinely a kind/subclass of the candidate parent; related-to, used-by,
  part-of, and instance-of are incorrect.
- **specificity:** `too_broad | appropriate | too_narrow | uncertain`.
- **concept_validity:** `valid | noise | uncertain`.
- **confidence_1_to_5:** 1 (low) through 5 (high).

Do not edit `item_id`, `row_digest`, `concept`, `candidate_parent`, or
`concept_context`. The design is condition-blind: both competing parents may be
recognisable because the same concept can appear twice, so judge every edge
independently and do not try to infer condition identity. Complete the file
independently before discussing disagreements. The researcher must withhold
`blinding_key.json` until both reviews are locked.
