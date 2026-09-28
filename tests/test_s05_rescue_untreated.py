"""Logic + resume/pause tests for S05's untreated-definition rescue (Task 8 / 8.1).

Verifies the ported analytical logic and the mandated port+extend changes:

  * each concept's untreated definitions are batched, the LLM's (verb, target)
    extractions are lemmatized and appended to `props`, rescued definitions are
    dropped from `unt`, and coverage is recomputed (Port),
  * NEW (verb, target) frequencies are added onto existing S04 edges, matching
    the original in-place bookkeeping (Port),
  * concepts WITHOUT untreated definitions pass through unchanged,
  * `run()` reads the latest S04 artifact, writes ONE versioned artifact, and
    returns it (R2.3, R13.3); the input file is never mutated (R2.4); re-runs
    never overwrite (R1.1),
  * resume: an interrupted run resumes from the checkpoint and never repeats a
    completed concept's LLM calls (R8.2, R19.5),
  * pause: a mid-run QuotaExhausted leaves the checkpoint but NO primary artifact
    and NO manifest line (R8.4, R19.4, R19.6).

The LLM client is ALWAYS mocked (see :class:`FakeClient`) so tests are fully
offline and deterministic; the semantic clustering (SentenceTransformer) is
monkeypatched to identity so no embedding model is loaded.

Run:  pytest test_result/pipeline_v2/tests/test_s05_rescue_untreated.py
"""

import json
import sys
import types as _pytypes
from pathlib import Path

import pytest

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s05_rescue_untreated as S05  # noqa: E402


# ── Mocked LLM client (no network) ──────────────────────────────────────────
class _DailyQuotaError(Exception):
    """Provider error `common._classify_rate_error` classifies as daily quota."""
    def __init__(self):
        super().__init__(
            "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
            "'GenerateRequestsPerDay' (per day)."
        )


class _FakeModels:
    def __init__(self, responder):
        self._responder = responder

    def generate_content(self, *, model, contents, config):
        return self._responder(contents=contents)


class FakeClient:
    def __init__(self, responder):
        self.models = _FakeModels(responder)


def _resp(text):
    return _pytypes.SimpleNamespace(text=text)


def _extraction_json(verb, target, indices):
    return json.dumps(
        {"extractions": [{"verb": verb, "target": target, "indices": indices}]}
    )


def _install_client(monkeypatch, responder):
    """Route common.get_client()/call_llm to a mocked client and clear caches."""
    client = FakeClient(responder)
    monkeypatch.setattr(C, "_LLM_CLIENT", client)
    monkeypatch.setattr(C, "_LLM_CACHES", {})
    # Identity clustering so no SentenceTransformer is loaded.
    monkeypatch.setattr(
        S05, "cluster_objects_semantically",
        lambda objs, threshold=0.35: {o: o for o in objs},
    )


def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    (tmp_path / "caches").mkdir(parents=True, exist_ok=True)


def _seed_s04(db, tmp_path):
    s04_dir = tmp_path / "artifacts" / "s04_extract_properties"
    s04_dir.mkdir(parents=True)
    p = s04_dir / "20990101-000000__deadbeef.json"
    p.write_text(json.dumps(db), encoding="utf-8")
    return p


def _make_db():
    """One concept with untreated defs, one fully-covered concept (no `unt`)."""
    return {
        "CNN": {
            "f": 42, "td": 4, "cov": 0.5,
            "props": {
                "use": {"filter": {"f": 3, "v": {"filter": 3}, "e": "ex0"}},
            },
            "unt": [
                "A method that leverages kernels over the image.",
                "An approach exploiting spatial structure.",
            ],
        },
        "SVM": {
            "f": 10, "td": 1, "cov": 1.0,
            "props": {"use": {"margin": {"f": 1, "v": {"margin": 1}, "e": "e"}}},
            "unt": [],
        },
    }


