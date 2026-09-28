from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.common import ROOT, RESULTS_DIR, load_json, write_json, write_md

DEFAULT_INPUT = ROOT / "reports" / "reference_in_definitions.json"
DEFAULT_OUTPUT = RESULTS_DIR / "10_balanced_cq_benchmark.json"
DEFAULT_MD = RESULTS_DIR / "10_balanced_cq_benchmark.md"

QUESTION_TEMPLATES = {
    "class_identity": {
        "prompt": "What is {concept} in the ontology, and what distinguishes it from a closely related concept?",
        "answer_type": "concept_definition",
    },
    "hierarchy": {
        "prompt": "Is {concept} a type, subtype, or sibling of another concept in the ontology? Identify the most plausible parent or superordinate class.",
        "answer_type": "hierarchy",
    },
    "relation": {
        "prompt": "Which relation or property most naturally connects {concept} to {neighbor}? Explain the semantic connection.",
        "answer_type": "relation",
    },
    "property": {
        "prompt": "Which property best characterizes {concept}, and why is it more appropriate than neighboring terms in the same domain?",
        "answer_type": "property",
    },
    "distinction": {
        "prompt": "How does {concept} differ from {neighbor}, and under what conditions would one be preferred over the other?",
        "answer_type": "distinction",
    },
    "evidence": {
        "prompt": "Which corpus evidence or definitional support most strongly justifies including {concept} in the ontology?",
        "answer_type": "evidence",
    },
}


def extract_concepts(payload: dict) -> list[dict]:
    if isinstance(payload.get("top_mentioned"), list):
        items = payload["top_mentioned"]
        concepts = []
        for idx, item in enumerate(items):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                term, count = item[0], item[1]
                concepts.append({"term": str(term), "frequency": int(count), "source_index": idx})
            elif isinstance(item, dict):
                term = item.get("term") or item.get("concept") or item.get("label")
                count = item.get("frequency") or item.get("count") or 1
                concepts.append({"term": str(term), "frequency": int(count), "source_index": idx})
        if concepts:
            return concepts

    if isinstance(payload.get("concepts"), list):
        concepts = []
        for idx, item in enumerate(payload["concepts"]):
            if isinstance(item, dict):
                term = item.get("term") or item.get("concept") or item.get("label")
                count = item.get("frequency") or item.get("count") or 1
                concepts.append({"term": str(term), "frequency": int(count), "source_index": idx})
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                concepts.append({"term": str(item[0]), "frequency": int(item[1]), "source_index": idx})
        if concepts:
            return concepts

    if isinstance(payload.get("reference_labels"), int):
        return [{"term": f"concept_{i}", "frequency": 1, "source_index": i} for i in range(1, payload["reference_labels"] + 1)]

    raise ValueError("Input JSON does not contain an extractable concept inventory.")


