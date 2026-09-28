#!/usr/bin/env python3
"""
harvest_concepts.py — Upstream Corpus Harvesting (Volume-over-Depth).

Extracts exactly ONE salient scientific concept and its accompanying
single-sentence definitional gloss per abstract across scientific literature.

The harvested records form the frozen seed artifact ingested by Stage S01.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

# Load environment
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import common as C

SYSTEM_PROMPT = """You are an expert scientific ontology curator in Machine Learning.
For the provided academic abstract, extract exactly ONE primary domain concept
and provide a concise, single-sentence definitional gloss grounded in the text.

Output format must be valid JSON:
{
  "concept_name": "canonical surface term (lowercase, singular)",
  "definition": "single sentence defining the concept"
}
"""


def extract_concept_mock(row_id: int, abstract: str) -> Dict:
    """Deterministic offline extractor for demonstration and review testing."""
    # Simple heuristic fallback when offline
    first_sentence = abstract.strip().split(".")[0].strip()
    words = [w.strip(",$().'\"") for w in first_sentence.split() if len(w) > 4]
    candidate = words[0] if words else "machine learning"
    return {
        "id": row_id,
        "concept_name": candidate.lower(),
        "definition": f"A foundational concept in statistical learning described as: {first_sentence}."
    }


def extract_concept_llm(row_id: int, abstract: str) -> Dict:
    """Extract concept and definition using the configured foundation model."""
    user_prompt = f"Abstract:\n{abstract}\n\nExtract the primary concept and definition in JSON."
    try:
        response_text = C.call_llm(user_prompt=user_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0)
        # Parse JSON from response
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        payload = json.loads(clean_text.strip())
        return {
            "id": row_id,
            "concept_name": payload.get("concept_name", "").strip().lower(),
            "definition": payload.get("definition", "").strip()
        }
    except Exception as e:
        print(f"Warning: LLM extraction fallback for record {row_id}: {e}")
        return extract_concept_mock(row_id, abstract)


def harvest_corpus(input_csv: Path, output_jsonl: Path, limit: Optional[int] = None, mock: bool = False):
    print(f"[*] Starting Volume-over-Depth harvesting from {input_csv} -> {output_jsonl}")
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with open(input_csv, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            abstract = row.get("abstract") or row.get("text") or ""
            if abstract.strip():
                rows.append((i + 1, abstract))
            if limit and len(rows) >= limit:
                break

    print(f"[*] Loaded {len(rows)} abstracts to process (Mock mode: {mock}).")

    extracted_records = []
    for row_id, abstract in rows:
        if mock or not os.getenv("GEMINI_API_KEY"):
            record = extract_concept_mock(row_id, abstract)
        else:
            record = extract_concept_llm(row_id, abstract)
        
        extracted_records.append(record)
        print(f"  [{row_id:03d}] Harvested: '{record['concept_name']}'")

    with open(output_jsonl, "w", encoding="utf-8") as f:
        for r in extracted_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[✓] Successfully harvested {len(extracted_records)} concepts -> {output_jsonl}")
    return extracted_records


def main():
    parser = argparse.ArgumentParser(description="SCOP Pre-Pipeline: Volume-over-Depth Corpus Harvester.")
    parser.add_argument("--input", default=str(ROOT / "harvest" / "sample_abstracts.csv"),
                        help="Input CSV containing abstract column.")
    parser.add_argument("--output", default=str(ROOT / "data" / "seed" / "harvested_sample.jsonl"),
                        help="Output JSONL destination for harvested concepts.")
    parser.add_argument("--limit", type=int, default=5,
                        help="Maximum number of abstracts to harvest (default: 5).")
    parser.add_argument("--mock", action="store_true",
                        help="Run offline deterministic extractor without calling LLM APIs.")
    args = parser.parse_args()

    harvest_corpus(Path(args.input), Path(args.output), limit=args.limit, mock=args.mock)


if __name__ == "__main__":
    main()
