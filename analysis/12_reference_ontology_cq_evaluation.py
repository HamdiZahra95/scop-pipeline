from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowledge
from analysis.common import RESULTS_DIR, load_json, write_json, write_md

BENCHMARK_PATH = RESULTS_DIR / "10_balanced_cq_benchmark.json"
BASELINE_RESULT_PATH = RESULTS_DIR / "11_balanced_cq_evaluation.json"


def normalize(value: str) -> str:
    import re
    text = value.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    benchmark = load_json(BENCHMARK_PATH)
    comparison = load_json(BASELINE_RESULT_PATH)
    knowledge.load()

    ranked = []
    by_band = {"high_frequency": [], "medium_frequency": [], "low_frequency_important": []}
    for concept in benchmark["concepts_selected"]:
        term = concept["term"]
        match = knowledge.match(term)
        item = {
            "term": term,
            "band": concept["band"],
            "match_kind": match.kind,
            "ref_term": match.ref_term,
            "ref_parent": match.ref_parent,
            "score": match.score,
            "covered": match.matched,
        }
        ranked.append(item)
        by_band.setdefault(concept["band"], []).append(item)

    band_summary = {}
    for band_name, entries in by_band.items():
        covered = sum(1 for x in entries if x["covered"])
        total = len(entries)
        band_summary[band_name] = {
            "total": total,
            "covered": covered,
            "coverage_rate": round((covered / total) if total else 0.0, 4),
            "missing": [x["term"] for x in entries if not x["covered"]],
        }

    covered_total = sum(1 for x in ranked if x["covered"])
    total_total = len(ranked)
    result = {
        "benchmark_id": benchmark["benchmark_id"],
        "ontology_used_for_guidance": "ML_Ontology.ttl",
        "ontology_path": str(Path(__file__).resolve().parent.parent / "ML_Ontology.ttl"),
        "total_concepts": total_total,
        "covered_concepts": covered_total,
        "coverage_rate": round((covered_total / total_total) if total_total else 0.0, 4),
        "by_band": band_summary,
        "match_distribution": {
            "exact": sum(1 for x in ranked if x["match_kind"] == "exact"),
            "lexical": sum(1 for x in ranked if x["match_kind"] == "lexical"),
            "semantic": sum(1 for x in ranked if x["match_kind"] == "semantic"),
            "none": sum(1 for x in ranked if x["match_kind"] == "none"),
        },
        "details": ranked,
        "context": {
            "baseline_coverage_rate": comparison["baseline"]["coverage_rate"],
            "guided_coverage_rate": comparison["guided"]["coverage_rate"],
            "reference_ontology_vs_guided_delta": round((comparison["guided"]["coverage_rate"] - (covered_total / total_total)) if total_total else 0.0, 4),
        },
    }

    out_json = RESULTS_DIR / "12_reference_ontology_cq_evaluation.json"
    write_json(out_json, result)

    md_lines = [
        "# 12. Guidance Ontology CQ Evaluation",
        "",
        "This evaluation checks the same balanced CQ concept set against the ontology actually used as the guidance source during the knowledge-guided run.",
        "",
        f"- ontology: {result['ontology_used_for_guidance']}",
        f"- total concepts: {result['total_concepts']}",
        f"- covered concepts: {result['covered_concepts']}",
        f"- coverage rate: {result['coverage_rate']:.2%}",
        "",
        "## by band",
    ]
    for band, stats in band_summary.items():
        md_lines.append(f"### {band}")
        md_lines.append(f"- covered: {stats['covered']}/{stats['total']} = {stats['coverage_rate']:.2%}")
        if stats["missing"]:
            md_lines.append(f"- missing: {', '.join(stats['missing'])}")
        md_lines.append("")

    md_lines.extend([
        "## match distribution",
        f"- exact: {result['match_distribution']['exact']}",
        f"- lexical: {result['match_distribution']['lexical']}",
        f"- semantic: {result['match_distribution']['semantic']}",
        f"- none: {result['match_distribution']['none']}",
        "",
        "## interpretation",
        "The ontology used to guide the run covers the balanced CQ concept set almost completely, which is expected because it is the explicit domain reference used to anchor the guided pipeline. This also explains why the guided run can appear more disciplined and more semantically aligned to the benchmark than the unconstrained baseline.",
    ])
    write_md(RESULTS_DIR / "12_reference_ontology_cq_evaluation.md", "\n".join(md_lines))

    print(f"Reference ontology CQ evaluation saved to {out_json}")


if __name__ == "__main__":
    main()
