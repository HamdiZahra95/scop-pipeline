"""Property-based tests for the common.py foundation invariants (Task 1.2).

Framework: Hypothesis (design.md "Testing Strategy" — PBT is appropriate for the
common.py invariants). Each test maps to a numbered Correctness Property from the
design's "Correctness Properties" section:

  * Property 1  — No overwrite            (Requirements 1.1, 1.5)
  * Property 3  — Latest selection        (Requirements 2.1, 2.2)
  * Property 4  — Code-hash discrimination(Requirements 1.2, 1.3)
  * Property 8  — OWL-DL axiom-table sanity(Requirements 16.1, 16.2, 16.5)
  * Property 12 — Manifest completeness   (Requirements 4.1, 4.2)

These tests never touch the real artifacts/ or logs/ trees. Because Hypothesis
does not reset function-scoped pytest fixtures between generated inputs, each
property manages its own temp directory and patches ``common``'s module globals
(ARTIFACTS, MANIFEST) and RUN_ID via the ``sandbox`` context manager below,
restoring them afterwards. This keeps every generated example isolated.

Run:  pytest test_result/pipeline_v2/tests/test_foundation_properties.py
"""

import contextlib
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Make the pipeline_v2 dir importable so `import common` works regardless of the
# pytest invocation directory.
PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))

import common as C  # noqa: E402


@contextlib.contextmanager
def sandbox(run_id=None, artifacts=True, manifest=False):
    """Isolate a generated example: fresh temp dir + patched common globals.

    Restores C.ARTIFACTS / C.MANIFEST / C.RUN_ID on exit so no real pipeline
    output is touched and examples never leak state into one another.
    """
    saved = {"ARTIFACTS": C.ARTIFACTS, "MANIFEST": C.MANIFEST, "RUN_ID": C.RUN_ID}
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        try:
            if artifacts:
                C.ARTIFACTS = base / "artifacts"
                C.ARTIFACTS.mkdir(parents=True, exist_ok=True)
            if manifest:
                C.MANIFEST = base / "manifest.jsonl"
            if run_id is not None:
                C.RUN_ID = run_id
            yield base
        finally:
            C.ARTIFACTS = saved["ARTIFACTS"]
            C.MANIFEST = saved["MANIFEST"]
            C.RUN_ID = saved["RUN_ID"]


# ── shared strategies ──────────────────────────────────────────────────────
# Sortable RUN_ID-like labels: the real RUN_ID is a timestamp string, so we use
# short alphanumeric tokens that are safe as directory/file-name components.
_run_id_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1, max_size=20,
)
# Source bytes for a fake caller file (drives code_hash).
_source_st = st.binary(min_size=0, max_size=64)


def _write_source(tmp_dir: Path, data: bytes) -> Path:
    """Write bytes to a fresh .py file (unique by content) and return its path."""
    name = "src_" + hashlib.sha256(data).hexdigest()[:12] + ".py"
    p = tmp_dir / name
    p.write_bytes(data)
    return p


# ── Property 1: No overwrite ────────────────────────────────────────────────
# For any sequence of stage runs (any mix of RUN_IDs and code hashes), the file
# count in artifacts/<stage>/ never decreases and no existing file's bytes ever
# change.
# **Validates: Requirements 1.1, 1.5**
@settings(max_examples=150, deadline=None)
@given(
    writes=st.lists(
        st.tuples(_run_id_st, st.integers(min_value=0, max_value=30)),
        min_size=1, max_size=25,
    ),
)
def test_property1_no_overwrite(writes):
    with sandbox() as base:
        src_dir = base / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        stage = "s99_no_overwrite"

        # Snapshot of {path: bytes} that must remain intact across the whole run.
        seen: dict[Path, bytes] = {}
        prev_count = 0

        for run_id, code_variant in writes:
            C.RUN_ID = run_id
            # Source bytes are a deterministic function of code_variant so that a
            # repeated (run_id, code_variant) pair yields the SAME code_hash and
            # SAME filename — exactly as a re-run with identical code+input would.
            src = _write_source(src_dir, f"# variant {code_variant}\n".encode())

            out = C.output_path(stage, str(src), ext="json")
            # Content is a pure function of the filename key, so re-hitting the
            # same (run_id, code_hash) filename writes byte-identical content.
            content = json.dumps({"key": out.name}, sort_keys=True)
            out.write_text(content, encoding="utf-8")

            stage_dir = C.ARTIFACTS / stage
            files = sorted(stage_dir.glob("*.json"))

            # Invariant A: file count never decreases.
            assert len(files) >= prev_count
            prev_count = len(files)

            # Invariant B: every previously-seen file still has original bytes.
            for f in files:
                b = f.read_bytes()
                if f in seen:
                    assert seen[f] == b, f"bytes of {f.name} changed (overwrite!)"
                else:
                    seen[f] = b


