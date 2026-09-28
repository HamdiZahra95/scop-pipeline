"""
Export a condition-blind paired parent-edge review from a completed S09a ablation.

Reviewers receive independently shuffled CSV files containing concept, candidate
parent, and frozen-input context. Condition names, original paths, movement actions,
and explicit pair identifiers remain hidden. The design is condition-blind but
pair-visible because a repeated concept can reveal competing candidate parents.
A separate blinding key maps item IDs back to conditions and must be withheld
until labels are complete.

Example:

    python analysis/v15_export_s09a_expert_review.py \
      --experiment analysis/results/s09a_ablation/s09a_primary_2026 \
      --changed 150 --unchanged 75 --reviewers 2
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
import common as PC

SCHEMA_VERSION = "s09a-expert-review-v2"
PROTOCOL_ID = "s09a-ablation-protocol-v1.6"
PROTOCOL_REQUEST_TIMEOUT_SECONDS = 200.0
PROTOCOL_MAX_OUTPUT_TOKENS = 8192
ALLOWED_CORRECTNESS = "correct | incorrect | uncertain"
ALLOWED_SPECIFICITY = "too_broad | appropriate | too_narrow | uncertain"
ALLOWED_VALIDITY = "valid | noise | uncertain"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    temporary.replace(path)


def _safe_csv_cell(value) -> str:
    """Prevent labels beginning with spreadsheet formula markers from executing."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _safe_csv_cell(row.get(field, "")) for field in fields})
    temporary.replace(path)


def _resolve_recorded_path(raw: str, experiment_root: Path) -> Path:
    path = Path(raw)
    if path.is_file():
        return path.resolve()
    candidate = (experiment_root / path).resolve()
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"recorded experiment file does not exist: {raw}")


def _verify_condition_output(record: dict, experiment_root: Path,
                             expected_condition: str | None = None) -> None:
    if not isinstance(record, dict):
        raise ValueError("condition-output record is not an object")
    if (expected_condition is not None
            and record.get("condition") != expected_condition):
        raise ValueError(
            f"condition-output identity mismatch: expected {expected_condition!r}, "
            f"recorded {record.get('condition')!r}"
        )
    artifact = _resolve_recorded_path(record.get("artifact", ""), experiment_root)
    ledger = _resolve_recorded_path(
        record.get("movement_ledger", ""), experiment_root
    )
    if artifact.stat().st_size != record.get("artifact_bytes"):
        raise ValueError(f"recorded artifact size changed: {artifact}")
    if _sha256(artifact) != record.get("artifact_sha256"):
        raise ValueError(f"recorded artifact hash changed: {artifact}")
    if _sha256(ledger) != record.get("movement_ledger_sha256"):
        raise ValueError(f"recorded movement-ledger hash changed: {ledger}")
    with open(ledger, "r", encoding="utf-8") as handle:
        rows = sum(1 for line in handle if line.strip())
    if rows != record.get("movement_rows"):
        raise ValueError(f"recorded movement-ledger row count changed: {ledger}")


def _replicate_manifest(experiment: dict, root: Path, replicate: int) -> dict:
    path = root / "replicates" / f"replicate_{replicate:03d}" / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"replicate manifest not found: {path}")
    manifest = _load_json(path)
    if manifest.get("status") != "complete":
        raise ValueError(f"replicate {replicate} is not complete")
    if manifest.get("replicate") != replicate:
        raise ValueError("replicate manifest identity differs from requested replicate")
    if manifest.get("schema_version") != experiment.get("schema_version"):
        raise ValueError("replicate schema differs from experiment manifest")
    if manifest.get("protocol_id") != experiment.get("protocol_id"):
        raise ValueError("replicate protocol differs from experiment manifest")
    if manifest.get("input_sha256") != experiment["input"]["sha256"]:
        raise ValueError("replicate input hash differs from experiment manifest")
    if manifest.get("source_sha256") != experiment.get("source_sha256"):
        raise ValueError("replicate source hashes differ from experiment manifest")
    if manifest.get("conditions") != experiment.get("conditions"):
        raise ValueError("replicate conditions differ from experiment manifest")
    expected_conditions = set(experiment.get("conditions", []))
    outputs = manifest.get("condition_outputs", {})
    if set(outputs) != expected_conditions:
        raise ValueError("replicate condition outputs do not match its design")
    for condition, record in outputs.items():
        _verify_condition_output(record, root, condition)
    return manifest


