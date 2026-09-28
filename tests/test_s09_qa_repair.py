"""Logic + order/single-pass/reports tests for S09's QA/repair pass (Task 10 / 10.1).

Verifies the merged nine-operation pass and the mandated R11 behaviour:

  * S09 reads the latest S08 artifact once, runs the nine ops in memory in the
    FIXED R11.2 order, and writes ONE new versioned primary artifact (R11.1);
  * exactly TWO read-only audits land in reports/ (redundancy + validation) and
    are NOT the primary artifact (R11.3);
  * one pass per invocation — re-running yields a NEW versioned file rather than
    looping internally (R11.4);
  * a concept carrying only `literal_annotations` and no `props` is NEVER deleted
    during chain/ghost cleanup (R11.5);
  * the input S08 file is never mutated (R2.4);
  * node validation re-surfaces S08's non-subsumption flags for repair (R18.2);
  * the manifest records one line pointing at the primary artifact + reports.

The LLM client is ALWAYS mocked (see :class:`FakeClient`) so tests are fully
offline and deterministic.

Run:  pytest test_result/pipeline_v2/tests/test_s09_qa_repair.py
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
import s09_qa_repair as S09  # noqa: E402


# ── Mocked LLM client (no network) ──────────────────────────────────────────
class _DailyQuotaError(Exception):
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


def _install_client(monkeypatch, responder):
    monkeypatch.setattr(C, "_LLM_CLIENT", FakeClient(responder))
    monkeypatch.setattr(C, "_LLM_CACHES", {})


def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    monkeypatch.setattr(C, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    (tmp_path / "caches").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)


def _seed_s08(db, tmp_path):
    d = tmp_path / "artifacts" / "s08_build_taxonomy"
    d.mkdir(parents=True)
    p = d / "20990101-000000__deadbeef.json"
    p.write_text(json.dumps(db), encoding="utf-8")
    return p


def _skeleton_nodes():
    """The injected skeleton spine an S08 artifact carries."""
    nodes = {}
    for node, parent in C.SKELETON.items():
        nodes[node] = {
            'f': 0, 'td': 0, 'cov': 1.0, 'props': {},
            'literal_annotations': [], 'taxonomy_parent': parent,
            'is_intermediary': True, 'is_skeleton': True,
        }
    return nodes


def _make_db():
    """A synthetic S08-shaped DB exercising each QA operation."""
    db = _skeleton_nodes()
    db.update({
        # normal concept under a valid leaf.
        "cnn": {
            "f": 5, "td": 5, "cov": 1.0,
            "props": {"processesData": {"pixels": {"f": 3, "v": 3.0, "e": "e"}}},
            "literal_annotations": [], "taxonomy_parent": "ML_Model",
        },
        # concept with a BROKEN chain (parent missing from db) -> op1 fixes it.
        "kalman_filter": {
            "f": 2, "td": 2, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "Ghost_Parent",
        },
        # concept FLOATING under owl:Thing -> op3 rescues it.
        "wavelet_transform": {
            "f": 2, "td": 2, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "owl:Thing",
        },
        # literal-annotation-only concept floating -> LLM says DELETE but R11.5
        # guard MUST keep it (never soft-deleted).
        "legacy_annotation_concept": {
            "f": 0, "td": 1, "cov": 1.0, "props": {},
            "literal_annotations": [
                {"prop": "hasComponent", "value": "widget",
                 "weight": 1, "raw_verbs": ["use"]}
            ],
            "taxonomy_parent": "owl:Thing",
        },
        # S08 flagged this as a non-subsumption edge -> op8 re-surfaces it (R18.2).
        "backpropagation": {
            "f": 3, "td": 3, "cov": 1.0,
            "props": {"optimizes": {"loss": {"f": 1, "v": 1.0, "e": "e"}}},
            "literal_annotations": [], "taxonomy_parent": "ML_Model",
            "non_subsumption_flag": True, "non_subsumption_relation": "used_by",
        },
    })
    return db


def _responder(*, contents):
    """Route each S09 LLM sub-step by inspecting its prompt text."""
    text = contents if isinstance(contents, str) else str(contents)

    # OP3 rescue: destination map. Mark the literal-only concept DELETE to prove
    # the R11.5 guard protects it; route the real floater to a valid leaf.
    if "5 FOUNDATIONAL DOMAINS (Top-Level)" in text and "DELETE" in text:
        out = {}
        if "wavelet_transform" in text:
            out["wavelet_transform"] = "ML_Algorithm"
        if "legacy_annotation_concept" in text:
            out["legacy_annotation_concept"] = "DELETE"
        return _resp(json.dumps(out))

    # OP1 broken-chain fix: route kalman_filter to a valid parent.
    if "broken hierarchy chains" in text:
        out = {}
        if "kalman_filter" in text:
            out["kalman_filter"] = "ML_Algorithm"
        return _resp(json.dumps(out))

    # OP8 node validation audit: report no issues (keeps the pass simple).
    if "performing quality assurance on an ontology node" in text:
        return _resp(json.dumps({"has_issues": False}))

    # Any other LLM sub-step (orphan routing, resubdivision, refinement,
    # semantic-dup fixer, re-parent, grouping): empty mapping is a valid answer
    # (callers apply their own fallback), matching the source scripts.
    return _resp(json.dumps({}))


# ── run(): full QA pass over a synthetic S08 DB ─────────────────────────────
def test_single_artifact_two_reports_and_literal_survival(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    src = _make_db()
    in_path = _seed_s08(src, tmp_path)
    _install_client(monkeypatch, _responder)

    out_path = S09.run()

    # R11.1: ONE primary artifact written and returned.
    assert Path(out_path).is_file()
    art_dir = tmp_path / "artifacts" / "s09_qa_repair"
    assert len(list(art_dir.glob("*.json"))) == 1

    # R11.3: exactly TWO read-only audits in reports/ (redundancy + validation),
    # and neither lives under artifacts/.
    reports = sorted(p.name for p in (tmp_path / "reports").glob("*.json"))
    assert len(reports) == 2
    assert any(".redundancy.json" in n for n in reports)
    assert any(".validation.json" in n for n in reports)

    db = json.loads(Path(out_path).read_text())

    # R11.5: literal-annotation-only concept survived — NOT soft-deleted.
    assert "legacy_annotation_concept" in db
    assert not db["legacy_annotation_concept"].get("is_noise")
    assert db["legacy_annotation_concept"]["literal_annotations"]

    # OP1 fixed the broken chain (Ghost_Parent -> a valid parent).
    assert db["kalman_filter"]["taxonomy_parent"] != "Ghost_Parent"
    # OP3 rescued the real floater off owl:Thing.
    assert db["wavelet_transform"]["taxonomy_parent"] != "owl:Thing"


def test_validation_audit_records_s08_non_subsumption_flags(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s08(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)

    S09.run()

    val_report = next((tmp_path / "reports").glob("*.validation.json"))
    audit = json.loads(val_report.read_text())
    # R18.2: S08's non_subsumption flag was re-surfaced in the audit.
    assert "_s08_non_subsumption_flags" in audit
    assert audit["_s08_non_subsumption_flags"].get("backpropagation") == "used_by"


def test_input_file_not_mutated(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    in_path = _seed_s08(_make_db(), tmp_path)
    before = in_path.read_bytes()
    _install_client(monkeypatch, _responder)
    S09.run()
    assert in_path.read_bytes() == before


def test_reruns_never_overwrite_no_internal_loop(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s08(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S09.run()
    # New RUN_ID + clear the resumable checkpoint so the second pass reruns.
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    ckpt = tmp_path / "caches" / "s09_qa_repair" / "map_cache.json"
    if ckpt.is_file():
        ckpt.unlink()
    p2 = S09.run()

    # R11.4: a re-run produces a NEW versioned file (both retained).
    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_manifest_records_one_line_with_report_paths(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s08(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)
    S09.run()

    lines = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["stage"] == "s09_qa_repair"
    assert rec["counts"]["nodes_total"] >= 1
    # The two read-only reports are referenced from the manifest's extra field.
    assert ".redundancy.json" in rec["extra"]["redundancy_report"]
    assert ".validation.json" in rec["extra"]["validation_report"]


def test_run_raises_when_no_s08_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        S09.run()


# ── pause: mid-run QuotaExhausted leaves NO primary artifact ────────────────
def test_pause_writes_no_artifact(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    # Give op1 a broken-chain concept so it makes an LLM call we can fail on.
    _seed_s08(_make_db(), tmp_path)

    def responder(*, contents):
        text = contents if isinstance(contents, str) else str(contents)
        if "broken hierarchy chains" in text:
            raise _DailyQuotaError()
        return _responder(contents=contents)

    _install_client(monkeypatch, responder)

    with pytest.raises(SystemExit) as ei:
        S09.run()
    assert ei.value.code == 0

    art_dir = tmp_path / "artifacts" / "s09_qa_repair"
    assert not art_dir.exists() or list(art_dir.glob("*.json")) == []
    manifest = tmp_path / "manifest.jsonl"
    if manifest.exists():
        assert '"s09_qa_repair"' not in manifest.read_text()


# ── Cycle guard (self-loops + longer cycles) — R11/R18 acyclic guarantee ─────

def test_break_subclass_cycles_fixes_self_loops_and_cycles():
    """S09's final guard reattaches self-loops and cycle members to owl:Thing.

    Regression for the OP9 merge/rename bug that pointed a survivor at itself,
    which S12 flagged as subClassOf cycles (hard fail).
    """
    db = {
        # a reachable spine so healthy nodes stay put
        "Computer_Science": {"taxonomy_parent": "owl:Thing", "is_skeleton": True},
        "Machine_Learning": {"taxonomy_parent": "Computer_Science", "is_skeleton": True},
        "ML_Model": {"taxonomy_parent": "Machine_Learning"},
        "generative_model": {"taxonomy_parent": "generative_model"},   # self-loop
        # 2-cycle: A -> B -> A
        "A": {"taxonomy_parent": "B"},
        "B": {"taxonomy_parent": "A"},
        # healthy chain must be left untouched (reaches Computer_Science)
        "cnn": {"taxonomy_parent": "ML_Model"},
    }
    res = S09._break_subclass_cycles(db)

    assert res["self_loops_fixed"] == 1
    assert res["cycles_broken"] >= 1
    # No node is its own parent anymore.
    assert all(v["taxonomy_parent"] != k for k, v in db.items())
    # The detached self-loop/cycle members are re-anchored by the root sweep so
    # they reach a top-level domain rather than dangling at owl:Thing.
    assert db["generative_model"]["taxonomy_parent"] != "generative_model"
    assert db["generative_model"]["taxonomy_parent"] != "owl:Thing"
    assert res["reanchored_to_root"] >= 1
    # The healthy edge is preserved (it already reaches a root via ML_Model).
    assert db["cnn"]["taxonomy_parent"] == "ML_Model"


def test_merge_concepts_never_creates_self_parent():
    """Merging a node's own parent into it must not leave the survivor self-parented."""
    db = {
        "Core_Generative_Model": {"taxonomy_parent": "ML_Model", "props": {}},
        "generative_model": {"taxonomy_parent": "Core_Generative_Model", "props": {}},
    }
    S09._merge_concepts(db, keep_name="generative_model",
                        discard_name="Core_Generative_Model")
    assert "Core_Generative_Model" not in db
    assert db["generative_model"]["taxonomy_parent"] != "generative_model"
    # Survivor inherits the discarded parent's former parent.
    assert db["generative_model"]["taxonomy_parent"] == "ML_Model"