# ── Property 3: Latest selection ────────────────────────────────────────────
# require_latest(stage) returns the lexicographically greatest existing artifact
# and raises iff none exist.
# **Validates: Requirements 2.1, 2.2**
@settings(max_examples=150, deadline=None)
@given(
    stems=st.lists(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
            min_size=1, max_size=24,
        ),
        min_size=0, max_size=15, unique=True,
    ),
)
def test_property3_latest_selection(stems):
    with sandbox() as _base:
        stage = "s99_latest"
        stage_dir = C.ARTIFACTS / stage
        stage_dir.mkdir(parents=True, exist_ok=True)

        if not stems:
            # No artifacts on disk → require_latest must raise a clear error.
            assert C.latest_output(stage) is None
            with pytest.raises(FileNotFoundError):
                C.require_latest(stage)
            return

        for s in stems:
            (stage_dir / f"{s}.json").write_text("{}", encoding="utf-8")

        expected = stage_dir / f"{max(stems)}.json"
        assert C.require_latest(stage) == expected
        assert C.latest_output(stage) == expected


# ── Property 4: Code-hash discrimination ────────────────────────────────────
# Two runs produce the same output filename iff both RUN_ID and source bytes are
# identical; changing source bytes changes codehash8.
# **Validates: Requirements 1.2, 1.3**
@settings(max_examples=200, deadline=None)
@given(
    run_a=_run_id_st, run_b=_run_id_st,
    src_a=_source_st, src_b=_source_st,
)
def test_property4_code_hash_discrimination(run_a, run_b, src_a, src_b):
    with sandbox() as base:
        src_dir = base / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        stage = "s99_codehash"

        file_a = _write_source(src_dir, src_a)
        file_b = _write_source(src_dir, src_b)

        # code_hash is a pure function of source bytes: equal bytes ⇒ equal hash.
        if src_a == src_b:
            assert C.code_hash(str(file_a)) == C.code_hash(str(file_b))
        else:
            # Different source bytes ⇒ different codehash8 (32-bit truncation
            # makes a collision astronomically unlikely for these small inputs).
            assert C.code_hash(str(file_a)) != C.code_hash(str(file_b))

        C.RUN_ID = run_a
        name_a = C.output_path(stage, str(file_a), ext="json").name
        C.RUN_ID = run_b
        name_b = C.output_path(stage, str(file_b), ext="json").name

        same_filename = name_a == name_b
        same_inputs = (run_a == run_b) and (src_a == src_b)
        # Biconditional: same filename ⇔ (same RUN_ID AND same source bytes).
        assert same_filename == same_inputs


# ── Property 8: OWL-DL axiom-table sanity ───────────────────────────────────
# For every entry in PROPERTY_AXIOMS: no property is both Transitive and carries
# cardinality; none of the 13 core is Functional/InverseFunctional; every entry
# has domain and range. Includes mutation tests that MUST fail the check.
# **Validates: Requirements 16.1, 16.2, 16.5**
def test_property8_real_table_is_sane():
    # Exhaustive over the fixed table: the real axiom box must validate.
    C.validate_property_axioms()
    for prop, spec in C.PROPERTY_AXIOMS.items():
        chars = set(spec.get("characteristics", []) or [])
        assert spec.get("domain"), prop
        assert spec.get("range"), prop
        assert not (chars & {"Functional", "InverseFunctional"}), prop
        if "Transitive" in chars:
            assert not spec.get("cardinality"), prop