def _eligible_original(input_db: dict, left: dict, right: dict) -> list[str]:
    names = []
    for name, original in input_db.items():
        if name == "__meta__" or not isinstance(original, dict):
            continue
        if original.get("is_skeleton") or original.get("qa_bypassed"):
            continue
        if not isinstance(left.get(name), dict) or not isinstance(right.get(name), dict):
            continue
        if not left[name].get("taxonomy_parent") or not right[name].get("taxonomy_parent"):
            continue
        names.append(name)
    return sorted(names, key=lambda value: (PC.get_uri_name(value), value))


def _path_info(db: dict, concept: str) -> tuple[str, int]:
    domains = set(PC.TOP_LEVEL_DOMAINS)
    seen = set()
    current = concept
    depth = 0
    domain = "unreachable"
    while current and current != "owl:Thing" and current not in seen:
        seen.add(current)
        if current in domains:
            domain = current
            break
        data = db.get(current)
        if not isinstance(data, dict):
            break
        current = data.get("taxonomy_parent")
        depth += 1
    return domain, depth


def _depth_bucket(depth: int) -> str:
    if depth <= 2:
        return "shallow_0_2"
    if depth <= 5:
        return "middle_3_5"
    return "deep_6_plus"


def _simple_random_sample(items: list[dict], count: int,
                          seed: int) -> list[dict]:
    """Sample without replacement with equal probability for every item."""
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return list(items)
    selected = list(items)
    random.Random(seed).shuffle(selected)
    return selected[:count]


