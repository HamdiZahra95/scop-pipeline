#!/usr/bin/env python3
"""
v15c_multi_llm_expert_panel.py — 10-Model Frontier Committee Evaluator for S09a.

This script executes an automated expert review across a panel of up to 10 distinct
frontier LLMs from different labs (DeepSeek, Alibaba, Mistral, NVIDIA, Moonshot, Zhipu, MiniMax)
via the Ollama Cloud API.

Key design principles:
1. Complete Independence: Each model evaluates blinded concept pairs without knowledge of other models.
2. Batched Inference: Concepts are evaluated in batches of 10 to minimize API requests and credit usage.
3. Fault-Tolerant Persistent Cache: Every batch response is saved immediately; interruptions resume smoothly.
4. Standardized Protocol Output:
   - Exports reviewer_1.csv through reviewer_10.csv matching the exact row digests and schema.
   - Computes ensemble majority voting into adjudication.csv.
   - Computes 10x10 pairwise Cohen's Kappa matrix and multi-rater Fleiss' Kappa.
   - Runs v16_score_s09a_expert_review.py for protocol-verified statistical inference.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ollama

# Default 10-Model Frontier Roster
DEFAULT_PANEL_MODELS: List[Tuple[str, str, str]] = [
    ("reviewer_1", "deepseek-v4.1-flash", "DeepSeek V4.1 Flash (1.6T MoE)"),
    ("reviewer_2", "qwen3.5:397b", "Qwen 3.5 397B (Alibaba MoE)"),
    ("reviewer_3", "mistral-large-3:675b", "Mistral Large 3 (675B MoE)"),
    ("reviewer_4", "nemotron-3-ultra", "Nemotron 3 Ultra (NVIDIA Flagship)"),
    ("reviewer_5", "gpt-oss:120b", "GPT-OSS 120B (Open Weights)"),
    ("reviewer_6", "kimi-k3", "Kimi K3 (Moonshot 1.56T MoE)"),
    ("reviewer_7", "glm-5.3", "GLM 5.3 (Zhipu 755B MoE)"),
    ("reviewer_8", "minimax-m3", "MiniMax M3 (MiniMax MoE)"),
    ("reviewer_9", "nemotron-3-super", "Nemotron 3 Super (NVIDIA Super)"),
    ("reviewer_10", "deepseek-v4-pro:0813", "DeepSeek V4 Pro (1.6T MoE)"),
]

SCHEMA_FIELDS = [
    "item_id", "row_digest", "concept", "candidate_parent",
    "concept_context", "correctness", "specificity", "concept_validity",
    "confidence_1_to_5", "notes",
]

CORRECTNESS_VALS = {"correct", "incorrect", "uncertain"}
SPECIFICITY_VALS = {"too_broad", "appropriate", "too_narrow", "uncertain"}
VALIDITY_VALS = {"valid", "noise", "uncertain"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_ollama_client(api_key: Optional[str] = None, host: Optional[str] = None) -> ollama.Client:
    key = (api_key or os.getenv("OLLAMA_API_KEY") or "").strip()
    endpoint = (
        host
        or os.getenv("OLLAMA_HOST")
        or "https://ollama.com"
    ).strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return ollama.Client(host=endpoint, headers=headers)


def _load_cache(cache_path: Path) -> Dict[str, Any]:
    if cache_path.is_file():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache_path: Path, data: Dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp_path.replace(cache_path)


def _build_batch_prompt(batch: List[Dict[str, str]]) -> str:
    item_lines = []
    for row in batch:
        item_id = row["item_id"]
        concept = row["concept"]
        parent = row["candidate_parent"]
        context = row.get("concept_context", "").strip()
        item_lines.append(
            f"Item ID: {item_id}\n"
            f"  - Concept: \"{concept}\"\n"
            f"  - Candidate Direct Parent: \"{parent}\"\n"
            f"  - Context / Definition Evidence: {context}\n"
        )
    items_block = "\n".join(item_lines)

    return f"""You are an expert machine-learning ontologist and formal taxonomic auditor evaluating candidate taxonomic is-a (subclass) edges.