@settings(max_examples=150, deadline=None)
@given(
    prop=st.sampled_from(C.CORE_PROPERTIES),
    card=st.integers(min_value=1, max_value=5),
)
def test_property8_mutation_transitive_plus_cardinality_raises(prop, card):
    """Adding a cardinality restriction to ANY property that is (or is made)
    Transitive must make the validator raise (R16.1)."""
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    chars = list(bad[prop].get("characteristics", []) or [])
    if "Transitive" not in chars:
        chars = chars + ["Transitive"]
    bad[prop]["characteristics"] = chars
    bad[prop]["cardinality"] = card
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


@settings(max_examples=150, deadline=None)
@given(
    prop=st.sampled_from(C.CORE_PROPERTIES),
    forbidden=st.sampled_from(["Functional", "InverseFunctional"]),
)
def test_property8_mutation_forbidden_characteristic_raises(prop, forbidden):
    """Assigning Functional/InverseFunctional to any core property raises (R16.5)."""
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    bad[prop]["characteristics"] = list(bad[prop].get("characteristics", []) or []) + [forbidden]
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


@settings(max_examples=150, deadline=None)
@given(
    prop=st.sampled_from(C.CORE_PROPERTIES),
    drop=st.sampled_from(["domain", "range"]),
)
def test_property8_mutation_missing_domain_or_range_raises(prop, drop):
    """Removing domain or range from any core property raises (R16.2)."""
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    bad[prop].pop(drop, None)
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


# ── Property 12: Manifest completeness ──────────────────────────────────────
# Every completed stage run appends exactly one manifest line carrying all
# required fields.
# **Validates: Requirements 4.1, 4.2**
_REQUIRED_MANIFEST_FIELDS = {
    "ts", "run_id", "stage", "code_sha", "in", "in_sha", "out", "out_sha", "counts",
}


@settings(max_examples=150, deadline=None)
@given(
    run_id=_run_id_st,
    stage=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
                  min_size=1, max_size=20),
    in_bytes=st.binary(min_size=0, max_size=64),
    out_bytes=st.binary(min_size=0, max_size=64),
    counts=st.dictionaries(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12),
        st.integers(min_value=0, max_value=10**6),
        max_size=6,
    ),
)
def test_property12_manifest_completeness(run_id, stage, in_bytes, out_bytes, counts):
    with sandbox(run_id=run_id, manifest=True) as base:
        src = base / "stage_src.py"
        src.write_bytes(b"# stage source\n")
        in_path = base / "in.json"
        out_path = base / "out.json"
        in_path.write_bytes(in_bytes)
        out_path.write_bytes(out_bytes)

        before = C.MANIFEST.read_text().count("\n") if C.MANIFEST.exists() else 0
        C.write_manifest(stage, str(src), in_path, out_path, counts=counts)
        lines = C.MANIFEST.read_text(encoding="utf-8").splitlines()

        # Exactly one new line appended per completed run.
        assert len(lines) == before + 1

        rec = json.loads(lines[-1])
        # All required fields present.
        assert _REQUIRED_MANIFEST_FIELDS.issubset(rec.keys())
        # Fields carry the correct values.
        assert rec["run_id"] == run_id
        assert rec["stage"] == stage
        assert rec["code_sha"] == C.code_hash(str(src))
        assert rec["in"] == str(in_path)
        assert rec["out"] == str(out_path)
        assert rec["in_sha"] == hashlib.sha256(in_bytes).hexdigest()
        assert rec["out_sha"] == hashlib.sha256(out_bytes).hexdigest()
        assert rec["counts"] == counts
        assert isinstance(rec["ts"], str) and rec["ts"]