def _context(data: dict, limit: int) -> str:
    parts = []
    for key in ("definition", "description", "gloss", "context"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
        elif isinstance(value, list):
            text = "; ".join(str(item) for item in value[:3] if str(item).strip())
            if text:
                parts.append(f"{key}: {text}")
    annotations = data.get("literal_annotations") or []
    rendered = []
    for annotation in annotations[:5]:
        if isinstance(annotation, dict):
            prop = annotation.get("prop") or "relation"
            value = annotation.get("value")
            if value:
                rendered.append(f"{prop}: {value}")
        elif str(annotation).strip():
            rendered.append(str(annotation))
    if rendered:
        parts.append("corpus evidence: " + "; ".join(rendered))
    if not parts:
        parts.append(
            f"corpus frequency={data.get('f', 'unknown')}; "
            f"document frequency={data.get('td', 'unknown')}"
        )
    text = " | ".join(parts)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _ledger_actions(path: Path) -> dict[str, str]:
    return {
        row["concept"]: row.get("action", "unknown")
        for row in _load_jsonl(path)
        if row.get("original_node")
    }


def _display_digest(item_id: str, concept: str, candidate_parent: str,
                    concept_context: str) -> str:
    payload = json.dumps(
        {
            "item_id": item_id,
            "concept": concept,
            "candidate_parent": candidate_parent,
            "concept_context": concept_context,
        },
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_candidates(sample: list[dict], conditions: tuple[str, str],
                      input_db: dict, context_limit: int,
                      seed: int) -> tuple[list[dict], dict, dict]:
    # Collapse identical candidate edges across conditions. Reviewers judge an
    # edge once; the key maps that item back to both conditions.
    candidates: dict[tuple[str, str], dict] = {}
    concept_condition_key: dict[str, dict[str, tuple[str, str]]] = {}
    for concept_row in sample:
        concept = concept_row["concept"]
        concept_condition_key[concept] = {}
        for condition in conditions:
            parent = concept_row["parents"][condition]
            edge_key = (concept, parent)
            concept_condition_key[concept][condition] = edge_key
            candidates.setdefault(edge_key, {
                "concept": concept,
                "candidate_parent": parent,
                "concept_context": _context(input_db[concept], context_limit),
                "conditions": [],
            })["conditions"].append(condition)

    ordered = list(candidates.values())
    rng = random.Random(seed)
    rng.shuffle(ordered)
    item_map = {}
    edge_to_id = {}
    review_rows = []
    for index, candidate in enumerate(ordered, start=1):
        item_id = f"E{index:04d}"
        edge_key = (candidate["concept"], candidate["candidate_parent"])
        edge_to_id[edge_key] = item_id
        display = {
            "concept": _safe_csv_cell(candidate["concept"]),
            "candidate_parent": _safe_csv_cell(candidate["candidate_parent"]),
            "concept_context": _safe_csv_cell(candidate["concept_context"]),
        }
        row_digest = _display_digest(item_id, **display)
        item_map[item_id] = {
            "concept": candidate["concept"],
            "candidate_parent": candidate["candidate_parent"],
            "conditions": sorted(candidate["conditions"]),
            "display": display,
            "row_digest": row_digest,
        }
        review_rows.append({
            "item_id": item_id,
            "row_digest": row_digest,
            **display,
            "correctness": "",
            "specificity": "",
            "concept_validity": "",
            "confidence_1_to_5": "",
            "notes": "",
        })

    sample_map = {}
    for row in sample:
        concept = row["concept"]
        sample_map[concept] = {
            "changed": row["changed"],
            "stratum": row["stratum"],
            "condition_item_ids": {
                condition: edge_to_id[concept_condition_key[concept][condition]]
                for condition in conditions
            },
        }
    return review_rows, item_map, sample_map


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export condition-blind expert parent-edge review sheets."
    )
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--replicate", type=int)
    parser.add_argument(
        "--comparison", nargs=2, metavar=("CONTROL", "TREATMENT"),
        default=("fallback", "full"),
    )
    parser.add_argument("--changed", type=int, default=150)
    parser.add_argument("--unchanged", type=int, default=75)
    parser.add_argument(
        "--all-changed", action="store_true",
        help="Export every changed original concept instead of --changed.",
    )
    parser.add_argument("--reviewers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--context-limit", type=int, default=700)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.changed < 0 or args.unchanged < 0:
        parser.error("sample counts cannot be negative")
    if args.reviewers < 2:
        parser.error("at least two independent reviewers are required")
    if args.context_limit < 100:
        parser.error("--context-limit must be at least 100 characters")
    return args


def main(argv=None) -> int:
    args = _parse_args(argv)
    experiment_root = args.experiment.expanduser().resolve()
    experiment_path = experiment_root / "experiment.json"
    if not experiment_path.is_file():
        raise FileNotFoundError(f"experiment manifest not found: {experiment_path}")
    experiment = _load_json(experiment_path)
    if experiment.get("status") != "complete":
        raise ValueError("expert review requires a completed experiment manifest")
    if experiment.get("protocol_id") != PROTOCOL_ID:
        raise ValueError(
            f"expert review requires protocol {PROTOCOL_ID!r}; "
            f"experiment records {experiment.get('protocol_id')!r}"
        )
    recorded_timeout = experiment.get("tunables", {}).get(
        "request_timeout_seconds"
    )
    if recorded_timeout != PROTOCOL_REQUEST_TIMEOUT_SECONDS:
        raise ValueError(
            f"expert review requires the protocol-v1.3 request deadline "
            f"{PROTOCOL_REQUEST_TIMEOUT_SECONDS:g}s; experiment records "
            f"{recorded_timeout!r}"
        )
    recorded_max_tokens = experiment.get("tunables", {}).get(
        "max_output_tokens"
    )
    if recorded_max_tokens != PROTOCOL_MAX_OUTPUT_TOKENS:
        raise ValueError(
            f"expert review requires the protocol-v1.3 output cap "
            f"{PROTOCOL_MAX_OUTPUT_TOKENS}; experiment records "
            f"{recorded_max_tokens!r}"
        )
    requested_replicates = experiment.get("replicates")
    if type(requested_replicates) is not int or requested_replicates < 1:
        raise ValueError("experiment has an invalid replicate count")
    expected_status = {
        str(number): "complete"
        for number in range(1, requested_replicates + 1)
    }
    if experiment.get("replicate_status") != expected_status:
        raise ValueError("experiment does not record every replicate as complete")
    replicate_manifests = {
        number: _replicate_manifest(experiment, experiment_root, number)
        for number in range(1, requested_replicates + 1)
    }
    replicate = args.replicate or experiment.get("primary_replicate", 1)
    if replicate not in replicate_manifests:
        raise ValueError("requested review replicate is outside the experiment")
    replicate_manifest = replicate_manifests[replicate]
    control, treatment = tuple(args.comparison)
    if control == treatment:
        raise ValueError("control and treatment conditions must be distinct")
    available = replicate_manifest.get("condition_outputs", {})
    if control not in available or treatment not in available:
        raise ValueError(
            f"replicate lacks comparison {control!r} versus {treatment!r}; "
            f"available={sorted(available)}"
        )

    input_path = _resolve_recorded_path(
        experiment["input"]["path"], experiment_root
    )
    if input_path.stat().st_size != experiment["input"].get("bytes"):
        raise ValueError("frozen input size no longer matches the experiment manifest")
    if _sha256(input_path) != experiment["input"]["sha256"]:
        raise ValueError("frozen input no longer matches the recorded SHA-256")
    input_db = _load_json(input_path)
    condition_dbs = {
        condition: _load_json(_resolve_recorded_path(
            available[condition]["artifact"], experiment_root
        ))
        for condition in (control, treatment)
    }
    treatment_ledger = _resolve_recorded_path(
        available[treatment]["movement_ledger"], experiment_root
    )
    actions = _ledger_actions(treatment_ledger)

    rows = []
    for concept in _eligible_original(
        input_db, condition_dbs[control], condition_dbs[treatment]
    ):
        parents = {
            control: condition_dbs[control][concept]["taxonomy_parent"],
            treatment: condition_dbs[treatment][concept]["taxonomy_parent"],
        }
        domain, depth = _path_info(condition_dbs[treatment], concept)
        action = actions.get(concept, "unchanged")
        rows.append({
            "concept": concept,
            "parents": parents,
            "changed": parents[control] != parents[treatment],
            "stratum": {
                "domain": domain,
                "depth_bucket": _depth_bucket(depth),
                "treatment_action": action,
            },
        })
    changed = [row for row in rows if row["changed"]]
    unchanged = [row for row in rows if not row["changed"]]
    review_changed_census = args.all_changed or len(changed) <= 250
    changed_count = (
        len(changed) if review_changed_census
        else min(args.changed, len(changed))
    )
    selected_changed = _simple_random_sample(
        changed, changed_count, seed=args.seed
    )
    selected_unchanged = _simple_random_sample(
        unchanged, min(args.unchanged, len(unchanged)),
        seed=args.seed + 1009,
    )
    sample = selected_changed + selected_unchanged
    if not selected_changed:
        raise ValueError(
            "comparison contains no sampled changed parent edges; there is no "
            "repair/regression contrast to review"
        )

    output_dir = (
        args.output.expanduser().resolve() if args.output else
        experiment_root / f"expert_review_r{replicate:03d}_{control}_vs_{treatment}"
    )
    if output_dir.exists():
        raise FileExistsError(
            f"review directory already exists: {output_dir}. Choose --output; "
            "nothing was overwritten."
        )
    output_dir.mkdir(parents=True)

    review_rows, item_map, sample_map = _build_candidates(
        sample, (control, treatment), input_db, args.context_limit, args.seed
    )
    fields = [
        "item_id", "row_digest", "concept", "candidate_parent",
        "concept_context", "correctness", "specificity", "concept_validity",
        "confidence_1_to_5", "notes",
    ]
    reviewer_files = []
    for reviewer in range(1, args.reviewers + 1):
        reviewer_rows = list(review_rows)
        random.Random(args.seed + reviewer * 7919).shuffle(reviewer_rows)
        path = output_dir / f"reviewer_{reviewer}.csv"
        _write_csv(path, reviewer_rows, fields)
        reviewer_files.append({
            "reviewer": reviewer,
            "path": str(path),
            "sha256_at_export": _sha256(path),
            "rows": len(reviewer_rows),
        })
    adjudication_path = output_dir / "adjudication.csv"
    _write_csv(adjudication_path, review_rows, fields)

    key = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "created_at_utc": _utc_now(),
        "experiment_manifest": str(experiment_path),
        "experiment_manifest_sha256": _sha256(experiment_path),
        "experiment_id": experiment.get("experiment_id"),
        "input_sha256": experiment["input"]["sha256"],
        "replicate": replicate,
        "comparison": {"control": control, "treatment": treatment},
        "condition_outputs": {
            control: available[control],
            treatment: available[treatment],
        },
        "seed": args.seed,
        "review_configuration": {
            "reviewers": args.reviewers,
            "context_limit": args.context_limit,
            "condition_blind": True,
            "pair_visible": True,
        },
        "source_sha256": {"review_exporter": _sha256(Path(__file__).resolve())},
        "sampling": {
            "eligible_original_concepts": len(rows),
            "available_changed": len(changed),
            "available_unchanged": len(unchanged),
            "sampled_changed": len(selected_changed),
            "sampled_unchanged": len(selected_unchanged),
            "changed_scheme": (
                "census (automatic protocol threshold: population <=250)"
                if len(changed) <= 250 else
                "census (explicit complete-population review above threshold)"
                if args.all_changed else
                "simple random sample without replacement"
            ),
            "changed_inclusion_probability": (
                round(len(selected_changed) / len(changed), 8) if changed else 0.0
            ),
            "unchanged_scheme": "simple random sample without replacement",
            "unchanged_inclusion_probability": (
                round(len(selected_unchanged) / len(unchanged), 8)
                if unchanged else 0.0
            ),
        },
        "item_map": item_map,
        "sample_concepts": sample_map,
        "reviewer_files": reviewer_files,
        "blank_adjudication_file": str(adjudication_path),
        "instructions": {
            "correctness": ALLOWED_CORRECTNESS,
            "specificity": ALLOWED_SPECIFICITY,
            "concept_validity": ALLOWED_VALIDITY,
            "confidence": "integer 1..5",
            "blinding": (
                "Do not give this key or condition information to reviewers "
                "until both CSV files are complete and locked."
            ),
        },
    }
    key_path = output_dir / "blinding_key.json"
    _write_json(key_path, key)

    instructions = f"""# S09a parent-edge expert review

Judge every row independently. Do not infer or request which experimental condition
produced an edge. The competing edge may appear elsewhere in a different order.

## Labels

- **correctness:** `{ALLOWED_CORRECTNESS}`. Select `correct` only when the concept
  is genuinely a kind/subclass of the candidate parent; related-to, used-by,
  part-of, and instance-of are incorrect.
- **specificity:** `{ALLOWED_SPECIFICITY}`.
- **concept_validity:** `{ALLOWED_VALIDITY}`.
- **confidence_1_to_5:** 1 (low) through 5 (high).

Do not edit `item_id`, `row_digest`, `concept`, `candidate_parent`, or
`concept_context`. The design is condition-blind: both competing parents may be
recognisable because the same concept can appear twice, so judge every edge
independently and do not try to infer condition identity. Complete the file
independently before discussing disagreements. The researcher must withhold
`blinding_key.json` until both reviews are locked.
"""
    (output_dir / "REVIEW_INSTRUCTIONS.md").write_text(instructions, encoding="utf-8")
    summary = {
        "review_directory": str(output_dir),
        "blinding_key": str(key_path),
        "reviewers": args.reviewers,
        "review_items_per_reviewer": len(review_rows),
        "sampled_concepts": len(sample),
        "changed_concepts": len(selected_changed),
        "unchanged_negative_controls": len(selected_unchanged),
        "comparison": key["comparison"],
    }
    _write_json(output_dir / "export_summary.json", summary)
    print(json.dumps(summary, indent=2))
    print("Keep blinding_key.json separate from reviewers until labels are locked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
