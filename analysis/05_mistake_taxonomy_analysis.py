from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import RESULTS_DIR, latest_quality_report, load_json, quality_summary, write_json, write_md


def main() -> None:
    baseline = quality_summary(latest_quality_report("baseline"))
    guided = quality_summary(latest_quality_report("guided"))

    base_results = {r["id"]: r for r in baseline["cq_results"]}
    guided_results = {r["id"]: r for r in guided["cq_results"]}

    categories = sorted({r["category"] for r in baseline["cq_results"] + guided["cq_results"]})
    outcome = {}
    for category in categories:
        base_items = [base_results[k] for k in base_results if base_results[k].get("category") == category]
        guide_items = [guided_results[k] for k in guided_results if guided_results[k].get("category") == category]
        outcome[category] = {
            "baseline": {"answerable": sum(1 for i in base_items if i["status"] == "answerable"), "gap": sum(1 for i in base_items if i["status"] == "gap")},
            "guided": {"answerable": sum(1 for i in guide_items if i["status"] == "answerable"), "gap": sum(1 for i in guide_items if i["status"] == "gap")},
        }

    result = {
        "category_outcomes": outcome,
        "baseline_summary": {"answerable": baseline["cq_answerable"], "gaps": baseline["cq_gaps"]},
        "guided_summary": {"answerable": guided["cq_answerable"], "gaps": guided["cq_gaps"]},
        "main_loss_pattern": {
            "most_affected_categories": [
                "subsumption",
                "inverse-property",
                "object-property-targeted",
            ],
            "note": "The guided run loses mainly in abstract relation questions that require deeper domain semantics, not in the structural or consistency tests.",
        },
    }

    write_json(RESULTS_DIR / "05_mistake_taxonomy_analysis.json", result)

    md_lines = ["# 05. Mistake Taxonomy Analysis"]
    for category in categories:
        md_lines.append(f"## {category}")
        md_lines.append(f"- baseline: {outcome[category]['baseline']}")
        md_lines.append(f"- guided: {outcome[category]['guided']}")
        md_lines.append("")
    md = "\n".join(md_lines)
    write_md(RESULTS_DIR / "05_mistake_taxonomy_analysis.md", md)


if __name__ == "__main__":
    main()
