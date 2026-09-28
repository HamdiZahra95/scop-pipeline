"""
Run the controlled S09a semantic taxonomy-repair ablation.

The experiment starts each replicate from one explicit, SHA-256-identified S09
artifact. Within a replicate, Phase 1 is generated once and shared between the
``phase1`` and ``full`` conditions. Replicates use physically separate cache
namespaces under the experiment directory. Existing caches are never cleared or
silently reused: a new run fails if its output directory already exists, while
``--resume`` validates the immutable experiment configuration before continuing.

No historical pipeline artifact is overwritten.

Example (from pipeline_v2/):

    python analysis/v14_s09a_paired_ablation.py \
      --input artifacts/s09_qa_repair/20260815-122647__03e5db99.json \
      --conditions fallback phase1 full \
      --replicates 5 \
      --experiment-id s09a_primary_2026

Running Phase 1/full sends concept labels and paths to the configured LLM
provider. ``fallback`` is deterministic and makes no external LLM request.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
sys.path.insert(0, str(PV2 / "stages"))

import common as PC
import s09a_taxonomy_rehome as S9A

SCHEMA_VERSION = "s09a-ablation-v1"
PROTOCOL_ID = "s09a-ablation-protocol-v1.6"
PROTOCOL_REQUEST_TIMEOUT_SECONDS = 200.0
PROTOCOL_MAX_OUTPUT_TOKENS = 8192


class EvidenceIntegrityError(RuntimeError):
    """Raised when a recorded artifact, ledger, or count no longer matches."""

DEFAULT_INPUT = (
    PV2 / "artifacts" / "s09_qa_repair"
    / "20260815-122647__03e5db99.json"
)
DEFAULT_RESULTS_ROOT = Path(__file__).resolve().parent / "results" / "s09a_ablation"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_experiment_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    if not cleaned:
        raise argparse.ArgumentTypeError("experiment id must contain a letter or digit")
    return cleaned


def _source_hashes() -> dict[str, str]:
    files = {
        "ablation_runner": Path(__file__).resolve(),
        "s09a_stage": Path(S9A.__file__).resolve(),
        "pipeline_common": Path(PC.__file__).resolve(),
    }
    return {name: _sha256(path) for name, path in files.items()}


def _tunable_snapshot() -> dict:
    snapshot = {
        "floater_batch": S9A.FLOATER_BATCH,
        "refine_batch": S9A.REFINE_BATCH,
        "max_passes": S9A.MAX_PASSES,
        "max_refine_level": S9A.MAX_REFINE_LEVEL,
        "fuzzy_threshold": S9A.FUZZY_THRESHOLD,
        "request_timeout_seconds": S9A.REFINE_TIMEOUT,
        "max_output_tokens": S9A.REFINE_MAX_TOKENS,
        "llm_schema_attempts": PC.LLM_MAX_SCHEMA_ATTEMPTS,
        "llm_rate_retries": PC.LLM_MAX_RATE_RETRIES,
    }
    if snapshot["request_timeout_seconds"] != PROTOCOL_REQUEST_TIMEOUT_SECONDS:
        raise ValueError(
            f"protocol {PROTOCOL_ID} requires S09A_REFINE_TIMEOUT="
            f"{PROTOCOL_REQUEST_TIMEOUT_SECONDS:g}; effective value is "
            f"{snapshot['request_timeout_seconds']:g}. Use the protocol value "
            "or create and document a new protocol amendment."
        )
    if snapshot["max_output_tokens"] != PROTOCOL_MAX_OUTPUT_TOKENS:
        raise ValueError(
            f"protocol {PROTOCOL_ID} requires S09A_REFINE_MAX_TOKENS="
            f"{PROTOCOL_MAX_OUTPUT_TOKENS}; effective value is "
            f"{snapshot['max_output_tokens']}. Use the protocol value or create "
            "and document a new protocol amendment."
        )
    return snapshot


def _new_configuration(args, input_path: Path, input_sha: str,
                       output_root: Path) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "study": "frozen-input S09a semantic taxonomy-repair ablation",
        "status": "planned",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "experiment_id": args.experiment_id,
        "input": {
            "path": str(input_path),
            "sha256": input_sha,
            "bytes": input_path.stat().st_size,
        },
        "conditions": list(args.conditions),
        "replicates": args.replicates,
        "primary_replicate": args.primary_replicate,
        "seed": args.seed,
        "model": PC.GEMINI_MODEL,
        "initial_temperature": 0,
        "output_root": str(output_root),
        "cache_root": str(output_root / "cache"),
        "trace_path": str(output_root / "logs" / "llm_trace.jsonl"),
        "source_sha256": _source_hashes(),
        "tunables": _tunable_snapshot(),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "SCOP_mode_at_launch": os.getenv("SCOP_MODE", "baseline"),
        },
        "design": {
            "same_input_all_conditions": True,
            "phase1_shared_with_full_within_replicate": True,
            "physically_isolated_cache_per_replicate": True,
            "fresh_cache_rule": (
                "namespace must not exist for a new experiment; --resume may only "
                "reuse the namespace recorded by this same configuration"
            ),
            "primary_comparison": "fallback versus full",
            "secondary_comparison": "phase1 versus full",
            "structural_metrics_are_secondary": True,
        },
        "replicate_status": {},
        "warnings": [],
    }


def _immutable_projection(config: dict) -> dict:
    keys = (
        "schema_version", "protocol_id", "experiment_id", "input", "conditions",
        "replicates", "primary_replicate", "seed", "model", "source_sha256",
        "tunables",
    )
    return {key: config.get(key) for key in keys}


def _prepare_experiment(args, input_path: Path, output_root: Path) -> dict:
    manifest_path = output_root / "experiment.json"
    input_sha = _sha256(input_path)
    proposed = _new_configuration(args, input_path, input_sha, output_root)

    if output_root.exists() and not args.resume:
        raise FileExistsError(
            f"experiment directory already exists: {output_root}. Choose a new "
            "--experiment-id/--output or use --resume. Nothing was deleted."
        )
    if args.resume:
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"cannot resume without {manifest_path}; nothing was changed"
            )
        existing = _load_json(manifest_path)
        if _immutable_projection(existing) != _immutable_projection(proposed):
            raise ValueError(
                "resume configuration differs from the recorded immutable design. "
                "Use the original arguments or start a new experiment id."
            )
        existing["status"] = "running"
        existing["updated_at_utc"] = _utc_now()
        _write_json(manifest_path, existing)
        return existing

    output_root.mkdir(parents=True, exist_ok=False)
    proposed["status"] = "running"
    proposed["started_at_utc"] = _utc_now()
    _write_json(manifest_path, proposed)
    return proposed


def _cache_state(path: Path) -> dict:
    files = sorted(item for item in path.rglob("*") if item.is_file()) if path.exists() else []
    return {
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "bytes": sum(item.stat().st_size for item in files),
        "files": [
            {
                "relative_path": str(item.relative_to(path)),
                "sha256": _sha256(item),
                "bytes": item.stat().st_size,
            }
            for item in files
        ],
    }


def _write_condition(replicate_dir: Path, condition: str,
                     outcome: dict) -> dict:
    artifact_path = replicate_dir / f"{condition}.json"
    ledger_path = replicate_dir / f"{condition}.movements.jsonl"
    _write_json(artifact_path, outcome["db"])
    _write_jsonl(ledger_path, outcome["ledger"])
    return {
        "condition": condition,
        "artifact": str(artifact_path),
        "artifact_sha256": _sha256(artifact_path),
        "artifact_bytes": artifact_path.stat().st_size,
        "movement_ledger": str(ledger_path),
        "movement_ledger_sha256": _sha256(ledger_path),
        "movement_rows": len(outcome["ledger"]),
        "counts": outcome["counts"],
    }


def _verify_condition_output(record: dict,
                             expected_condition: str | None = None) -> None:
    """Recompute all recorded evidence identities before consuming or skipping."""
    if not isinstance(record, dict):
        raise EvidenceIntegrityError("condition-output record is not an object")
    if (expected_condition is not None
            and record.get("condition") != expected_condition):
        raise EvidenceIntegrityError(
            f"condition-output identity mismatch: expected {expected_condition!r}, "
            f"recorded {record.get('condition')!r}"
        )
    artifact = Path(record.get("artifact", ""))
    ledger = Path(record.get("movement_ledger", ""))
    if not artifact.is_file() or not ledger.is_file():
        raise EvidenceIntegrityError(
            f"missing recorded output for condition {record.get('condition')!r}"
        )
    if artifact.stat().st_size != record.get("artifact_bytes"):
        raise EvidenceIntegrityError(f"artifact size changed: {artifact}")
    if _sha256(artifact) != record.get("artifact_sha256"):
        raise EvidenceIntegrityError(f"artifact hash changed: {artifact}")
    if _sha256(ledger) != record.get("movement_ledger_sha256"):
        raise EvidenceIntegrityError(f"movement-ledger hash changed: {ledger}")
    with open(ledger, "r", encoding="utf-8") as handle:
        rows = sum(1 for line in handle if line.strip())
    if rows != record.get("movement_rows"):
        raise EvidenceIntegrityError(f"movement-ledger row count changed: {ledger}")


def _completed_replicate(path: Path, config: dict, replicate: int) -> bool:
    if not path.is_file():
        return False
    manifest = _load_json(path)
    if manifest.get("status") != "complete":
        return False
    metadata_matches = bool(
        manifest.get("replicate") == replicate
        and manifest.get("protocol_id") == config["protocol_id"]
        and manifest.get("input_sha256") == config["input"]["sha256"]
        and manifest.get("source_sha256") == config["source_sha256"]
        and manifest.get("conditions") == config["conditions"]
    )
    if not metadata_matches:
        raise EvidenceIntegrityError(
            f"completed replicate {replicate} metadata no longer matches its design"
        )
    outputs = manifest.get("condition_outputs", {})
    if set(outputs) != set(config["conditions"]):
        raise EvidenceIntegrityError(
            f"replicate {replicate} condition outputs do not match its design"
        )
    for condition in config["conditions"]:
        _verify_condition_output(outputs[condition], condition)
    return True


def _run_replicate(config: dict, replicate: int, frozen_db: dict,
                   output_root: Path, resume: bool) -> dict:
    replicate_name = f"replicate_{replicate:03d}"
    replicate_dir = output_root / "replicates" / replicate_name
    replicate_manifest_path = replicate_dir / "manifest.json"
    if _completed_replicate(replicate_manifest_path, config, replicate):
        print(f"[{replicate_name}] complete; verified manifest, skipping.")
        return _load_json(replicate_manifest_path)

    cache_namespace = replicate_name
    cache_path = Path(config["cache_root"]) / cache_namespace
    start_cache = _cache_state(cache_path)
    if not resume and start_cache["exists"]:
        raise FileExistsError(
            f"fresh-cache violation: {cache_path} already exists. Nothing was deleted."
        )

    replicate_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": config["protocol_id"],
        "status": "running",
        "replicate": replicate,
        "primary": replicate == config["primary_replicate"],
        "started_at_utc": _utc_now(),
        "input_sha256": config["input"]["sha256"],
        "source_sha256": config["source_sha256"],
        "conditions": config["conditions"],
        "seed": config["seed"],
        "model": config["model"],
        "cache_namespace": cache_namespace,
        "cache_at_start": start_cache,
        "condition_outputs": {},
    }
    _write_json(replicate_manifest_path, manifest)

    outcomes = S9A.run_conditions(
        frozen_db,
        conditions=tuple(config["conditions"]),
        input_sha=config["input"]["sha256"],
        cache_namespace=cache_namespace,
    )
    for condition in config["conditions"]:
        manifest["condition_outputs"][condition] = _write_condition(
            replicate_dir, condition, outcomes[condition]
        )
        _verify_condition_output(
            manifest["condition_outputs"][condition], condition
        )
    manifest["cache_at_end"] = _cache_state(cache_path)
    manifest["status"] = "complete"
    manifest["completed_at_utc"] = _utc_now()
    _write_json(replicate_manifest_path, manifest)
    print(f"[{replicate_name}] complete -> {replicate_dir}")
    return manifest


def _eligible_parent_map(db: dict, original_names: set[str]) -> dict[str, str]:
    result = {}
    for name in original_names:
        data = db.get(name)
        if not isinstance(data, dict):
            continue
        if data.get("is_skeleton") or data.get("qa_bypassed"):
            continue
        parent = data.get("taxonomy_parent")
        if parent:
            result[name] = parent
    return result


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _stability_summary(config: dict, output_root: Path) -> dict:
    input_path = Path(config["input"]["path"])
    if _sha256(input_path) != config["input"]["sha256"]:
        raise EvidenceIntegrityError("frozen input hash changed before stability analysis")
    input_db = _load_json(input_path)
    original_names = {
        name for name, data in input_db.items()
        if name != "__meta__" and isinstance(data, dict)
    }
    completed = []
    for replicate in range(1, config["replicates"] + 1):
        path = output_root / "replicates" / f"replicate_{replicate:03d}" / "manifest.json"
        if _completed_replicate(path, config, replicate):
            completed.append(_load_json(path))

    by_condition = {}
    for condition in config["conditions"]:
        manifests = [
            item["condition_outputs"][condition] for item in completed
            if condition in item.get("condition_outputs", {})
        ]
        parent_maps = [
            _eligible_parent_map(
                _load_json(Path(item["artifact"])), original_names
            )
            for item in manifests
        ]
        agreements = []
        jaccards = []
        for left, right in itertools.combinations(parent_maps, 2):
            common = sorted(set(left) & set(right))
            agreements.append(
                sum(left[name] == right[name] for name in common) / len(common)
                if common else 1.0
            )
            left_edges = set(left.items())
            right_edges = set(right.items())
            union = left_edges | right_edges
            jaccards.append(len(left_edges & right_edges) / len(union) if union else 1.0)
        all_names = set().union(*(set(mapping) for mapping in parent_maps)) if parent_maps else set()
        variable = sum(
            1 for name in all_names
            if len({mapping.get(name) for mapping in parent_maps}) > 1
        )
        by_condition[condition] = {
            "completed_replicates": len(manifests),
            "artifact_sha256": [item["artifact_sha256"] for item in manifests],
            "unique_artifact_sha256": len({item["artifact_sha256"] for item in manifests}),
            "mean_pairwise_parent_agreement": _mean(agreements),
            "mean_pairwise_edge_jaccard": _mean(jaccards),
            "variable_parent_concepts": variable,
            "eligible_original_concepts": len(all_names),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": config["protocol_id"],
        "generated_at_utc": _utc_now(),
        "input_sha256": config["input"]["sha256"],
        "completed_replicates": len(completed),
        "requested_replicates": config["replicates"],
        "conditions": by_condition,
        "interpretation": (
            "Agreement describes isolated-cache realizations under the recorded "
            "provider/model settings; it is not an estimate from independent "
            "corpora or domains."
        ),
    }


def _render_stability(summary: dict) -> str:
    lines = [
        "# S09a isolated-cache stability",
        "",
        f"Input SHA-256: `{summary['input_sha256']}`",
        f"Completed: {summary['completed_replicates']}/"
        f"{summary['requested_replicates']} replicates",
        "",
        "| condition | complete | unique outputs | parent agreement | edge Jaccard | variable parents |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for condition, values in summary["conditions"].items():
        lines.append(
            f"| {condition} | {values['completed_replicates']} | "
            f"{values['unique_artifact_sha256']} | "
            f"{values['mean_pairwise_parent_agreement']} | "
            f"{values['mean_pairwise_edge_jaccard']} | "
            f"{values['variable_parent_concepts']} |"
        )
    lines.extend(["", f"> {summary['interpretation']}", ""])
    return "\n".join(lines)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Frozen-input, fresh-cache S09a mechanism ablation."
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help=f"Explicit S09 JSON artifact (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--conditions", nargs="+", choices=S9A.CONDITIONS,
        default=list(S9A.CONDITIONS),
        help="Conditions to execute; use fallback alone for a no-network smoke run.",
    )
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--primary-replicate", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--experiment-id", type=_safe_experiment_id,
        default=f"s09a_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Experiment directory (default: analysis/results/s09a_ablation/<id>).",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume only when the recorded immutable configuration matches.",
    )
    args = parser.parse_args(argv)
    if args.replicates < 1:
        parser.error("--replicates must be at least 1")
    if not 1 <= args.primary_replicate <= args.replicates:
        parser.error("--primary-replicate must be within 1..--replicates")
    args.conditions = list(dict.fromkeys(args.conditions))
    return args


def main(argv=None) -> int:
    args = _parse_args(argv)
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"frozen S09 input does not exist: {input_path}")
    output_root = (
        args.output.expanduser().resolve() if args.output
        else (DEFAULT_RESULTS_ROOT / args.experiment_id).resolve()
    )
    config = _prepare_experiment(args, input_path, output_root)

    # Redirect only this process's caches and traces into the experiment root.
    PC.CACHES = Path(config["cache_root"])
    PC.LLM_TRACE_PATH = Path(config["trace_path"])
    PC.LLM_SEED = config["seed"]
    PC._LLM_CACHES = {}
    Path(config["trace_path"]).parent.mkdir(parents=True, exist_ok=True)

    frozen_db = _load_json(input_path)
    manifest_path = output_root / "experiment.json"
    try:
        for replicate in range(1, config["replicates"] + 1):
            result = _run_replicate(
                config, replicate, frozen_db, output_root, args.resume
            )
            config["replicate_status"][str(replicate)] = result["status"]
            config["updated_at_utc"] = _utc_now()
            _write_json(manifest_path, config)
    except PC.QuotaExhausted as exc:
        config["status"] = "paused_quota"
        config["updated_at_utc"] = _utc_now()
        config["pause_reason"] = str(exc)
        _write_json(manifest_path, config)
        print(
            "Experiment paused on daily quota. Re-run with the identical arguments "
            f"and --resume. Progress remains under {config['cache_root']}."
        )
        return 0
    except Exception as exc:
        config["status"] = "failed"
        config["updated_at_utc"] = _utc_now()
        config["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        _write_json(manifest_path, config)
        raise

    stability = _stability_summary(config, output_root)
    _write_json(output_root / "stability_summary.json", stability)
    (output_root / "stability_summary.md").write_text(
        _render_stability(stability), encoding="utf-8"
    )
    config["status"] = "complete"
    config["completed_at_utc"] = _utc_now()
    config["updated_at_utc"] = _utc_now()
    config["stability_summary"] = str(output_root / "stability_summary.json")
    if not {"fallback", "full"}.issubset(config["conditions"]):
        config["warnings"].append(
            "Primary fallback-versus-full design is incomplete; this run is a "
            "smoke/partial experiment and must not support the headline inference."
        )
    _write_json(manifest_path, config)
    print(f"Experiment complete -> {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
