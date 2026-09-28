from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, load_json, write_json, write_md


def main() -> None:
    ref_in_defs = load_json(ROOT / "reports" / "reference_in_definitions.json")
    ref_vs_farm = load_json(ROOT / "reports" / "reference_vs_farmed_analysis.json")

    missing_signal = {
        "reference_labels": ref_in_defs["reference_labels"],
        "definitions_scanned": ref_in_defs["definitions_scanned"],
        "attested_in_definitions": ref_in_defs["attested_in_definitions"],
        "not_attested": ref_in_defs["not_attested"],
        "top_mentioned_concepts": ref_in_defs.get("top_mentioned", [])[:15],
        "not_found_in_farmed": ref_vs_farm["not_found"],
    }

    write_json(RESULTS_DIR / "07_missing_concept_analysis.json", missing_signal)

    md = f"""# 07. Missing Concept Analysis

## Strong signals of undercoverage
- reference labels: {ref_in_defs['reference_labels']}
- definitions scanned: {ref_in_defs['definitions_scanned']}
- attested in definitions: {ref_in_defs['attested_in_definitions']}
- not attested: {ref_in_defs['not_attested']}
- not found in the farmed vocabulary: {ref_vs_farm['not_found']}

## Top mentioned conceptual anchors in the corpus
{chr(10).join(f'- {label}: {count}' for label, count in ref_in_defs.get('top_mentioned', [])[:15])}

## Interpretation
A large fraction of the target concept space is not directly attested in the corpus-derived definitions. This is exactly why a strict guided run can lose breadth: it is not actually discarding the domain, it is discarding low-frequency and weakly supported terms that the corpus itself does not strongly attest.
"""
    write_md(RESULTS_DIR / "07_missing_concept_analysis.md", md)


if __name__ == "__main__":
    main()
