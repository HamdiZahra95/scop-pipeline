from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, latest_owl, latest_quality_report, load_json, write_json, write_md

BENCHMARK_PATH = RESULTS_DIR / "10_balanced_cq_benchmark.json"


def normalize_term(value: str) -> str:
    text = value.lower().strip()
    text = text.replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_ontology_tokens(owl_path: Path) -> set[str]:
    text = owl_path.read_text(encoding="utf-8", errors="ignore")

    labels = {normalize_term(m) for m in re.findall(r"<rdfs:label[^>]*>\s*([^<]+?)\s*</rdfs:label>", text, flags=re.I)}
    local_names = {
        normalize_term(m)
        for m in re.findall(r'rdf:about="[^"]*#([^"#]+)"', text, flags=re.I)
    }
    object_refs = {
        normalize_term(m)
        for m in re.findall(r'rdf:resource="[^"]*#([^"#]+)"', text, flags=re.I)
    }
    return labels | local_names | object_refs


def evaluate_run(benchmark: dict, owl_path: Path, mode: str) -> dict:
    concepts = benchmark["concepts_selected"]
    tokens = extract_ontology_tokens(owl_path)

    by_band = {"high_frequency": [], "medium_frequency": [], "low_frequency_important": []}
    by_type = {"class_identity": 0, "hierarchy": 0, "relation": 0, "property": 0, "distinction": 0, "evidence": 0}

    covered_concepts: list[str] = []
    missing_concepts: list[str] = []

    for concept in concepts:
        term = concept["term"]
        norm = normalize_term(term)
        covered = norm in tokens or any(norm in token for token in tokens if len(norm) > 4)
        bucket = concept["band"]
        by_band.setdefault(bucket, []).append({"term": term, "covered": covered})
        if covered:
            covered_concepts.append(term)
        else:
            missing_concepts.append(term)

    total_questions = 0
    for q in benchmark["questions"]:
        total_questions += 1
        qtype = q["type"]
        by_type[qtype] += 1

    band_stats = {}
    for band, items in by_band.items():
        covered = sum(1 for item in items if item["covered"])
        total = len(items)
        band_stats[band] = {
            "total_concepts": total,
            "covered_concepts": covered,
            "coverage_rate": round((covered / total) if total else 0.0, 4),
            "missing": [item["term"] for item in items if not item["covered"]],
        }

    type_stats = {}
    for qtype, total in by_type.items():
        # Each question type is mapped to at least one selected concept, so type score is derived from covered concept count for that family.
        q_cover = 0
        for q in benchmark["questions"]:
            if q["type"] != qtype:
                continue
            term = q["term"]
            if normalize_term(term) in tokens or any(normalize_term(term) in token for token in tokens if len(normalize_term(term)) > 4):
                q_cover += 1
        type_stats[qtype] = {
            "total_questions": total,
            "covered_questions": q_cover,
            "coverage_rate": round((q_cover / total) if total else 0.0, 4),
        }

    concept_coverage = round((len(covered_concepts) / len(concepts)) if concepts else 0.0, 4)

    return {
        "run_name": mode,
        "owl_path": str(owl_path),
        "total_concepts": len(concepts),
        "covered_concepts": len(covered_concepts),
        "coverage_rate": concept_coverage,
        "missing_concepts": missing_concepts,
        "by_band": band_stats,
        "by_question_type": type_stats,
    }


def main() -> None:
    benchmark = load_json(BENCHMARK_PATH)
    baseline = evaluate_run(benchmark, latest_owl("baseline"), "baseline")
    guided = evaluate_run(benchmark, latest_owl("guided"), "guided")

    baseline_coverage = baseline["coverage_rate"]
    guided_coverage = guided["coverage_rate"]
    delta = round(guided_coverage - baseline_coverage, 4)

    winner = "guided" if guided_coverage > baseline_coverage else "baseline" if baseline_coverage > guided_coverage else "tie"

    result = {
        "benchmark": {
            "path": str(BENCHMARK_PATH),
            "benchmark_id": benchmark.get("benchmark_id"),
            "concepts_selected": len(benchmark.get("concepts_selected", [])),
            "question_count": len(benchmark.get("questions", [])),
        },
        "baseline": baseline,
        "guided": guided,
        "side_by_side": {
            "baseline_coverage_rate": baseline_coverage,
            "guided_coverage_rate": guided_coverage,
            "coverage_delta": delta,
            "winner": winner,
            "better_by_band": {
                band: ("guided" if guided["by_band"].get(band, {}).get("coverage_rate", 0) > baseline["by_band"].get(band, {}).get("coverage_rate", 0)
                       else "baseline" if baseline["by_band"].get(band, {}).get("coverage_rate", 0) > guided["by_band"].get(band, {}).get("coverage_rate", 0)
                       else "tie")
                for band in ["high_frequency", "medium_frequency", "low_frequency_important"]
            },
        },
    }

    write_json(RESULTS_DIR / "11_balanced_cq_evaluation.json", result)

    md = [
        "# 11. Balanced CQ Evaluation Against Both Runs",
        "",
        "## Objective",
        "This evaluation scores the baseline and guided ontology runs against the same corpus-grounded, frequency-balanced CQ benchmark. The comparison focuses on concept coverage under a shared benchmark rather than generic CQ counts alone.",
        "",
        f"## Overall coverage",
        f"- baseline coverage: {baseline_coverage:.2%}",
        f"- guided coverage: {guided_coverage:.2%}",
        f"- delta: {delta:.2%}",
        f"- winner: {winner}",
        "",
        "## By frequency band",
    ]

    for band in ["high_frequency", "medium_frequency", "low_frequency_important"]:
        b = baseline["by_band"].get(band, {})
        g = guided["by_band"].get(band, {})
        md.append(f"### {band}")
        md.append(f"- baseline: {b.get('covered_concepts', 0)}/{b.get('total_concepts', 0)} = {b.get('coverage_rate', 0):.2%}")
        md.append(f"- guided: {g.get('covered_concepts', 0)}/{g.get('total_concepts', 0)} = {g.get('coverage_rate', 0):.2%}")
        md.append("")

    md.append("## Interpretation")
    md.append("The benchmark is deliberately balanced across concept-frequency bands so that the broader exploratory run does not gain an unfair advantage merely by covering more generic terms. The side-by-side comparison therefore makes the trade-off more meaningful: broader recall is weighed against grounded coverage and disciplined retention across concept bands.")
    write_md(RESULTS_DIR / "11_balanced_cq_evaluation.md", "\n".join(md))

    print(f"Balanced CQ evaluation complete: {RESULTS_DIR / '11_balanced_cq_evaluation.json'}")


if __name__ == "__main__":
    main()
