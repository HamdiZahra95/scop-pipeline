"""Logic tests for S04's property mining (Task 4 / R23 source).

Verifies the ported analytical logic and the mandated port changes:

  * the four regex patterns mine (verb, object) actions and lemmatize verbs,
  * untreated definitions are tracked and coverage is recorded,
  * `run()` reads ONLY the `freq_gt_10` bin of the latest S03 directory (the
    single gate source, R21.1) so only freq>10 concepts appear (R13.1, R23.1),
  * the output honours the `{f, td, cov, props, unt, consolidated_definitions}`
    contract, carries the definitions through for S11 (R20.3), and records raw
    mined verbs under `props[verb]...` as the sub-property source (R23.1),
  * `run()` writes a versioned artifact and returns it (R2.3, R13.3),
  * re-runs never overwrite a prior artifact (R1.1),
  * the manifest records concept count, mean coverage, and verb count (R4).

The object-clustering (SentenceTransformer) step is monkeypatched to an
identity map so tests run fast and offline; the mining/coverage logic under
test is exercised for real (no mocks).

Run:  pytest test_result/pipeline_v2/tests/test_s04_extract_properties.py
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
import s04_extract_properties as S04  # noqa: E402


# ── extract_unified_actions_with_tracking: pure mining logic ────────────────
def test_p1_that_which_verb_object_and_lemmatization():
    """P1 pattern mines (verb, object) and lemmatizes the verb."""
    defs = ["A model that uses gradient descent to optimize weights."]
    actions, untreated = S04.extract_unified_actions_with_tracking(defs)
    verbs = {a[0] for a in actions}
    assert "use" in verbs               # 'uses' → lemma 'use'
    assert any("gradient descent" in a[1] for a in actions)
    assert untreated == []              # the single def was treated


def test_untreated_tracked_when_no_pattern_matches():
    """A definition matching no pattern is recorded as untreated."""
    defs = ["A purely nominal phrase with no action verb."]
    actions, untreated = S04.extract_unified_actions_with_tracking(defs)
    assert actions == []
    assert untreated == defs


def test_mixed_treated_and_untreated():
    defs = [
        "An algorithm that applies backpropagation for training.",  # treated
        "A standalone noun phrase.",                                # untreated
    ]
    actions, untreated = S04.extract_unified_actions_with_tracking(defs)
    assert len(actions) >= 1
    assert untreated == ["A standalone noun phrase."]


# ── cluster_objects_semantically: trivial (no-model) branches ───────────────
def test_cluster_single_object_is_identity_without_model():
    assert S04.cluster_objects_semantically(["only one"]) == {"only one": "only one"}
    assert S04.cluster_objects_semantically([]) == {}


# ── run(): end-to-end over a synthetic S03 gate bin ─────────────────────────
def _seed_s03(records, tmp_path, monkeypatch):
    """Write a synthetic S03 versioned directory with a freq_gt_10 bin."""
    run_dir = tmp_path / "artifacts" / "s03_frequency_gate" / "20990101-000000__deadbeef"
    run_dir.mkdir(parents=True)
    C.save_jsonl(run_dir / "freq_gt_10.jsonl", records)

    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    # Identity clustering so the test needs no embedding model.
    monkeypatch.setattr(
        S04, "cluster_objects_semantically",
        lambda objs, threshold=0.35: {o: o for o in objs},
    )


def test_run_produces_contract_shape_and_records_verbs(tmp_path, monkeypatch):
    records = [
        {
            "target_concept": "CNN",
            "corpus_frequency": 42,
            "consolidated_definitions": [
                "A neural network that uses convolution for feature extraction.",
                "A model that applies pooling layers.",
                "A standalone phrase with no verb.",
            ],
        },
    ]
    _seed_s03(records, tmp_path, monkeypatch)

    out_path = S04.run()
    assert Path(out_path).is_file()

    db = json.loads(Path(out_path).read_text())
    assert "CNN" in db
    entry = db["CNN"]
    # {f, td, cov, props, unt, consolidated_definitions} contract.
    assert set(entry.keys()) == {"f", "td", "cov", "props", "unt",
                                 "consolidated_definitions"}
    assert entry["f"] == 42
    assert entry["td"] == 3
    # R20.3: the consolidated definitions are carried through so S11 can emit
    # skos:definition/rdfs:comment (previously dropped, leaving coverage at 0).
    assert entry["consolidated_definitions"] == [
        "A neural network that uses convolution for feature extraction.",
        "A model that applies pooling layers.",
        "A standalone phrase with no verb.",
    ]
    # raw mined verbs recorded under props[verb] (sub-property source, R23.1).
    assert "use" in entry["props"]
    # untreated definition tracked.
    assert "A standalone phrase with no verb." in entry["unt"]
    # target->{f,v,e} inner shape.
    for verb, targets in entry["props"].items():
        for target, meta in targets.items():
            assert set(meta.keys()) == {"f", "v", "e"}


def test_run_only_includes_gate_concepts_from_freq_gt_10_bin(tmp_path, monkeypatch):
    """S04 reads only the freq_gt_10 bin, so only gated concepts appear (R23.1)."""
    records = [
        {"target_concept": "HighFreq", "corpus_frequency": 99,
         "consolidated_definitions": ["A model that uses attention."]},
    ]
    _seed_s03(records, tmp_path, monkeypatch)
    out_path = S04.run()
    db = json.loads(Path(out_path).read_text())
    assert list(db.keys()) == ["HighFreq"]


def test_run_manifest_reports_metrics(tmp_path, monkeypatch):
    records = [
        {"target_concept": "CNN", "corpus_frequency": 42,
         "consolidated_definitions": ["A network that uses convolution."]},
    ]
    _seed_s03(records, tmp_path, monkeypatch)
    S04.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert "concepts_out" in counts
    assert "mean_coverage" in counts
    assert "distinct_verbs" in counts


def test_reruns_never_overwrite_prior_artifact(tmp_path, monkeypatch):
    records = [
        {"target_concept": "CNN", "corpus_frequency": 42,
         "consolidated_definitions": ["A network that uses convolution."]},
    ]
    _seed_s03(records, tmp_path, monkeypatch)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S04.run()
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    p2 = S04.run()

    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_require_latest_s03_dir_raises_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    with pytest.raises(FileNotFoundError):
        S04.require_latest_s03_dir()
