"""
Score a blinded paired S09a parent-edge expert review.

The scorer reports inter-reviewer agreement before adjudication, resolves labels
from reviewer agreement plus an optional adjudication file, and evaluates the
same concepts under control and treatment. Primary outputs are paired correctness
rates, risk difference with a concept bootstrap interval, repaired/regressed
McNemar discordances, repair precision, and regression rate.

A separate adjudication file is required for final inference. Without one, the
effect estimate is explicitly provisional; unresolved reviewer disagreements are
also marked uncertain. Resolved review evidence receives headline-ready status
only when the frozen primary input, run, comparison, sampling, and scoring
settings also match the prespecified protocol.

Example:

    python analysis/v16_score_s09a_expert_review.py \
      --key .../blinding_key.json \
      --labels .../reviewer_1.csv .../reviewer_2.csv \
      --adjudicated .../adjudication.csv \
      --bootstrap 10000
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "s09a-expert-score-v2"
REVIEW_SCHEMA_VERSION = "s09a-expert-review-v2"
PROTOCOL_ID = "s09a-ablation-protocol-v1.6"
PROTOCOL_REQUEST_TIMEOUT_SECONDS = 200.0
PROTOCOL_MAX_OUTPUT_TOKENS = 8192
PRIMARY_INPUT_SHA256 = (
    "a8b5e146ae00f586ed01a39cda7cde76e58e993eefcfecc66ddf419b7e744c4e"
)
PRIMARY_CONDITIONS = ("fallback", "phase1", "full")
CORRECTNESS = {"correct", "incorrect", "uncertain"}
SPECIFICITY = {"too_broad", "appropriate", "too_narrow", "uncertain"}
VALIDITY = {"valid", "noise", "uncertain"}


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


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    temporary.replace(path)


def _resolve_recorded_path(raw: str, base: Path) -> Path:
    path = Path(raw)
    if path.is_file():
        return path.resolve()
    candidate = (base / path).resolve()
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"recorded evidence file does not exist: {raw}")


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
    artifact = _resolve_recorded_path(
        record.get("artifact", ""), experiment_root
    )
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


def _verified_replicate_manifest(experiment: dict, experiment_root: Path,
                                 replicate: int) -> dict:
    path = (
        experiment_root / "replicates" / f"replicate_{replicate:03d}"
        / "manifest.json"
    )
    if not path.is_file():
        raise FileNotFoundError(f"recorded replicate manifest is missing: {path}")
    manifest = _load_json(path)
    if (manifest.get("status") != "complete"
            or manifest.get("replicate") != replicate
            or manifest.get("schema_version")
            != experiment.get("schema_version")
            or manifest.get("protocol_id")
            != experiment.get("protocol_id")
            or manifest.get("input_sha256")
            != experiment["input"]["sha256"]
            or manifest.get("source_sha256")
            != experiment.get("source_sha256")
            or manifest.get("conditions")
            != experiment.get("conditions")):
        raise ValueError(
            f"replicate {replicate} manifest differs from the completed experiment"
        )
    outputs = manifest.get("condition_outputs", {})
    if set(outputs) != set(experiment.get("conditions", [])):
        raise ValueError(
            f"replicate {replicate} condition outputs do not match its design"
        )
    for condition, record in outputs.items():
        _verify_condition_output(record, experiment_root, condition)
    return manifest


def _normalise(value: str) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


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


def _load_labels(path: Path, expected_items: dict[str, dict], *,
                 require_complete: bool) -> dict[str, dict]:
    labels = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "item_id", "row_digest", "concept", "candidate_parent",
            "concept_context", "correctness",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path} lacks required columns {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            item_id = (row.get("item_id") or "").strip()
            if not item_id:
                continue
            if item_id in labels:
                raise ValueError(f"duplicate item_id {item_id!r} in {path}:{line_number}")
            if item_id not in expected_items:
                raise ValueError(f"unknown item_id {item_id!r} in {path}:{line_number}")
            expected = expected_items[item_id]
            display = expected.get("display")
            expected_digest = expected.get("row_digest")
            if not isinstance(display, dict) or not expected_digest:
                raise ValueError(
                    "blinding key lacks immutable display-row identities; "
                    "re-export review sheets with the current exporter"
                )
            observed_display = {
                "concept": row.get("concept", ""),
                "candidate_parent": row.get("candidate_parent", ""),
                "concept_context": row.get("concept_context", ""),
            }
            observed_digest = (row.get("row_digest") or "").strip()
            recomputed = _display_digest(item_id, **observed_display)
            if observed_display != display:
                raise ValueError(
                    f"immutable edge fields changed for {item_id} in {path}:{line_number}"
                )
            if observed_digest != expected_digest or recomputed != expected_digest:
                raise ValueError(
                    f"row digest mismatch for {item_id} in {path}:{line_number}"
                )
            correctness = _normalise(row.get("correctness", ""))
            specificity = _normalise(row.get("specificity", ""))
            validity = _normalise(row.get("concept_validity", ""))
            if correctness and correctness not in CORRECTNESS:
                raise ValueError(
                    f"invalid correctness {correctness!r} in {path}:{line_number}"
                )
            if specificity and specificity not in SPECIFICITY:
                raise ValueError(
                    f"invalid specificity {specificity!r} in {path}:{line_number}"
                )
            if validity and validity not in VALIDITY:
                raise ValueError(
                    f"invalid concept_validity {validity!r} in {path}:{line_number}"
                )
            confidence = (row.get("confidence_1_to_5") or "").strip()
            if confidence and confidence not in {"1", "2", "3", "4", "5"}:
                raise ValueError(
                    f"invalid confidence {confidence!r} in {path}:{line_number}"
                )
            labels[item_id] = {
                "correctness": correctness or None,
                "specificity": specificity or None,
                "concept_validity": validity or None,
                "confidence_1_to_5": confidence,
                "notes": (row.get("notes") or "").strip(),
            }
    if require_complete:
        missing_rows = sorted(set(expected_items) - set(labels))
        incomplete = sorted(
            item_id for item_id, row in labels.items()
            if not row["correctness"] or not row["specificity"]
            or not row["concept_validity"] or not row["confidence_1_to_5"]
        )
        if missing_rows or incomplete:
            raise ValueError(
                f"review file {path} is incomplete: missing_rows={missing_rows[:5]}, "
                f"incomplete_rows={incomplete[:5]}"
            )
    return labels


def _cohen_kappa(left: dict[str, dict], right: dict[str, dict], field: str,
                  categories: set[str]) -> dict:
    ids = sorted(
        item_id for item_id in set(left) & set(right)
        if left[item_id].get(field) in categories
        and right[item_id].get(field) in categories
    )
    if not ids:
        return {"n": 0, "raw_agreement": None, "kappa": None}
    left_values = [left[item_id][field] for item_id in ids]
    right_values = [right[item_id][field] for item_id in ids]
    observed = sum(a == b for a, b in zip(left_values, right_values)) / len(ids)
    left_counts = Counter(left_values)
    right_counts = Counter(right_values)
    expected = sum(
        (left_counts[category] / len(ids)) * (right_counts[category] / len(ids))
        for category in categories
    )
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "n": len(ids),
        "raw_agreement": round(observed, 4),
        "kappa": round(kappa, 4),
        "left_distribution": dict(left_counts),
        "right_distribution": dict(right_counts),
    }


def _fleiss_kappa(reviewers: list[dict[str, dict]], field: str, categories: set[str]) -> dict:
    """Compute Fleiss' Kappa across N raters on common items."""
    valid_ids = sorted(
        item_id for item_id in set.intersection(*(set(r) for r in reviewers))
        if all(r[item_id].get(field) in categories for r in reviewers)
    )
    if not valid_ids:
        return {"n": 0, "raters": len(reviewers), "kappa": None}

    N = len(valid_ids)
    n = len(reviewers)
    ordered_cats = sorted(categories)
    k = len(ordered_cats)
    cat_to_idx = {c: idx for idx, c in enumerate(ordered_cats)}

    table = [[0] * k for _ in range(N)]
    for i, item_id in enumerate(valid_ids):
        for r in reviewers:
            c = r[item_id].get(field)
            if c in cat_to_idx:
                table[i][cat_to_idx[c]] += 1

    P_i = []
    for i in range(N):
        sum_sq = sum(table[i][j] ** 2 for j in range(k))
        P_i.append((sum_sq - n) / (n * (n - 1)))
    P_bar = sum(P_i) / N

    p_j = [sum(table[i][j] for i in range(N)) / (N * n) for j in range(k)]
    P_e_bar = sum(p ** 2 for p in p_j)

    kappa = (P_bar - P_e_bar) / (1.0 - P_e_bar) if P_e_bar < 1.0 else 1.0
    return {
        "n": N,
        "raters": n,
        "kappa": round(kappa, 4),
        "mean_P": round(P_bar, 4),
        "P_e": round(P_e_bar, 4),
    }


