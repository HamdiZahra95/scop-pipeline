"""Logic + Property-10-seed tests for S07's grounding gate (Task 6.1 / R12, R20.4).

Verifies the ported grounding logic and the mandated port changes:

  * a target whose normalized form matches a verified master concept is KEPT as
    a formal edge under the canonical master name (R12.1),
  * a target NOT in the master list is DEMOTED to a `literal_annotations` entry
    of the form `{prop, value, weight, raw_verbs}` (R12.1),
  * multiple raw targets that map to the same canonical master name have their
    frequencies and raw-verb counts merged onto one edge (Port),
  * `consolidated_definitions` (and every other non-`props` key) are carried
    through UNCHANGED — grounding never drops definitions (R20.4),
  * the master whitelist prefers the latest S02 output and falls back to the
    frozen seed when S02 is absent (design R12 decision),
  * `run()` reads the latest S06 artifact, writes a versioned artifact, and
    returns it (R2.3, R13.3); re-runs never overwrite (R1.1),
  * the manifest records kept-edge vs demoted-edge counts.

Property 10 seed (R20.4): for every concept, the set of `consolidated_definitions`
at the S07 OUTPUT is a superset-or-equal of the set at the S07 INPUT — definitions
are never silently dropped by grounding.

**Validates: Requirements 12.1, 20.4**

Run:  pytest test_result/pipeline_v2/tests/test_s07_ground_to_master.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s07_ground_to_master as S07  # noqa: E402


# ── pure helper: normalization (Port logic) ─────────────────────────────────
def test_normalize_concept_lowercases_strips_and_singularizes():
    assert S07.normalize_concept("  Neural Networks ") == "neural network"
    assert S07.normalize_concept("CNN") == "cnn"
    # -ss is NOT stripped (guard against "loss" -> "los")
    assert S07.normalize_concept("Loss") == "loss"
    # too-short words keep their trailing 's'
    assert S07.normalize_concept("is") == "is"


# ── fixtures / seeding helpers ──────────────────────────────────────────────
def _seed_master_s02(master_names, tmp_path):
    """Write a synthetic latest-S02 artifact acting as the master whitelist."""
    s02_dir = tmp_path / "artifacts" / "s02_consolidate"
    s02_dir.mkdir(parents=True)
    payload = [{"target_concept": n, "corpus_frequency": 5,
                "consolidated_definitions": []} for n in master_names]
    (s02_dir / "20990101-000000__cafebabe.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _seed_s06(db, tmp_path):
    """Write a synthetic latest-S06 artifact (the cleaned property DB)."""
    s06_dir = tmp_path / "artifacts" / "s06_clean_vocab"
    s06_dir.mkdir(parents=True)
    (s06_dir / "20990101-000000__deadbeef.json").write_text(
        json.dumps(db), encoding="utf-8"
    )


def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")


def _make_db():
    """A property DB with one verified target and one unverified target."""
    return {
        "CNN": {
            "f": 42, "td": 3, "cov": 0.9,
            "consolidated_definitions": [
                "A convolutional neural network used for image classification.",
                "A deep model that processes images.",
            ],
            "props": {
                # 'image' is in the master list -> KEEP as formal edge.
                "process": {"image": {"f": 3, "v": {"image": 3}, "e": "ex1"}},
                # 'magic dust' is NOT in the master list -> DEMOTE to literal.
                "use": {"magic dust": {"f": 1, "v": {"sprinkle": 1}, "e": "ex2"}},
            },
            "unt": ["some untreated def"],
        },
    }


# ── run(): grounding behavior over a synthetic S06 property DB ───────────────
def test_verified_target_kept_unverified_demoted(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image", "kernel"], tmp_path)
    _seed_s06(_make_db(), tmp_path)

    out_path = S07.run()
    assert Path(out_path).is_file()
    db = json.loads(Path(out_path).read_text())
    entry = db["CNN"]

    # verified 'image' edge kept as a formal edge.
    assert "process" in entry["props"]
    assert "image" in entry["props"]["process"]
    # unverified 'magic dust' demoted, no longer a formal edge.
    assert "use" not in entry["props"]
    # demoted literal annotation has the mandated shape.
    la = entry["literal_annotations"]
    assert len(la) == 1
    assert set(la[0].keys()) == {"prop", "value", "weight", "raw_verbs"}
    assert la[0]["prop"] == "use"
    assert la[0]["value"] == "magic dust"
    assert la[0]["weight"] == 1
    assert la[0]["raw_verbs"] == ["sprinkle"]


def test_definitions_carried_through_unchanged(tmp_path, monkeypatch):
    """R20.4: consolidated_definitions (and other keys) survive grounding."""
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image"], tmp_path)
    src = _make_db()
    _seed_s06(src, tmp_path)

    out_path = S07.run()
    db = json.loads(Path(out_path).read_text())
    assert db["CNN"]["consolidated_definitions"] == \
        src["CNN"]["consolidated_definitions"]
    # other bookkeeping preserved verbatim.
    for key in ("f", "td", "cov", "unt"):
        assert db["CNN"][key] == src["CNN"][key]


def test_multiple_raw_targets_merge_onto_canonical(tmp_path, monkeypatch):
    """Two raw targets normalizing to the same master concept merge into one edge."""
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image"], tmp_path)
    db = {
        "X": {
            "f": 1, "td": 1, "cov": 1.0, "consolidated_definitions": [],
            "props": {
                "process": {
                    "image": {"f": 2, "v": {"image": 2}, "e": "e1"},
                    # 'images' normalizes to 'image' (naive singular).
                    "images": {"f": 3, "v": {"images": 3}, "e": "e2"},
                }
            },
            "unt": [],
        }
    }
    _seed_s06(db, tmp_path)

    out_path = S07.run()
    out = json.loads(Path(out_path).read_text())
    edges = out["X"]["props"]["process"]
    assert set(edges.keys()) == {"image"}      # merged onto canonical master name
    assert edges["image"]["f"] == 5            # 2 + 3 frequencies merged
    assert edges["image"]["v"] == {"image": 2, "images": 3}


def test_falls_back_to_seed_when_no_s02(tmp_path, monkeypatch):
    """With no S02 output, the frozen seed/gemma_payload.json is used."""
    _redirect(tmp_path, monkeypatch)
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir(parents=True)
    (seed_dir / "gemma_payload.json").write_text(
        json.dumps([{"target_concept": "image"}]), encoding="utf-8"
    )
    monkeypatch.setattr(C, "SEED", seed_dir)
    _seed_s06(_make_db(), tmp_path)

    out_path = S07.run()
    out = json.loads(Path(out_path).read_text())
    # 'image' still grounded from the seed master list.
    assert "image" in out["CNN"]["props"]["process"]
    # manifest records the seed as the master source.
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    rec = json.loads(line)
    assert "gemma_payload.json" in rec["extra"]["master_source"]


def test_manifest_reports_kept_and_demoted_counts(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image"], tmp_path)
    _seed_s06(_make_db(), tmp_path)
    S07.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert counts["kept_edges"] == 1
    assert counts["demoted_edges"] == 1
    assert counts["concepts"] == 1


def test_reruns_never_overwrite_prior_artifact(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image"], tmp_path)
    _seed_s06(_make_db(), tmp_path)
    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S07.run()
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    p2 = S07.run()
    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_run_raises_when_no_s06_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image"], tmp_path)
    with pytest.raises(FileNotFoundError):
        S07.run()


# ── Property 10 seed: definitions preserved through S07 (R20.4) ─────────────
# Generator: random property DBs whose targets are drawn from a small pool that
# straddles the master whitelist (some verified, some not), each concept
# carrying a random set of consolidated_definitions. The property asserts the
# output definition set ⊇ the input definition set for every concept.

_defs = st.lists(st.text(min_size=1, max_size=12), max_size=5, unique=True)
_targets = st.sampled_from(["image", "kernel", "magic dust", "widget", "images"])
_verbs = st.sampled_from(["process", "use", "transforms", "optimizes"])


@st.composite
def _concept(draw):
    props = {}
    n_verbs = draw(st.integers(min_value=0, max_value=3))
    for _ in range(n_verbs):
        verb = draw(_verbs)
        tgt = draw(_targets)
        props.setdefault(verb, {})[tgt] = {
            "f": draw(st.integers(min_value=1, max_value=9)),
            "v": {tgt: 1},
            "e": "ex",
        }
    return {
        "f": draw(st.integers(min_value=1, max_value=99)),
        "td": draw(st.integers(min_value=0, max_value=9)),
        "cov": 1.0,
        "consolidated_definitions": draw(_defs),
        "props": props,
        "unt": [],
    }


@st.composite
def _db(draw):
    names = draw(st.lists(st.text(min_size=1, max_size=8), min_size=1,
                          max_size=6, unique=True))
    return {name: draw(_concept()) for name in names}


@settings(max_examples=100, deadline=None)
@given(db=_db())
def test_property10_definitions_superset(db):
    """Property 10 seed: S07 output definitions ⊇ S07 input definitions (R20.4).

    State (ARTIFACTS/MANIFEST + a unique RUN_ID per example) is managed manually
    rather than via function-scoped fixtures, which Hypothesis does not reset
    between generated examples.
    """
    tmp_path = Path(tempfile.mkdtemp(prefix="s07_p10_"))
    saved = (C.ARTIFACTS, C.MANIFEST, C.SEED, C.RUN_ID)
    try:
        # Master whitelist grounds only 'image'/'images'/'kernel'; others demote.
        _seed_master_s02(["image", "kernel"], tmp_path)
        _seed_s06(db, tmp_path)
        C.ARTIFACTS = tmp_path / "artifacts"
        C.MANIFEST = tmp_path / "manifest.jsonl"
        C.RUN_ID = "20990101-000000"

        out_path = S07.run()
        out = json.loads(Path(out_path).read_text())

        for name, in_concept in db.items():
            in_defs = set(in_concept.get("consolidated_definitions", []))
            out_defs = set(out[name].get("consolidated_definitions", []))
            assert in_defs <= out_defs, (
                f"S07 dropped definitions for '{name}': "
                f"missing {in_defs - out_defs}"
            )
    finally:
        C.ARTIFACTS, C.MANIFEST, C.SEED, C.RUN_ID = saved
        shutil.rmtree(tmp_path, ignore_errors=True)


# ── Knowledge-guided grounding (mode == "guided") ───────────────────────────
def test_guided_reference_target_kept(tmp_path, monkeypatch):
    """A target absent from the corpus master list but present in the reference
    ontology is KEPT (not demoted) in guided mode."""
    _redirect(tmp_path, monkeypatch)
    # Corpus master list contains only 'image'; 'magic dust' is NOT in it.
    _seed_master_s02(["image"], tmp_path)
    _seed_s06(_make_db(), tmp_path)

    monkeypatch.setattr(C, "SCOP_MODE", "guided", raising=False)
    import knowledge as K
    # Reference contributes 'magic dust' as a verified concept.
    monkeypatch.setattr(K, "load", lambda force=False: None)
    monkeypatch.setattr(K, "concepts", {"magic_dust": "magic dust"}, raising=False)

    out_path = S07.run()
    db = json.loads(Path(out_path).read_text())
    entry = db["CNN"]
    # 'magic dust' now survives as a formal edge thanks to reference grounding.
    assert "use" in entry["props"]
    assert "magic dust" in entry["props"]["use"]


def test_baseline_reference_target_demoted(tmp_path, monkeypatch):
    """In baseline mode, the same reference-only target is demoted (unchanged)."""
    _redirect(tmp_path, monkeypatch)
    _seed_master_s02(["image"], tmp_path)
    _seed_s06(_make_db(), tmp_path)
    monkeypatch.setattr(C, "SCOP_MODE", "baseline", raising=False)

    out_path = S07.run()
    db = json.loads(Path(out_path).read_text())
    entry = db["CNN"]
    assert "use" not in entry["props"]   # demoted, as in the baseline test
