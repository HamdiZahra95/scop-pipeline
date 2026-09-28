"""Logic tests for S03's frequency binning (Task 3 / R21).

Verifies the ported binning logic and the mandated port changes:

  * every concept lands in the correct bin by `corpus_frequency`
    (1, 2, 3, 4, 5, 6-10, gt_10),
  * the 6-10 / gt_10 boundary is sourced from `common.FREQ_GATE_DEFAULT`
    (the single tunable gate, R21.1) — changing the constant moves the
    boundary,
  * `run()` writes a versioned DIRECTORY containing all non-empty bins and
    returns it (R2.3, R13.3),
  * every bin is retained on disk and no concept is dropped (R21.3),
  * the manifest records per-bin counts (R4).

These exercise the real transform end-to-end (no mocks) by driving `run()` over
a tiny synthetic S02 artifact and reading the versioned bin directory back.

Run:  pytest test_result/pipeline_v2/tests/test_s03_frequency_gate.py
"""

import json
import sys
from pathlib import Path

import pytest

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s03_frequency_gate as S03  # noqa: E402


# ── get_bin_name: pure binning logic ───────────────────────────────────────
@pytest.mark.parametrize("freq,expected", [
    (1, "freq_1"),
    (2, "freq_2"),
    (3, "freq_3"),
    (4, "freq_4"),
    (5, "freq_5"),
    (6, "freq_6_to_10"),
    (9, "freq_6_to_10"),
    (10, "freq_6_to_10"),   # boundary == gate → still in the 6-10 bin
    (11, "freq_gt_10"),     # first value ABOVE the gate
    (500, "freq_gt_10"),
    (0, "unknown"),
])
def test_get_bin_name_boundaries(freq, expected):
    assert S03.get_bin_name(freq) == expected


def test_gate_boundary_sourced_from_constant(monkeypatch):
    """The 6-10 / gt_10 split follows FREQ_GATE_DEFAULT, not a hardcoded 10.

    The exact bins 1..5 are gate-independent; the gate governs the upper split.
    With the default gate (10), freq=8 sits in the 6-10 bin. Lowering the gate
    to 7 must reclassify freq=8 as above-gate (R21.1).
    """
    assert C.FREQ_GATE_DEFAULT == 10  # documented default
    assert S03.get_bin_name(8) == "freq_6_to_10"   # 6..10 with default gate

    monkeypatch.setattr(C, "FREQ_GATE_DEFAULT", 7)
    assert S03.get_bin_name(7) == "freq_6_to_10"   # 6..gate (==7) still in range
    assert S03.get_bin_name(8) == "freq_gt_10"     # now above the lowered gate


def _seed_s02(records, tmp_path, monkeypatch):
    """Write a synthetic S02 artifact and redirect common's roots to tmp."""
    stage_dir = tmp_path / "artifacts" / "s02_consolidate"
    stage_dir.mkdir(parents=True)
    seed = stage_dir / "20990101-000000__deadbeef.json"
    C.save_json(seed, records)

    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")


def _load_bin(run_dir, name):
    path = Path(run_dir) / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_run_writes_all_bins_and_retains_every_concept(tmp_path, monkeypatch):
    """run() bins all concepts into a versioned dir; no concept is dropped."""
    records = (
        [{"target_concept": f"c1_{i}", "corpus_frequency": 1} for i in range(3)]
        + [{"target_concept": "c2", "corpus_frequency": 2}]
        + [{"target_concept": "c6", "corpus_frequency": 6}]
        + [{"target_concept": "c10", "corpus_frequency": 10}]
        + [{"target_concept": "c50", "corpus_frequency": 50}]
    )
    _seed_s02(records, tmp_path, monkeypatch)

    run_dir = S03.run()
    assert Path(run_dir).is_dir()

    assert len(_load_bin(run_dir, "freq_1")) == 3
    assert len(_load_bin(run_dir, "freq_2")) == 1
    assert len(_load_bin(run_dir, "freq_6_to_10")) == 2   # freq 6 and 10
    assert len(_load_bin(run_dir, "freq_gt_10")) == 1     # freq 50

    # No concept lost across all bins.
    total = sum(
        len(_load_bin(run_dir, b)) for b in S03.BIN_ORDER
    )
    assert total == len(records)


def test_run_manifest_has_per_bin_counts(tmp_path, monkeypatch):
    """The manifest line records per-bin counts + the gate threshold (R4)."""
    records = [
        {"target_concept": "a", "corpus_frequency": 1},
        {"target_concept": "b", "corpus_frequency": 11},
    ]
    _seed_s02(records, tmp_path, monkeypatch)

    S03.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert counts["freq_1"] == 1
    assert counts["freq_gt_10"] == 1
    assert counts["total"] == 2
    assert counts["gate_threshold"] == C.FREQ_GATE_DEFAULT


def test_reruns_never_overwrite_prior_bins(tmp_path, monkeypatch):
    """Two runs (distinct RUN_IDs) leave two bin directories on disk (R1.1, R21.3)."""
    records = [{"target_concept": "a", "corpus_frequency": 1}]
    _seed_s02(records, tmp_path, monkeypatch)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    d1 = S03.run()
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    d2 = S03.run()

    assert d1 != d2
    assert Path(d1).is_dir() and Path(d2).is_dir()
    stage_root = tmp_path / "artifacts" / "s03_frequency_gate"
    assert len([p for p in stage_root.iterdir() if p.is_dir()]) == 2


# ── Knowledge-guided gate recovery (mode == "guided") ───────────────────────
def test_guided_promotes_reference_low_freq_concepts(tmp_path, monkeypatch):
    """In guided mode, a reference-attested low-frequency concept is promoted
    into freq_gt_10; a non-reference low-freq concept stays in its bin."""
    records = [
        {"target_concept": "xgboost", "corpus_frequency": 3},        # reference → promote
        {"target_concept": "obscure widget", "corpus_frequency": 3}, # not reference → stays
        {"target_concept": "c50", "corpus_frequency": 50},           # already gt_10
    ]
    _seed_s02(records, tmp_path, monkeypatch)
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    (tmp_path / "caches").mkdir(exist_ok=True)

    # Force guided mode and stub the reference membership test (no real ontology).
    monkeypatch.setattr(C, "SCOP_MODE", "guided", raising=False)
    import knowledge as K
    monkeypatch.setattr(K, "is_reference_concept",
                        lambda name: name.strip().lower() == "xgboost")

    run_dir = S03.run()
    gt10 = {r["target_concept"] for r in _load_bin(run_dir, "freq_gt_10")}
    freq3 = {r["target_concept"] for r in _load_bin(run_dir, "freq_3")}

    assert "xgboost" in gt10          # recovered
    assert "c50" in gt10              # already above the gate
    assert "obscure widget" in freq3  # untouched
    assert "xgboost" not in freq3


def test_baseline_does_not_promote(tmp_path, monkeypatch):
    """In baseline mode, no recovery happens (byte-identical binning)."""
    records = [{"target_concept": "xgboost", "corpus_frequency": 3}]
    _seed_s02(records, tmp_path, monkeypatch)
    monkeypatch.setattr(C, "SCOP_MODE", "baseline", raising=False)

    run_dir = S03.run()
    assert "xgboost" in {r["target_concept"] for r in _load_bin(run_dir, "freq_3")}
    assert _load_bin(run_dir, "freq_gt_10") == []
