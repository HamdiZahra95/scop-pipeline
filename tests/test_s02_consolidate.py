"""Logic tests for S02's mandated normalization change (Task 2.1 / R9).

Verifies the deterministic case/space normalization that S02 adds on top of the
ported consolidation logic:

  * case variants collapse           ("Deep Learning" == "deep learning"),
  * internal-whitespace variants collapse ("deep  learning" == "deep learning"),
  * surrounding whitespace collapses (" deep learning " == "deep learning"),
  * merged variants COMBINE their frequencies and their definitions into a
    single surviving concept (R9.3),
  * the emitted concept carries the full output contract (R9.2).

These exercise the real transform end-to-end (no mocks) by driving `run()` over
a tiny synthetic S01 artifact and reading the versioned S02 output back.

Run:  pytest test_result/pipeline_v2/tests/test_s02_consolidate.py
"""

import sys
from pathlib import Path

import pytest

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s02_consolidate as S02  # noqa: E402


# ── normalize_name: the deterministic grouping key ─────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("Deep Learning", "deep learning"),
    ("deep learning", "deep learning"),
    ("  deep learning  ", "deep learning"),
    ("deep  learning", "deep learning"),
    ("DEEP\tLEARNING", "deep learning"),
    ("Neural   Network\n", "neural network"),
])
def test_normalize_name_collapses_case_and_space(raw, expected):
    assert S02.normalize_name(raw) == expected


def _seed_from(records, tmp_path, monkeypatch):
    """Point S01's artifact dir at a tmp seed built from `records` and return
    a loader for whatever S02 writes."""
    stage_dir = tmp_path / "artifacts" / "s01_seed_concepts"
    stage_dir.mkdir(parents=True)
    seed = stage_dir / "20990101-000000__deadbeef.jsonl"
    C.save_jsonl(seed, records)

    # Redirect common's ARTIFACTS root so require_latest/output_path use tmp.
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")


def _run_and_load(tmp_path):
    out = S02.run()
    return C.load_json(out)


def test_case_and_space_variants_merge_into_one_concept(tmp_path, monkeypatch):
    """Three surface variants of the same concept collapse into ONE, combining
    frequencies and definitions (R9.1, R9.3)."""
    records = [
        {"id": 1, "concept_name": "Deep Learning", "definition": "Def A."},
        {"id": 2, "concept_name": "deep learning", "definition": "Def B."},
        {"id": 3, "concept_name": "deep  learning", "definition": "Def A."},  # dup def
        {"id": 4, "concept_name": "Neural Network", "definition": "Def C."},
    ]
    _seed_from(records, tmp_path, monkeypatch)
    result = _run_and_load(tmp_path)

    by_norm = {S02.normalize_name(c["target_concept"]): c for c in result}
    # deep learning + neural network → exactly two concepts.
    assert len(result) == 2
    assert set(by_norm) == {"deep learning", "neural network"}

    dl = by_norm["deep learning"]
    # Frequency combines all 3 variant records.
    assert dl["corpus_frequency"] == 3
    # Definitions combine + dedupe (Def A appeared twice).
    assert sorted(dl["consolidated_definitions"]) == ["Def A.", "Def B."]


def test_output_contract_fields_present(tmp_path, monkeypatch):
    """Each emitted concept carries the full R9.2 contract."""
    records = [
        {"id": 1, "concept_name": "learning", "definition": "General learning."},
        {"id": 2, "concept_name": "deep learning", "definition": "learning with depth."},
    ]
    _seed_from(records, tmp_path, monkeypatch)
    result = _run_and_load(tmp_path)

    required = {
        "target_concept", "corpus_frequency", "consolidated_definitions",
        "lexical_broader", "lexical_narrower", "evidence_mentions",
    }
    for concept in result:
        assert required.issubset(concept.keys())
        assert isinstance(concept["corpus_frequency"], int)
        assert isinstance(concept["consolidated_definitions"], list)


def test_frequency_is_sum_not_max(tmp_path, monkeypatch):
    """Two records of the same normalized concept sum to frequency 2 (proves the
    merge adds counts rather than dropping duplicates)."""
    records = [
        {"id": 1, "concept_name": "Gradient Descent", "definition": "D1."},
        {"id": 2, "concept_name": "gradient descent", "definition": "D2."},
    ]
    _seed_from(records, tmp_path, monkeypatch)
    result = _run_and_load(tmp_path)
    assert len(result) == 1
    assert result[0]["corpus_frequency"] == 2
    assert sorted(result[0]["consolidated_definitions"]) == ["D1.", "D2."]