# ── run(): rescue behavior over a synthetic S04 property DB ──────────────────
def test_rescue_appends_props_drops_unt_and_recomputes_coverage(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    src = _make_db()
    in_path = _seed_s04(src, tmp_path)

    # LLM resolves BOTH untreated defs of CNN as (extract, features) at idx 0 & 1.
    def responder(*, contents):
        return _resp(_extraction_json("extracts", "features", [0, 1]))

    _install_client(monkeypatch, responder)

    out_path = S05.run()
    assert Path(out_path).is_file()
    db = json.loads(Path(out_path).read_text())

    cnn = db["CNN"]
    # rescued verb/target appended (lemmatized 'extracts' -> 'extract').
    assert "extract" in cnn["props"]
    assert "features" in cnn["props"]["extract"]
    assert cnn["props"]["extract"]["features"]["f"] == 2   # both defs resolved
    # pre-existing S04 edge preserved.
    assert cnn["props"]["use"]["filter"]["f"] == 3
    # both untreated defs resolved -> empty unt, coverage recomputed to 1.0.
    assert cnn["unt"] == []
    assert cnn["cov"] == 1.0
    # concept with no untreated defs passes through unchanged.
    assert db["SVM"] == src["SVM"]


def test_input_file_not_mutated(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    in_path = _seed_s04(_make_db(), tmp_path)
    before = in_path.read_bytes()

    def responder(*, contents):
        return _resp(_extraction_json("extracts", "features", [0, 1]))

    _install_client(monkeypatch, responder)
    S05.run()
    assert in_path.read_bytes() == before


def test_reruns_never_overwrite_prior_artifact(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s04(_make_db(), tmp_path)

    def responder(*, contents):
        return _resp(_extraction_json("extracts", "features", [0, 1]))

    _install_client(monkeypatch, responder)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S05.run()
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    p2 = S05.run()
    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_manifest_reports_rescue_counts(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s04(_make_db(), tmp_path)

    def responder(*, contents):
        return _resp(_extraction_json("extracts", "features", [0, 1]))

    _install_client(monkeypatch, responder)
    S05.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert counts["concepts_total"] == 2
    assert counts["concepts_to_rescue"] == 1
    assert counts["extractions_added"] == 2
    assert counts["remaining_untreated"] == 0


def test_run_raises_when_no_s04_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        S05.run()


# ── resume: a completed concept is never re-queried on the next run ─────────
def test_resume_skips_completed_concepts(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s04(_make_db(), tmp_path)

    calls = {"n": 0}

    def responder(*, contents):
        calls["n"] += 1
        return _resp(_extraction_json("extracts", "features", [0, 1]))

    _install_client(monkeypatch, responder)

    # First run completes CNN (one batch = one LLM call).
    S05.run()
    first = calls["n"]
    assert first == 1

    # Second run: checkpoint holds CNN, so no new LLM call is made.
    S05.run()
    assert calls["n"] == first


# ── pause: mid-run QuotaExhausted leaves checkpoint but no artifact ─────────
def test_pause_writes_no_artifact_but_keeps_checkpoint(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    # Two concepts both needing rescue so one can complete before the pause.
    db = {
        "A": {"f": 5, "td": 1, "cov": 0.0, "props": {},
              "unt": ["def a leverages kernels"]},
        "B": {"f": 5, "td": 1, "cov": 0.0, "props": {},
              "unt": ["def b exploits structure"]},
    }
    _seed_s04(db, tmp_path)

    # First concept processed returns fine; the second raises daily quota.
    state = {"seen": 0}

    def responder(*, contents):
        state["seen"] += 1
        if state["seen"] >= 2:
            raise _DailyQuotaError()
        return _resp(_extraction_json("extracts", "features", [0]))

    _install_client(monkeypatch, responder)

    # exit_on_pause defaults to True (sys.exit(0)); patch run_resumable_stage's
    # exit behavior by catching SystemExit.
    with pytest.raises(SystemExit) as ei:
        S05.run()
    assert ei.value.code == 0

    # No primary artifact promoted.
    art_dir = tmp_path / "artifacts" / "s05_rescue_untreated"
    assert not art_dir.exists() or list(art_dir.glob("*.json")) == []
    # No manifest line for S05.
    manifest = tmp_path / "manifest.jsonl"
    if manifest.exists():
        assert '"s05_rescue_untreated"' not in manifest.read_text()
    # Checkpoint holds exactly the one concept completed before the pause.
    checkpoint = tmp_path / "caches" / "s05_rescue_untreated" / "map_cache.json"
    assert checkpoint.is_file()
    assert len(json.loads(checkpoint.read_text())) == 1