def _resolve_item_labels(item_ids: set[str], reviewers: list[dict[str, dict]],
                         adjudicated: dict[str, dict] | None) -> tuple[dict, dict]:
    """Resolve only complete independent labels; adjudication cannot replace them."""
    resolved = {}
    stats = Counter()
    for item_id in sorted(item_ids):
        reviewer_values = [
            labels[item_id]["correctness"] for labels in reviewers
        ]
        if any(value is None for value in reviewer_values):
            raise ValueError(f"reviewer label missing for {item_id}")
        adjudicated_value = (
            adjudicated.get(item_id, {}).get("correctness")
            if adjudicated else None
        )
        if len(set(reviewer_values)) == 1:
            value = reviewer_values[0]
            source = "reviewer_agreement"
            if adjudicated_value and adjudicated_value != value:
                raise ValueError(
                    f"adjudication for {item_id} contradicts unanimous reviewers"
                )
        elif adjudicated_value:
            value = adjudicated_value
            source = "adjudicated_disagreement"
        else:
            value = "uncertain"
            source = "unadjudicated_disagreement"
        resolved[item_id] = {
            "correctness": value,
            "source": source,
            "reviewer_values": reviewer_values,
        }
        stats[source] += 1
    return resolved, dict(stats)


def _binary(label: str | None, uncertain_policy: str) -> int | None:
    if label == "correct":
        return 1
    if label == "incorrect":
        return 0
    if label == "uncertain" and uncertain_policy == "incorrect":
        return 0
    return None


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(quantile * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _paired_bootstrap(differences: list[int], iterations: int,
                      seed: int) -> list[float]:
    if not differences:
        return []
    rng = random.Random(seed)
    count = len(differences)
    values = []
    for _ in range(iterations):
        values.append(
            sum(differences[rng.randrange(count)] for _ in range(count)) / count
        )
    return values


def _exact_binomial_two_sided(successes: int, trials: int) -> float:
    if trials == 0:
        return 1.0
    probabilities = [math.comb(trials, i) * (0.5 ** trials) for i in range(trials + 1)]
    observed = probabilities[successes]
    return min(1.0, sum(value for value in probabilities if value <= observed + 1e-15))


def _paired_summary(rows: list[dict], iterations: int, seed: int) -> dict:
    if not rows:
        return {
            "n": 0,
            "control_correct_rate": None,
            "treatment_correct_rate": None,
            "risk_difference": None,
            "risk_difference_ci95": [None, None],
            "repairs": 0,
            "regressions": 0,
            "discordant": 0,
            "mcnemar_exact_p": 1.0,
            "repair_precision": None,
            "regression_rate": None,
            "joint_positive_result": False,
        }
    control = [row["control_binary"] for row in rows]
    treatment = [row["treatment_binary"] for row in rows]
    differences = [b - a for a, b in zip(control, treatment)]
    repairs = sum(a == 0 and b == 1 for a, b in zip(control, treatment))
    regressions = sum(a == 1 and b == 0 for a, b in zip(control, treatment))
    discordant = repairs + regressions
    bootstrap = _paired_bootstrap(differences, iterations, seed)
    lower = _percentile(bootstrap, 0.025)
    upper = _percentile(bootstrap, 0.975)
    p_value = _exact_binomial_two_sided(min(repairs, regressions), discordant)
    n = len(rows)
    risk_difference = sum(differences) / n
    return {
        "n": n,
        "control_correct": sum(control),
        "treatment_correct": sum(treatment),
        "control_correct_rate": round(sum(control) / n, 4),
        "treatment_correct_rate": round(sum(treatment) / n, 4),
        "risk_difference": round(risk_difference, 4),
        "risk_difference_ci95": [round(lower, 4), round(upper, 4)],
        "repairs": repairs,
        "regressions": regressions,
        "discordant": discordant,
        "mcnemar_exact_p": round(p_value, 6),
        "repair_precision": round(repairs / n, 4),
        "regression_rate": round(regressions / n, 4),
        "net_repairs": repairs - regressions,
        "joint_positive_result": bool(lower > 0 and p_value < 0.05),
        "decision_rule": "CI lower bound > 0 and exact McNemar p < .05",
    }


def _concept_rows(key: dict, resolved: dict, uncertain_policy: str) -> tuple[list, dict]:
    comparison = key["comparison"]
    control = comparison["control"]
    treatment = comparison["treatment"]
    item_map = key["item_map"]
    rows = []
    excluded = Counter()
    for concept, sample in sorted(key["sample_concepts"].items()):
        ids = sample["condition_item_ids"]
        control_id = ids[control]
        treatment_id = ids[treatment]
        control_label = resolved.get(control_id, {}).get("correctness")
        treatment_label = resolved.get(treatment_id, {}).get("correctness")
        control_binary = _binary(control_label, uncertain_policy)
        treatment_binary = _binary(treatment_label, uncertain_policy)
        row = {
            "concept": concept,
            "changed": bool(sample["changed"]),
            "stratum": sample.get("stratum", {}),
            "control_condition": control,
            "control_item_id": control_id,
            "control_parent": item_map[control_id]["candidate_parent"],
            "control_label": control_label,
            "control_source": resolved.get(control_id, {}).get("source"),
            "control_binary": control_binary,
            "treatment_condition": treatment,
            "treatment_item_id": treatment_id,
            "treatment_parent": item_map[treatment_id]["candidate_parent"],
            "treatment_label": treatment_label,
            "treatment_source": resolved.get(treatment_id, {}).get("source"),
            "treatment_binary": treatment_binary,
        }
        if control_binary is None or treatment_binary is None:
            if control_label is None or treatment_label is None:
                excluded["missing"] += 1
            else:
                excluded["uncertain_excluded"] += 1
            row["included"] = False
        else:
            row["included"] = True
            row["outcome"] = (
                "repair" if control_binary == 0 and treatment_binary == 1
                else "regression" if control_binary == 1 and treatment_binary == 0
                else "both_correct" if control_binary == treatment_binary == 1
                else "both_incorrect"
            )
        rows.append(row)
    return rows, dict(excluded)


def _write_concept_csv(path: Path, rows: Iterable[dict]) -> None:
    fields = [
        "concept", "changed", "included", "outcome",
        "control_condition", "control_item_id", "control_parent",
        "control_label", "control_source", "control_binary",
        "treatment_condition", "treatment_item_id", "treatment_parent",
        "treatment_label", "treatment_source", "treatment_binary",
        "stratum",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            serializable = dict(row)
            serializable["stratum"] = json.dumps(row.get("stratum", {}), sort_keys=True)
            writer.writerow({field: serializable.get(field, "") for field in fields})
    temporary.replace(path)


def _protocol_compliance(key: dict, experiment: dict, *,
                         uncertain_policy: str, bootstrap_iterations: int,
                         bootstrap_seed: int) -> dict:
    """Evaluate the frozen primary-analysis contract independently of review state."""
    sampling = key.get("sampling", {})
    review_configuration = key.get("review_configuration", {})
    sample_concepts = key.get("sample_concepts", {})
    available_changed = sampling.get("available_changed")
    available_unchanged = sampling.get("available_unchanged")
    sampled_changed = sampling.get("sampled_changed")
    sampled_unchanged = sampling.get("sampled_unchanged")

    changed_counts_valid = all(
        type(value) is int and value >= 0
        for value in (available_changed, sampled_changed)
    )
    changed_sampling_valid = False
    if changed_counts_valid and available_changed > 0:
        expected_probability = round(sampled_changed / available_changed, 8)
        probability_matches = (
            sampling.get("changed_inclusion_probability") == expected_probability
        )
        if available_changed <= 250:
            changed_sampling_valid = bool(
                sampled_changed == available_changed
                and str(sampling.get("changed_scheme", "")).startswith("census")
                and probability_matches
            )
        else:
            default_sample = bool(
                sampled_changed == 150
                and sampling.get("changed_scheme")
                == "simple random sample without replacement"
            )
            complete_census = bool(
                sampled_changed == available_changed
                and str(sampling.get("changed_scheme", "")).startswith("census")
            )
            changed_sampling_valid = bool(
                (default_sample or complete_census) and probability_matches
            )

    unchanged_counts_valid = all(
        type(value) is int and value >= 0
        for value in (available_unchanged, sampled_unchanged)
    )
    unchanged_sampling_valid = False
    if unchanged_counts_valid:
        expected_unchanged = min(75, available_unchanged)
        expected_probability = (
            round(expected_unchanged / available_unchanged, 8)
            if available_unchanged else 0.0
        )
        unchanged_sampling_valid = bool(
            sampled_unchanged == expected_unchanged
            and sampling.get("unchanged_scheme")
            == "simple random sample without replacement"
            and sampling.get("unchanged_inclusion_probability")
            == expected_probability
        )

    sample_rows = (
        list(sample_concepts.values())
        if isinstance(sample_concepts, dict) else []
    )
    observed_changed = sum(
        bool(row.get("changed"))
        for row in sample_rows if isinstance(row, dict)
    )
    observed_unchanged = sum(
        not bool(row.get("changed"))
        for row in sample_rows if isinstance(row, dict)
    )
    sample_metadata_matches = False
    if (isinstance(sample_concepts, dict)
            and changed_counts_valid and unchanged_counts_valid):
        sample_metadata_matches = bool(
            sampled_changed == observed_changed
            and sampled_unchanged == observed_unchanged
            and sampling.get("eligible_original_concepts")
            == available_changed + available_unchanged
        )

    comparison = key.get("comparison", {})
    reviewers = key.get("reviewer_files", [])
    expected_replicate_status = {
        str(number): "complete" for number in range(1, 6)
    }
    checks = {
        "protocol_identity": (
            key.get("protocol_id") == PROTOCOL_ID
            and experiment.get("protocol_id") == PROTOCOL_ID
        ),
        "primary_frozen_input": (
            key.get("input_sha256") == PRIMARY_INPUT_SHA256
            and experiment.get("input", {}).get("sha256") == PRIMARY_INPUT_SHA256
        ),
        "three_condition_design": (
            tuple(experiment.get("conditions", [])) == PRIMARY_CONDITIONS
        ),
        "five_isolated_replicates": (
            experiment.get("replicates") == 5
            and experiment.get("replicate_status")
            == expected_replicate_status
            and experiment.get("design", {}).get(
                "physically_isolated_cache_per_replicate"
            ) is True
        ),
        "designated_primary_replicate": (
            experiment.get("primary_replicate") == 1
            and key.get("replicate") == 1
        ),
        "runner_seed_42": experiment.get("seed") == 42,
        "initial_temperature_zero": experiment.get("initial_temperature") == 0,
        "request_timeout_200_seconds": (
            experiment.get("tunables", {}).get("request_timeout_seconds")
            == PROTOCOL_REQUEST_TIMEOUT_SECONDS
        ),
        "max_output_tokens_8192": (
            experiment.get("tunables", {}).get("max_output_tokens")
            == PROTOCOL_MAX_OUTPUT_TOKENS
        ),
        "primary_fallback_full_comparison": comparison == {
            "control": "fallback", "treatment": "full"
        },
        "review_seed_2026": key.get("seed") == 2026,
        "condition_blind_pair_visible_review": (
            review_configuration.get("condition_blind") is True
            and review_configuration.get("pair_visible") is True
        ),
        "at_least_two_exported_reviewers": (
            type(review_configuration.get("reviewers")) is int
            and review_configuration["reviewers"] >= 2
            and isinstance(reviewers, list)
            and len(reviewers) >= 2
        ),
        "changed_sampling_rule": changed_sampling_valid,
        "unchanged_control_sampling_rule": unchanged_sampling_valid,
        "sample_metadata_matches": sample_metadata_matches,
        "uncertain_mapped_to_incorrect": uncertain_policy == "incorrect",
        "bootstrap_10000": bootstrap_iterations == 10000,
        "bootstrap_seed_42": bootstrap_seed == 42,
    }
    deviations = [name for name, passed in checks.items() if not passed]
    return {
        "protocol_id": PROTOCOL_ID,
        "compliant": not deviations,
        "checks": checks,
        "deviations": deviations,
    }


def _render_markdown(result: dict) -> str:
    agreement = result["inter_reviewer_agreement"]["correctness"]
    primary = result["paired_results"]["changed_parent_concepts"]
    secondary = result["paired_results"]["all_sampled_concepts"]
    status_labels = {
        "final_preregistered_headline": "final preregistered headline analysis",
        "resolved_exploratory_or_sensitivity": (
            "resolved exploratory/sensitivity analysis"
        ),
        "provisional_review": "provisional review analysis",
    }
    status = status_labels[result["analysis_status"]]
    deviations = result["protocol_compliance"]["deviations"]
    lines = [
        "# S09a expert parent-edge evaluation",
        "",
        f"**Status:** {status}",
        f"**Comparison:** `{result['comparison']['control']}` → "
        f"`{result['comparison']['treatment']}`",
        f"**Uncertain policy:** `{result['uncertain_policy']}`",
        f"**Review ready:** `{result['review_ready']}`",
        f"**Primary protocol compliant:** "
        f"`{result['protocol_compliance']['compliant']}`",
        f"**Headline inference ready:** `{result['headline_inference_ready']}`",
    ]
    if deviations:
        lines.append("**Protocol deviations:** " + ", ".join(deviations))
    lines.extend([
        "",
        "## Inter-reviewer agreement before adjudication",
        "",
        f"- correctness rows: {agreement['n']}",
        f"- raw agreement: {agreement['raw_agreement']}",
        f"- Cohen's kappa: {agreement['kappa']}",
    ])
    if "fleiss_kappa" in agreement:
        lines.append(f"- Fleiss' kappa ({agreement.get('raters', len(result['reviewer_files']))} raters): {agreement['fleiss_kappa']}")
    if "mean_pairwise_kappa" in agreement:
        lines.append(f"- Mean pairwise Cohen's kappa: {agreement['mean_pairwise_kappa']}")
    lines.extend([
        "",
        "## Paired results",
        "",
        "| population | n | control correct | treatment correct | risk difference (95% CI) | repairs | regressions | exact McNemar p | joint rule |",
        "|---|---:|---:|---:|---|---:|---:|---:|---|",
    ])
    for label, block in (("changed parents (primary estimand)", primary),
                         ("all sampled (secondary)", secondary)):
        lines.append(
            f"| {label} | {block['n']} | {block['control_correct_rate']} | "
            f"{block['treatment_correct_rate']} | {block['risk_difference']} "
            f"{block['risk_difference_ci95']} | {block['repairs']} | "
            f"{block['regressions']} | {block['mcnemar_exact_p']} | "
            f"{block['joint_positive_result']} |"
        )
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        result["interpretation"],
        "",
        result["scope"],
        "",
        "A positive headline result requires protocol/review readiness, a "
        "confidence interval above zero, and exact McNemar `p < .05`. A null "
        "result is not evidence of equivalence.",
        "",
    ])
    return "\n".join(lines)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Score paired blinded S09a parent-edge labels."
    )
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--labels", type=Path, nargs="+", required=True,
                        metavar="REVIEWER_FILE",
                        help="Two or more reviewer label CSV files.")
    parser.add_argument("--adjudicated", type=Path)
    parser.add_argument(
        "--uncertain-policy", choices=("incorrect", "exclude"),
        default="incorrect",
    )
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.bootstrap < 100:
        parser.error("--bootstrap must be at least 100")
    return args