def assign_frequency_band(concepts: list[dict]) -> list[dict]:
    if not concepts:
        return []

    freqs = sorted(c["frequency"] for c in concepts)
    if len(freqs) == 1:
        threshold_low = threshold_high = freqs[0]
    elif len(freqs) == 2:
        threshold_low = freqs[0]
        threshold_high = freqs[-1]
    else:
        third = max(1, len(freqs) // 3)
        threshold_low = freqs[third]
        threshold_high = freqs[-third]

    for concept in concepts:
        f = concept["frequency"]
        if f >= threshold_high:
            concept["band"] = "high_frequency"
        elif f >= threshold_low:
            concept["band"] = "medium_frequency"
        else:
            concept["band"] = "low_frequency_important"

    return concepts


def choose_neighbor(term: str, concepts: list[dict], same_band: bool = True) -> str:
    relevant = [c for c in concepts if c["term"] != term]
    if same_band:
        band_terms = [c for c in relevant if c["band"] == next(c2["band"] for c2 in concepts if c2["term"] == term)]
        if band_terms:
            relevant = band_terms
    relevant = sorted(relevant, key=lambda x: x["frequency"], reverse=True)
    if not relevant:
        return "a closely related concept"
    return relevant[0]["term"]


def sample_balanced_concepts(concepts: list[dict], total_target: int = 60, band_ratios: tuple[float, float, float] = (0.4, 0.4, 0.2)) -> list[dict]:
    by_band = {"high_frequency": [], "medium_frequency": [], "low_frequency_important": []}
    for concept in concepts:
        by_band.setdefault(concept["band"], []).append(concept)

    desired = {
        "high_frequency": int(round(total_target * band_ratios[0])),
        "medium_frequency": int(round(total_target * band_ratios[1])),
        "low_frequency_important": total_target - int(round(total_target * band_ratios[0])) - int(round(total_target * band_ratios[1])),
    }

    band_order = ["high_frequency", "medium_frequency", "low_frequency_important"]
    selected: list[dict] = []
    remaining_slots = total_target

    for band in band_order:
        bucket = sorted(by_band.get(band, []), key=lambda x: x["frequency"], reverse=True)
        take = min(len(bucket), desired[band], remaining_slots)
        selected.extend(bucket[:take])
        remaining_slots -= take

    if remaining_slots > 0:
        for band in band_order:
            bucket = sorted(by_band.get(band, []), key=lambda x: x["frequency"], reverse=True)
            already = sum(1 for x in selected if x["band"] == band)
            remaining_bucket = [x for x in bucket if x not in selected]
            fill = min(len(remaining_bucket), remaining_slots)
            selected.extend(remaining_bucket[:fill])
            remaining_slots -= fill
            if remaining_slots == 0:
                break

    selected = selected[:total_target]
    if not selected:
        return sorted(concepts, key=lambda x: x["frequency"], reverse=True)[:total_target]
    return selected


def build_question(concept: dict, concepts: list[dict], qtype: str) -> dict:
    template = QUESTION_TEMPLATES[qtype]
    neighbor = choose_neighbor(concept["term"], concepts)
    prompt = template["prompt"].format(concept=concept["term"], neighbor=neighbor)
    return {
        "cq_id": f"cq_{concept['term'].lower().replace(' ', '_')}_{qtype}",
        "term": concept["term"],
        "band": concept["band"],
        "type": qtype,
        "prompt": prompt,
        "answer_type": template["answer_type"],
        "frequency": concept["frequency"],
    }


def generate_benchmark(concept_inventory_path: str | Path, total_target: int = 60) -> dict:
    payload = load_json(concept_inventory_path)
    concepts = assign_frequency_band(extract_concepts(payload))
    total_target = min(total_target, len(concepts))
    sample = sample_balanced_concepts(concepts, total_target=total_target)

    generated: list[dict] = []
    for concept in sample:
        for qtype in ["class_identity", "hierarchy", "relation", "property", "distinction", "evidence"]:
            generated.append(build_question(concept, concepts, qtype))

    by_band = {band: 0 for band in ["high_frequency", "medium_frequency", "low_frequency_important"]}
    by_type = {qtype: 0 for qtype in QUESTION_TEMPLATES}
    for item in generated:
        by_band[item["band"]] = by_band.get(item["band"], 0) + 1
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1

    benchmark = {
        "benchmark_id": "balanced_corpus_cq_v1",
        "input_inventory": str(Path(concept_inventory_path)),
        "strategy": {
            "objective": "Create a corpus-grounded, frequency-balanced CQ benchmark that avoids over-representing generic high-frequency concepts.",
            "bands": ["high_frequency", "medium_frequency", "low_frequency_important"],
            "target_total_concepts": total_target,
            "ratio": {"high_frequency": 0.4, "medium_frequency": 0.4, "low_frequency_important": 0.2},
            "question_types": list(QUESTION_TEMPLATES.keys()),
        },
        "concepts_selected": [
            {"term": c["term"], "frequency": c["frequency"], "band": c["band"]} for c in sample
        ],
        "counts_by_band": by_band,
        "counts_by_question_type": by_type,
        "total_questions": len(generated),
        "questions": generated,
    }
    return benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a balanced corpus-grounded competency-question benchmark.")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT), help="Path to a JSON concept inventory file.")
    parser.add_argument("--target", type=int, default=60, help="Target number of selected concepts to balance across frequency bands.")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="JSON destination for the generated benchmark.")
    parser.add_argument("--markdown", type=str, default=str(DEFAULT_MD), help="Markdown destination for the benchmark summary.")
    args = parser.parse_args()

    benchmark = generate_benchmark(args.input, total_target=args.target)
    write_json(args.output, benchmark)

    lines = [
        "# Balanced CQ Benchmark",
        "",
        "## objective",
        "This benchmark is intentionally frequency-balanced and corpus-grounded so that high-frequency generic concepts do not dominate the evaluation of both ontology-generation runs.",
        "",
        "## benchmark design",
        "- benchmark_id: balanced_corpus_cq_v1",
        f"- total selected concepts: {len(benchmark['concepts_selected'])}",
        f"- total generated questions: {benchmark['total_questions']}",
        "- bands: high_frequency, medium_frequency, low_frequency_important",
        "- question types: class_identity, hierarchy, relation, property, distinction, evidence",
        "",
        "## selected concepts by band",
    ]
    for band in ["high_frequency", "medium_frequency", "low_frequency_important"]:
        entries = [c for c in benchmark["concepts_selected"] if c["band"] == band]
        lines.append(f"### {band} ({len(entries)})")
        for concept in entries[:10]:
            lines.append(f"- {concept['term']} (frequency={concept['frequency']})")
        lines.append("")

    lines.extend([
        "## sample questions",
        "",
    ])
    for question in benchmark["questions"][:6]:
        lines.append(f"- {question['type']} | {question['term']} | {question['prompt']}")
    lines.append("")
    lines.append("This pipeline is designed to keep the benchmark comparable across runs without letting the broad, exploratory baseline benefit from an evaluation set dominated by frequent generic concepts.")

    write_md(args.markdown, "\n".join(lines))
    print(f"Balanced CQ benchmark written to: {args.output}")
    print(f"Benchmark summary written to: {args.markdown}")


if __name__ == "__main__":
    main()