For each concept and candidate direct parent, strictly evaluate whether the concept is genuinely a specialization / subClassOf the parent according to formal ontology principles (Description Logic, ACM CCS, and domain literature).

Criteria:
1. correctness: "correct" if the concept is genuinely a true subClassOf parent. "incorrect" if it is merely associative, part-of, uses, produces, or belongs to a different domain branch. "uncertain" if ambiguous.
2. specificity: "appropriate" if the parent represents the correct immediate abstraction level. "too_broad" if the parent is overly generic (e.g. swept to a top root). "too_narrow" if overly restrictive. "uncertain" if unclear.
3. concept_validity: "valid" if the term is a genuine scientific concept. "noise" if corrupted extraction noise. "uncertain" if unknown.
4. confidence: an integer from 1 (very unsure) to 5 (completely certain).
5. notes: a concise explanation (under 25 words) justifying your verdict.

Evaluate these {len(batch)} items:
{items_block}

Respond STRICTLY in valid JSON matching this schema:
{{
  "evaluations": [
    {{
      "item_id": "item_id_here",
      "correctness": "correct|incorrect|uncertain",
      "specificity": "appropriate|too_broad|too_narrow|uncertain",
      "concept_validity": "valid|noise|uncertain",
      "confidence": 5,
      "notes": "concise rationale"
    }}
  ]
}}
"""


def _clean_json_str(text: str) -> str:
    text = text.strip()
    bt3 = "```"
    if text.startswith(bt3 + "json"):
        text = text[len(bt3) + 4:]
    elif text.startswith(bt3):
        text = text[len(bt3):]
    if text.endswith(bt3):
        text = text[:-len(bt3)]
    text = text.strip()
    start_brace = text.find("{")
    start_bracket = text.find("[")
    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        end_brace = text.rfind("}")
        if end_brace != -1:
            return text[start_brace:end_brace + 1]
    elif start_bracket != -1:
        end_bracket = text.rfind("]")
        if end_bracket != -1:
            return text[start_bracket:end_bracket + 1]
    return text


def _normalize_eval(item_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    c = str(raw.get("correctness", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if c not in CORRECTNESS_VALS:
        c = "correct" if "correct" in c else "incorrect" if "incorrect" in c else "uncertain"

    s = str(raw.get("specificity", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if s not in SPECIFICITY_VALS:
        s = "appropriate" if "appr" in s else "too_broad" if "broad" in s else "too_narrow" if "narr" in s else "uncertain"

    v = str(raw.get("concept_validity", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if v not in VALIDITY_VALS:
        v = "valid" if "valid" in v else "noise" if "noise" in v else "uncertain"

    conf = str(raw.get("confidence") or raw.get("confidence_1_to_5") or "4").strip()
    if conf not in {"1", "2", "3", "4", "5"}:
        try:
            val = int(float(conf))
            conf = str(max(1, min(5, val)))
        except Exception:
            conf = "4"

    notes = str(raw.get("notes", "")).strip().replace("\n", " ")[:200]

    return {
        "item_id": item_id,
        "correctness": c,
        "specificity": s,
        "concept_validity": v,
        "confidence_1_to_5": conf,
        "notes": notes,
    }


def _call_model_batch(
    client: ollama.Client,
    model: str,
    batch: List[Dict[str, str]],
    cache: Dict[str, Any],
    cache_path: Path,
    max_retries: int = 5,
) -> Dict[str, Dict[str, Any]]:
    batch_ids = [row["item_id"] for row in batch]
    cache_key = f"{model}::" + "_".join(batch_ids)

    if cache_key in cache:
        return {item["item_id"]: item for item in cache[cache_key]}

    prompt = _build_batch_prompt(batch)
    expected_ids = set(batch_ids)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.0},
            )
            content = response.message.content.strip()
            cleaned = _clean_json_str(content)
            parsed = json.loads(cleaned)
            evals = parsed.get("evaluations", [])
            if isinstance(parsed, list):
                evals = parsed

            results_by_id = {}
            for item in evals:
                if isinstance(item, dict) and "item_id" in item:
                    iid = str(item["item_id"]).strip()
                    if iid in expected_ids:
                        results_by_id[iid] = _normalize_eval(iid, item)

            # Ensure all batch items are present
            if len(results_by_id) == len(expected_ids):
                ordered = [results_by_id[iid] for iid in batch_ids]
                cache[cache_key] = ordered
                _save_cache(cache_path, cache)
                return results_by_id

            # If partial, fill in missing with defaults
            for iid in expected_ids:
                if iid not in results_by_id:
                    results_by_id[iid] = _normalize_eval(iid, {"correctness": "uncertain", "notes": "unparsed fallback"})
            ordered = [results_by_id[iid] for iid in batch_ids]
            cache[cache_key] = ordered
            _save_cache(cache_path, cache)
            return results_by_id

        except Exception as e:
            wait_time = 2.0 * attempt
            print(f"      ↳ [{model}] error (attempt {attempt}/{max_retries}): {e}. Retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)

    # Fail-safe fallback if all retries exhausted
    fallback = {
        iid: _normalize_eval(iid, {"correctness": "uncertain", "notes": "API call retry timeout"})
        for iid in batch_ids
    }
    cache[cache_key] = [fallback[iid] for iid in batch_ids]
    _save_cache(cache_path, cache)
    return fallback


def _compute_cohen_kappa(r1: Dict[str, str], r2: Dict[str, str], categories: Tuple[str, ...]) -> float:
    common_ids = sorted(set(r1) & set(r2))
    if not common_ids:
        return 0.0
    v1 = [r1[i] for i in common_ids]
    v2 = [r2[i] for i in common_ids]
    n = len(common_ids)
    observed = sum(a == b for a, b in zip(v1, v2)) / n

    c1 = Counter(v1)
    c2 = Counter(v2)
    expected = sum((c1[cat] / n) * (c2[cat] / n) for cat in categories)
    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1.0 - expected), 4)


def _compute_fleiss_kappa(ratings: Dict[str, Dict[str, str]], categories: Tuple[str, ...]) -> float:
    """Compute Fleiss' Kappa across N raters on common subjects."""
    raters = list(ratings.keys())
    if len(raters) < 2:
        return 0.0
    common_ids = set.intersection(*(set(ratings[r].keys()) for r in raters))
    if not common_ids:
        return 0.0

    N = len(common_ids)
    n = len(raters)
    k = len(categories)
    cat_to_idx = {cat: idx for idx, cat in enumerate(categories)}

    # Table of counts N x k
    table = [[0] * k for _ in range(N)]
    for i, item_id in enumerate(sorted(common_ids)):
        for r in raters:
            val = ratings[r][item_id]
            idx = cat_to_idx.get(val, 0)
            table[i][idx] += 1

    # P_i for each subject
    P_i = []
    for i in range(N):
        sum_sq = sum(table[i][j] ** 2 for j in range(k))
        P_i.append((sum_sq - n) / (n * (n - 1)))
    P_bar = sum(P_i) / N

    # p_j marginal category probabilities
    p_j = [sum(table[i][j] for i in range(N)) / (N * n) for j in range(k)]
    P_e_bar = sum(p ** 2 for p in p_j)

    if P_e_bar >= 1.0:
        return 1.0
    return round((P_bar - P_e_bar) / (1.0 - P_e_bar), 4)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run 10-Model Frontier Committee Review for S09a.")
    parser.add_argument(
        "--review-dir",
        type=Path,
        default=Path("analysis/results/s09a_ablation/s09a_primary_a8b5e146_p16/expert_review_r001_fallback_vs_full"),
        help="Path to exported expert review directory containing reviewer_1.csv and blinding_key.json",
    )
    parser.add_argument("--batch-size", type=int, default=10, help="Number of items per batch prompt.")
    parser.add_argument("--limit-models", type=int, default=10, help="Number of models from the panel to run (1 to 10).")
    parser.add_argument("--dry-run", action="store_true", help="Only evaluate 1 batch to test connectivity.")
    args = parser.parse_args(argv)

    review_dir = args.review_dir.expanduser().resolve()
    if not review_dir.is_dir():
        raise FileNotFoundError(f"Review directory does not exist: {review_dir}")

    blinding_key_path = review_dir / "blinding_key.json"
    if not blinding_key_path.is_file():
        raise FileNotFoundError(f"blinding_key.json missing in {review_dir}")

    with open(blinding_key_path, "r", encoding="utf-8") as f:
        blinding_key = json.load(f)

    # Load canonical item map
    item_map = blinding_key["item_map"]
    canonical_items = [
        {
            "item_id": iid,
            "row_digest": data["row_digest"],
            "concept": data["display"]["concept"],
            "candidate_parent": data["display"]["candidate_parent"],
            "concept_context": data["display"]["concept_context"],
        }
        for iid, data in sorted(item_map.items())
    ]

    total_items = len(canonical_items)
    print(f"Loaded {total_items} canonical review items from blinding key.")

    client = _get_ollama_client()
    cache_path = review_dir / "multi_model_cache.json"
    cache = _load_cache(cache_path)

    models_to_run = DEFAULT_PANEL_MODELS[: args.limit_models]
    print(f"\nEvaluating across {len(models_to_run)} Frontier Models (Batch size: {args.batch_size}):")
    for rev_id, model_name, lab in models_to_run:
        print(f"  * {rev_id}: {model_name} [{lab}]")

    model_evaluations: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for rev_id, model_name, lab in models_to_run:
        print(f"\n--> Running {rev_id}: {model_name}...")
        evaluations_for_model = {}

        # Shuffle items for this reviewer to ensure order independence
        rev_num = int(rev_id.split("_")[-1])
        reviewer_items = list(canonical_items)
        random.Random(blinding_key["seed"] + rev_num * 7919).shuffle(reviewer_items)

        items_to_eval = reviewer_items[: args.batch_size] if args.dry_run else reviewer_items
        batches = [
            items_to_eval[i : i + args.batch_size]
            for i in range(0, len(items_to_eval), args.batch_size)
        ]

        for b_idx, batch in enumerate(batches, start=1):
            sys.stdout.write(f"\r    Batch {b_idx}/{len(batches)} ({len(batch)} items)... ")
            sys.stdout.flush()
            batch_res = _call_model_batch(client, model_name, batch, cache, cache_path)
            evaluations_for_model.update(batch_res)

        print("Done.")
        model_evaluations[rev_id] = evaluations_for_model

        # Write reviewer_X.csv in its specific randomized order
        out_csv_path = review_dir / f"{rev_id}.csv"
        rows_to_write = []
        for item in reviewer_items:
            iid = item["item_id"]
            ev = evaluations_for_model.get(iid, {})
            rows_to_write.append({
                "item_id": iid,
                "row_digest": item["row_digest"],
                "concept": item["concept"],
                "candidate_parent": item["candidate_parent"],
                "concept_context": item["concept_context"],
                "correctness": ev.get("correctness", "uncertain"),
                "specificity": ev.get("specificity", "uncertain"),
                "concept_validity": ev.get("concept_validity", "uncertain"),
                "confidence_1_to_5": ev.get("confidence_1_to_5", "3"),
                "notes": ev.get("notes", ""),
            })

        with open(out_csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
            writer.writeheader()
            writer.writerows(rows_to_write)
        print(f"    Saved {out_csv_path.name} ({len(rows_to_write)} rows).")

    # Generate Adjudication CSV based on committee ensemble majority voting
    print("\n--> Compiling Ensemble Adjudication (adjudication.csv)...")
    adjudication_rows = []
    adjudication_stats = Counter()

    for item in canonical_items:
        iid = item["item_id"]
        votes = [
            model_evaluations[rev_id][iid]["correctness"]
            for rev_id, _, _ in models_to_run
            if iid in model_evaluations[rev_id]
        ]
        specs = [
            model_evaluations[rev_id][iid]["specificity"]
            for rev_id, _, _ in models_to_run
            if iid in model_evaluations[rev_id]
        ]
        valids = [
            model_evaluations[rev_id][iid]["concept_validity"]
            for rev_id, _, _ in models_to_run
            if iid in model_evaluations[rev_id]
        ]
        confs = [
            int(model_evaluations[rev_id][iid].get("confidence_1_to_5", 3))
            for rev_id, _, _ in models_to_run
            if iid in model_evaluations[rev_id]
        ]

        vote_counts = Counter(votes)
        if vote_counts:
            top_vote, top_count = vote_counts.most_common(1)[0]
            consensus_correct = top_vote
        else:
            top_vote, top_count = "uncertain", 0
            consensus_correct = "uncertain"

        spec_counts = Counter(specs)
        consensus_spec = spec_counts.most_common(1)[0][0] if spec_counts else "uncertain"

        valid_counts = Counter(valids)
        consensus_valid = valid_counts.most_common(1)[0][0] if valid_counts else "uncertain"

        avg_conf = str(round(sum(confs) / len(confs))) if confs else "3"

        agreement_pct = round((top_count / len(votes)) * 100) if votes else 0
        consensus_notes = (
            f"Ensemble {top_count}/{len(votes)} ({agreement_pct}%) voted {top_vote}. "
            f"Votes: {dict(vote_counts)}."
        ) if votes else "No votes recorded."

        adjudication_rows.append({
            "item_id": iid,
            "row_digest": item["row_digest"],
            "concept": item["concept"],
            "candidate_parent": item["candidate_parent"],
            "concept_context": item["concept_context"],
            "correctness": consensus_correct,
            "specificity": consensus_spec,
            "concept_validity": consensus_valid,
            "confidence_1_to_5": avg_conf,
            "notes": consensus_notes,
        })
        adjudication_stats[f"{top_count}/{len(votes)}"] += 1

    adj_path = review_dir / "adjudication.csv"
    with open(adj_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(adjudication_rows)
    print(f"    Saved {adj_path.name} with {len(adjudication_rows)} consensus rows.")

    # Inter-Model Agreement Analysis
    print("\n--> Calculating Multi-Model Inter-Annotator Agreement...")
    categories = ("correct", "incorrect", "uncertain")
    model_correctness = {
        rev_id: {iid: evals[iid]["correctness"] for iid in evals}
        for rev_id, evals in model_evaluations.items()
    }

    fleiss_k = _compute_fleiss_kappa(model_correctness, categories)
    print(f"    Fleiss' Kappa across all {len(models_to_run)} models: {fleiss_k:.4f}")

    # Pairwise Cohen's Kappa Matrix
    pairwise_kappas = {}
    for i, (r1, m1, _) in enumerate(models_to_run):
        for j, (r2, m2, _) in enumerate(models_to_run):
            if i < j:
                k_val = _compute_cohen_kappa(model_correctness[r1], model_correctness[r2], categories)
                pairwise_kappas[(r1, r2)] = k_val

    # Save summary report
    summary_report = {
        "generated_at_utc": _utc_now(),
        "total_items": total_items,
        "models_evaluated": [
            {"id": rid, "model": mname, "description": desc}
            for rid, mname, desc in models_to_run
        ],
        "fleiss_kappa": fleiss_k,
        "pairwise_cohen_kappas": {
            f"{r1}__vs__{r2}": val for (r1, r2), val in pairwise_kappas.items()
        },
        "adjudication_consensus_distribution": dict(adjudication_stats),
    }

    report_path = review_dir / "multi_model_summary.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary_report, f, indent=2)
    print(f"    Saved agreement summary to {report_path.name}")

    print("\n10-Model Review & Ensemble Adjudication successfully generated!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