def main(argv=None) -> int:
    args = _parse_args(argv)
    key_path = args.key.expanduser().resolve()
    key = _load_json(key_path)
    if key.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError(f"unsupported blinding-key schema: {key.get('schema_version')}")
    experiment_manifest = _resolve_recorded_path(
        key["experiment_manifest"], key_path.parent
    )
    if _sha256(experiment_manifest) != key["experiment_manifest_sha256"]:
        raise ValueError("experiment manifest changed after review export")
    experiment_root = experiment_manifest.parent
    experiment = _load_json(experiment_manifest)
    if experiment.get("status") != "complete":
        raise ValueError("recorded experiment is no longer complete")
    if experiment.get("experiment_id") != key.get("experiment_id"):
        raise ValueError("experiment identity differs from the blinding key")
    if experiment.get("input", {}).get("sha256") != key.get("input_sha256"):
        raise ValueError("experiment input identity differs from the blinding key")
    input_path = _resolve_recorded_path(
        experiment["input"]["path"], experiment_root
    )
    if input_path.stat().st_size != experiment["input"].get("bytes"):
        raise ValueError("frozen input size changed after review export")
    if _sha256(input_path) != experiment["input"]["sha256"]:
        raise ValueError("frozen input hash changed after review export")

    requested_replicates = experiment.get("replicates")
    if (type(requested_replicates) is not int
            or requested_replicates < 1):
        raise ValueError("experiment has an invalid replicate count")
    expected_status = {
        str(number): "complete"
        for number in range(1, requested_replicates + 1)
    }
    if experiment.get("replicate_status") != expected_status:
        raise ValueError("experiment does not record every replicate as complete")
    verified_replicates = {
        number: _verified_replicate_manifest(
            experiment, experiment_root, number
        )
        for number in range(1, requested_replicates + 1)
    }

    replicate = key.get("replicate")
    if (not isinstance(replicate, int) or isinstance(replicate, bool)
            or replicate not in verified_replicates):
        raise ValueError("blinding key has an invalid replicate identity")
    replicate_manifest = verified_replicates[replicate]
    manifest_outputs = replicate_manifest["condition_outputs"]

    comparison = key.get("comparison", {})
    if set(comparison) != {"control", "treatment"}:
        raise ValueError("blinding key has an invalid comparison")
    if comparison["control"] == comparison["treatment"]:
        raise ValueError("control and treatment conditions must be distinct")
    recorded_outputs = key.get("condition_outputs", {})
    expected_conditions = set(comparison.values())
    if set(recorded_outputs) != expected_conditions:
        raise ValueError("blinding key lacks authenticated comparison outputs")
    for condition, record in recorded_outputs.items():
        if manifest_outputs.get(condition) != record:
            raise ValueError(
                f"blinding-key output for {condition!r} differs from its replicate"
            )
        _verify_condition_output(record, experiment_root, condition)

    expected_items = key["item_map"]
    if not isinstance(expected_items, dict) or not expected_items:
        raise ValueError("blinding key has no review-item identities")
    expected_ids = set(expected_items)
    label_paths = [path.expanduser().resolve() for path in args.labels]
    if len(label_paths) < 2:
        raise ValueError("at least two reviewer label files must be provided")
    if not all(path.is_file() for path in label_paths):
        raise FileNotFoundError("all reviewer label files must exist")
    if len(set(label_paths)) != len(label_paths):
        raise ValueError("reviewer inputs must all be distinct files")
    hashes = [_sha256(p) for p in label_paths]
    if len(set(hashes)) != len(hashes):
        raise ValueError(
            "reviewer inputs contain byte-identical files; independent review cannot be verified"
        )
    reviewer_labels = [
        _load_labels(path, expected_items, require_complete=True)
        for path in label_paths
    ]
    adjudication_path = args.adjudicated.expanduser().resolve() if args.adjudicated else None
    if adjudication_path and not adjudication_path.is_file():
        raise FileNotFoundError(f"adjudication file does not exist: {adjudication_path}")
    if adjudication_path and any(
        adjudication_path == path or adjudication_path.samefile(path)
        for path in label_paths
    ):
        raise ValueError("adjudication must be separate from reviewer files")
    adjudicated = (
        _load_labels(adjudication_path, expected_items, require_complete=False)
        if adjudication_path else None
    )

    if len(reviewer_labels) == 2:
        agreement = {
            "correctness": _cohen_kappa(
                reviewer_labels[0], reviewer_labels[1], "correctness", CORRECTNESS
            ),
            "specificity": _cohen_kappa(
                reviewer_labels[0], reviewer_labels[1], "specificity", SPECIFICITY
            ),
            "concept_validity": _cohen_kappa(
                reviewer_labels[0], reviewer_labels[1], "concept_validity", VALIDITY
            ),
        }
    else:
        pairwise_correctness = []
        pairwise_map = {}
        for i in range(len(reviewer_labels)):
            for j in range(i + 1, len(reviewer_labels)):
                k_res = _cohen_kappa(
                    reviewer_labels[i], reviewer_labels[j], "correctness", CORRECTNESS
                )
                if k_res["kappa"] is not None:
                    pairwise_correctness.append(k_res["kappa"])
                pairwise_map[f"reviewer_{i+1}__vs__reviewer_{j+1}"] = k_res["kappa"]
        mean_pairwise_k = round(sum(pairwise_correctness) / len(pairwise_correctness), 4) if pairwise_correctness else 0.0

        fleiss_correct = _fleiss_kappa(reviewer_labels, "correctness", CORRECTNESS)
        fleiss_spec = _fleiss_kappa(reviewer_labels, "specificity", SPECIFICITY)
        fleiss_valid = _fleiss_kappa(reviewer_labels, "concept_validity", VALIDITY)

        primary_k = _cohen_kappa(reviewer_labels[0], reviewer_labels[1], "correctness", CORRECTNESS)
        agreement = {
            "correctness": {
                "n": primary_k["n"],
                "raw_agreement": primary_k["raw_agreement"],
                "kappa": primary_k["kappa"],
                "mean_pairwise_kappa": mean_pairwise_k,
                "fleiss_kappa": fleiss_correct["kappa"],
                "raters": len(reviewer_labels),
            },
            "specificity": {
                "fleiss_kappa": fleiss_spec["kappa"],
            },
            "concept_validity": {
                "fleiss_kappa": fleiss_valid["kappa"],
            },
            "pairwise_cohen_kappas": pairwise_map,
            "fleiss_details": {
                "correctness": fleiss_correct,
                "specificity": fleiss_spec,
                "concept_validity": fleiss_valid,
            },
        }
    resolved, resolution_stats = _resolve_item_labels(
        expected_ids, reviewer_labels, adjudicated
    )
    concept_rows, exclusions = _concept_rows(
        key, resolved, args.uncertain_policy
    )
    included = [row for row in concept_rows if row["included"]]
    changed = [row for row in included if row["changed"]]
    disagreements_unresolved = resolution_stats.get("unadjudicated_disagreement", 0)
    adjudication_present = adjudication_path is not None
    review_ready = bool(adjudication_present and disagreements_unresolved == 0)
    protocol_compliance = _protocol_compliance(
        key,
        experiment,
        uncertain_policy=args.uncertain_policy,
        bootstrap_iterations=args.bootstrap,
        bootstrap_seed=args.seed,
    )
    headline_inference_ready = bool(
        review_ready and protocol_compliance["compliant"]
    )
    if headline_inference_ready:
        interpretation = (
            "Two complete independent reviews, separate adjudication, and every "
            "prespecified primary-analysis check are ready for headline inference."
        )
    elif not adjudication_present:
        interpretation = (
            "Provisional only: the protocol requires a separate adjudication "
            "record before any final inference, even when reviewers agree."
        )
    elif disagreements_unresolved:
        interpretation = (
            "Provisional only: at least one independent-review correctness "
            "disagreement has not been adjudicated."
        )
    else:
        interpretation = (
            "Resolved review evidence, but exploratory/sensitivity analysis only: "
            "primary-protocol checks failed: "
            + ", ".join(protocol_compliance["deviations"])
            + "."
        )

    all_sampled_seed = args.seed + 104729
    primary_changed_seed = args.seed
    all_sampled_summary = _paired_summary(
        included, args.bootstrap, all_sampled_seed
    )
    changed_parent_summary = _paired_summary(
        changed, args.bootstrap, primary_changed_seed
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "source_sha256": {"review_scorer": _sha256(Path(__file__).resolve())},
        "blinding_key": str(key_path),
        "blinding_key_sha256": _sha256(key_path),
        "experiment_id": key.get("experiment_id"),
        "input_sha256": key["input_sha256"],
        "replicate": key["replicate"],
        "comparison": key["comparison"],
        "reviewer_files": [
            {"path": str(path), "sha256_scored": _sha256(path)}
            for path in label_paths
        ],
        "adjudication_file": (
            {"path": str(adjudication_path), "sha256_scored": _sha256(adjudication_path)}
            if adjudication_path else None
        ),
        "uncertain_policy": args.uncertain_policy,
        "bootstrap_iterations": args.bootstrap,
        "bootstrap_seed": primary_changed_seed,
        "bootstrap_effective_seeds": {
            "changed_parent_primary": primary_changed_seed,
            "all_sampled_secondary": all_sampled_seed,
        },
        "inter_reviewer_agreement": agreement,
        "resolution": resolution_stats,
        "excluded_concepts": exclusions,
        "paired_results": {
            "all_sampled_concepts": all_sampled_summary,
            "changed_parent_concepts": changed_parent_summary,
        },
        "review_ready": review_ready,
        "protocol_compliance": protocol_compliance,
        "headline_inference_ready": headline_inference_ready,
        "inference_ready": headline_inference_ready,
        "headline_positive_result": bool(
            headline_inference_ready
            and changed_parent_summary["joint_positive_result"]
        ),
        "analysis_status": (
            "final_preregistered_headline"
            if headline_inference_ready else
            "resolved_exploratory_or_sensitivity"
            if review_ready else
            "provisional_review"
        ),
        "interpretation": interpretation,
        "scope": (
            "Concept-level uncertainty conditional on one frozen S09 input and "
            "the selected replicate; it does not establish generalization to "
            "another corpus, domain, model family, or complete pipeline run."
        ),
    }

    output_path = (
        args.output.expanduser().resolve() if args.output else
        key_path.parent / "score_results.json"
    )
    if output_path.exists():
        raise FileExistsError(
            f"score output already exists: {output_path}. Choose --output; "
            "nothing was overwritten."
        )
    markdown_path = output_path.with_suffix(".md")
    concept_path = output_path.with_name(output_path.stem + ".concepts.csv")
    _write_json(output_path, result)
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    _write_concept_csv(concept_path, concept_rows)
    print(f"Wrote:\n  {output_path}\n  {markdown_path}\n  {concept_path}")
    print(f"Review ready: {review_ready}")
    print(f"Primary protocol compliant: {protocol_compliance['compliant']}")
    print(f"Headline inference ready: {headline_inference_ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
