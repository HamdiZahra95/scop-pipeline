"""Logic + resume/pause tests for S08's is-a taxonomy build (Task 9 / 9.1).

Verifies the ported analytical logic and the mandated port+extend changes:

  * the shared SKELETON is injected and every concept is anchored under it
    (skeleton anchoring, R6.1),
  * the tree reaches depth > 1 (concepts sit below an ML leaf which sits below
    Machine_Learning — genuine multi-level subsumption, R18.1),
  * a concept carrying ONLY `literal_annotations` (no `props`, f==0) SURVIVES the
    clean-slate step (R11.5),
  * a non-is-a assignment is placed but flagged for S09 (R18.2),
  * `run()` reads the latest S07 artifact, writes ONE versioned artifact, and
    returns it (R2.3, R13.3); the input file is never mutated (R2.4); re-runs
    never overwrite (R1.1); the manifest reports depth/intermediary/floater
    counts (R4.3),
  * resume: an interrupted run resumes from the checkpoint and never repeats a
    completed batch's LLM calls (R8.2, R19.5),
  * pause: a mid-run QuotaExhausted leaves the checkpoint but NO primary artifact
    and NO manifest line (R8.4, R19.4, R19.6).

The LLM client is ALWAYS mocked (see :class:`FakeClient`) so tests are fully
offline and deterministic.

Run:  pytest test_result/pipeline_v2/tests/test_s08_build_taxonomy.py
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
import s08_build_taxonomy as S08  # noqa: E402


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
    client = FakeClient(responder)
    monkeypatch.setattr(C, "_LLM_CLIENT", client)
    monkeypatch.setattr(C, "_LLM_CACHES", {})


def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    (tmp_path / "caches").mkdir(parents=True, exist_ok=True)


def _seed_s07(db, tmp_path):
    d = tmp_path / "artifacts" / "s07_ground_to_master"
    d.mkdir(parents=True)
    p = d / "20990101-000000__deadbeef.json"
    p.write_text(json.dumps(db), encoding="utf-8")
    return p


def _make_db():
    """Concepts with props, a literal-annotation-only concept, and a flagged one."""
    return {
        "cnn": {
            "f": 5, "td": 5, "cov": 1.0,
            "props": {"use": {"filter": {"f": 3, "v": {"filter": 3}, "e": "e"}}},
            "literal_annotations": [],
            "consolidated_definitions": ["a convolutional neural network"],
        },
        "svm": {
            "f": 4, "td": 4, "cov": 1.0,
            "props": {"use": {"margin": {"f": 1, "v": {"margin": 1}, "e": "e"}}},
            "literal_annotations": [],
        },
        # literal-annotation-only concept: NO props, f==0. Must survive (R11.5).
        "bert": {
            "f": 0, "td": 3, "cov": 1.0, "props": {},
            "literal_annotations": [
                {"prop": "hasComponent", "value": "transformer",
                 "weight": 2, "raw_verbs": ["use"]}
            ],
            "consolidated_definitions": ["a transformer language model"],
        },
        # this one the LLM will report as part_of → flagged, not is_a.
        "gradient": {
            "f": 2, "td": 2, "cov": 1.0,
            "props": {"has": {"slope": {"f": 1, "v": {"slope": 1}, "e": "e"}}},
            "literal_annotations": [],
        },
    }


# Fixed assignment map for the mocked LLM (concept -> (category, relation)).
_ASSIGN = {
    "cnn": ("ML_Model", "is_a"),
    "svm": ("ML_Model", "is_a"),
    "bert": ("ML_Model", "is_a"),
    "gradient": ("ML_Foundations_and_Theory", "part_of"),
}


def _responder(*, contents):
    """Answer assignment batches and subdivision requests from the prompt text."""
    text = contents if isinstance(contents, str) else str(contents)
    if '"assignments"' in text and "IS A KIND OF" in text and "relation you see" in text:
        # Initial ML-leaf assignment batch: assign every known concept present.
        assigns = [
            {"concept": c, "category": cat, "relation": rel}
            for c, (cat, rel) in _ASSIGN.items() if f"'{c}'" in text or f'"{c}"' in text
        ]
        return _resp(json.dumps({"assignments": assigns}))
    if '"subcategories"' in text:
        # Subdivision: put everything into a single Core_<parent> bucket so the
        # tree gains a level without needing to know the concept list.
        # Extract the parent name from the prompt.
        import re
        m = re.search(r'parent category is: "([^"]+)"', text)
        parent = m.group(1) if m else "Unknown"
        m2 = re.search(r'concepts assigned to this category are: (\[.*?\])', text, re.S)
        concepts = []
        if m2:
            try:
                concepts = json.loads(m2.group(1).replace("'", '"'))
            except Exception:
                concepts = []
        return _resp(json.dumps({
            "subcategories": [{"name": f"Core_{parent}", "concepts": concepts}]
        }))
    if '"assignments"' in text:
        # Leftover rescue (no concepts expected in these tests).
        return _resp(json.dumps({"assignments": []}))
    return _resp("{}")


# ── run(): full taxonomy build over a synthetic S07 DB ──────────────────────
def test_skeleton_anchoring_depth_and_literal_survival(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    src = _make_db()
    in_path = _seed_s07(src, tmp_path)
    _install_client(monkeypatch, _responder)

    out_path = S08.run()
    assert Path(out_path).is_file()
    db = json.loads(Path(out_path).read_text())

    # Skeleton anchoring: the populated skeleton spine is present and anchored
    # exactly as the shared SKELETON prescribes. (Empty skeleton domains with no
    # descendants are pruned as empty intermediaries by the audit — faithful to
    # the original's dead-branch pruning — so we assert the spine that carries
    # this run's concepts.)
    for node in ["Computer_Science", "Artificial_Intelligence", "Machine_Learning",
                 "ML_Model", "ML_Foundations_and_Theory"]:
        assert node in db, f"skeleton spine node {node} missing"
        assert db[node]["taxonomy_parent"] == C.SKELETON[node]
        assert db[node].get("is_skeleton") is True

    # Literal-annotation-only concept survived the clean slate (R11.5).
    assert "bert" in db
    assert db["bert"]["props"] == {}
    assert db["bert"]["literal_annotations"]

    # Definitions carried through unchanged (R20.4).
    assert db["bert"]["consolidated_definitions"] == ["a transformer language model"]

    # Depth > 1: a concept -> Core_ML_Model -> ML_Model -> Machine_Learning ...
    def depth(node):
        d = 0
        seen = set()
        while True:
            parent = db.get(node, {}).get("taxonomy_parent")
            if not parent or parent == "owl:Thing" or parent not in db or node in seen:
                return d
            seen.add(node)
            node = parent
            d += 1
    assert depth("cnn") > 1

    # Non-subsumption assignment flagged for S09 (R18.2).
    assert db["gradient"].get("non_subsumption_flag") is True
    assert db["gradient"].get("non_subsumption_relation") == "part_of"
    # is-a assignment is NOT flagged.
    assert "non_subsumption_flag" not in db["cnn"]


def test_input_file_not_mutated(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    in_path = _seed_s07(_make_db(), tmp_path)
    before = in_path.read_bytes()
    _install_client(monkeypatch, _responder)
    S08.run()
    assert in_path.read_bytes() == before


def test_reruns_never_overwrite(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s07(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S08.run()
    # New RUN_ID and clear the resumable checkpoint so the second run rebuilds.
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    (tmp_path / "caches" / "s08_build_taxonomy" / "map_cache.json").unlink()
    p2 = S08.run()
    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_manifest_reports_taxonomy_counts(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s07(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)
    S08.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert "max_depth" in counts and counts["max_depth"] >= 1
    assert "intermediary_count" in counts
    assert "floater_count" in counts
    assert counts["non_subsumption_flagged"] == 1


def test_run_raises_when_no_s07_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        S08.run()


# ── resume: completed batches are never re-queried ──────────────────────────
def test_resume_skips_completed_batches(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s07(_make_db(), tmp_path)

    calls = {"assign": 0}

    def counting_responder(*, contents):
        text = contents if isinstance(contents, str) else str(contents)
        if "relation you see" in text:
            calls["assign"] += 1
        return _responder(contents=contents)

    _install_client(monkeypatch, counting_responder)

    S08.run()
    first = calls["assign"]
    assert first == 1  # one batch (< BATCH_SIZE concepts)

    # Second run: the assignment batch is checkpointed, so no new assign call.
    # (subdivision uses call_llm's own cache, also warm.)
    S08.run()
    assert calls["assign"] == first


# ── pause: mid-run QuotaExhausted leaves checkpoint but no artifact ─────────
def test_pause_writes_no_artifact_but_keeps_checkpoint(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    # Many concepts so there are >=2 assignment batches; pause on the 2nd.
    big = {f"c{i}": {"f": 1, "td": 1, "cov": 1.0,
                     "props": {"use": {"x": {"f": 1, "v": {"x": 1}, "e": "e"}}},
                     "literal_annotations": []}
           for i in range(150)}
    _seed_s07(big, tmp_path)

    state = {"assign": 0}

    def responder(*, contents):
        text = contents if isinstance(contents, str) else str(contents)
        if "relation you see" in text:
            state["assign"] += 1
            if state["assign"] >= 2:
                raise _DailyQuotaError()
            # First batch: assign all present concepts to ML_Model.
            import re
            names = re.findall(r"'(c\d+)'", text)
            return _resp(json.dumps({"assignments": [
                {"concept": n, "category": "ML_Model", "relation": "is_a"}
                for n in names
            ]}))
        return _responder(contents=contents)

    _install_client(monkeypatch, responder)

    with pytest.raises(SystemExit) as ei:
        S08.run()
    assert ei.value.code == 0

    art_dir = tmp_path / "artifacts" / "s08_build_taxonomy"
    assert not art_dir.exists() or list(art_dir.glob("*.json")) == []
    manifest = tmp_path / "manifest.jsonl"
    if manifest.exists():
        assert '"s08_build_taxonomy"' not in manifest.read_text()
    checkpoint = tmp_path / "caches" / "s08_build_taxonomy" / "map_cache.json"
    assert checkpoint.is_file()
    # Exactly one batch (the first) completed before the pause.
    assert len(json.loads(checkpoint.read_text())) == 1


# ── Knowledge-guided reference hints in the assignment prompt (mode==guided) ─
def test_guided_injects_reference_hints_into_prompt(tmp_path, monkeypatch):
    """In guided mode the Step-2 assignment prompt carries reference is-a hints
    for reference-known concepts, and none for unknown ones; baseline has none."""
    _redirect(tmp_path, monkeypatch)
    db = {
        "convolutional neural network": {
            "f": 20, "td": 1, "cov": 1.0, "props": {}, "unt": [],
            "literal_annotations": [], "consolidated_definitions": [],
        },
        "some novel frontier concept": {
            "f": 20, "td": 1, "cov": 1.0, "props": {}, "unt": [],
            "literal_annotations": [], "consolidated_definitions": [],
        },
    }
    _seed_s07(db, tmp_path)

    monkeypatch.setattr(C, "SCOP_MODE", "guided", raising=False)
    import knowledge as K
    monkeypatch.setattr(K, "load", lambda force=False: None)
    monkeypatch.setattr(K, "concepts", {"x": "y"}, raising=False)

    def fake_match(label, definition=None, use_semantic=True):
        if C.get_uri_name(label) == "convolutional_neural_network":
            return K.KnowledgeMatch("exact", "convolutional neural network",
                                    "convolutional_neural_network",
                                    "artificial_neural_network", 1.0)
        return K.KnowledgeMatch("none")
    monkeypatch.setattr(K, "match", fake_match)

    seen_prompts = []

    def responder(*, contents):
        seen_prompts.append(contents)
        return _resp(json.dumps({"assignments": [
            {"concept": "convolutional neural network", "category": "ML_Model", "relation": "is_a"},
            {"concept": "some novel frontier concept", "category": "ML_Model", "relation": "is_a"},
        ]}))
    _install_client(monkeypatch, responder)

    S08.run()

    assignment_prompts = [p for p in seen_prompts if "orthogonal categories" in p]
    assert assignment_prompts, "no assignment prompt captured"
    joined = "\n".join(assignment_prompts)
    # hint present for the reference-known concept, absent for the unknown one
    assert "artificial_neural_network" in joined
    assert "Reference knowledge" in joined
    assert "some novel frontier concept" not in joined.split("Reference knowledge")[1] \
        if "Reference knowledge" in joined else True


def test_baseline_has_no_reference_hints(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    db = {
        "convolutional neural network": {
            "f": 20, "td": 1, "cov": 1.0, "props": {}, "unt": [],
            "literal_annotations": [], "consolidated_definitions": [],
        },
    }
    _seed_s07(db, tmp_path)
    monkeypatch.setattr(C, "SCOP_MODE", "baseline", raising=False)

    seen = []

    def responder(*, contents):
        seen.append(contents)
        return _resp(json.dumps({"assignments": [
            {"concept": "convolutional neural network", "category": "ML_Model", "relation": "is_a"}]}))
    _install_client(monkeypatch, responder)

    S08.run()
    assert not any("Reference knowledge" in p for p in seen)


# ── Regression: audit depth must not blow the stack on a parent-chain cycle ──
def test_audit_depth_survives_a_parent_cycle():
    """audit_and_repair_taxonomy computes finite depths even if a bad placement
    left a cycle in taxonomy_parent (would previously RecursionError)."""
    db = dict(S08._intermediary_node("owl:Thing", skeleton=True) for _ in range(0))  # noqa
    db = {}
    # a 2-cycle A -> B -> A among non-skeleton concepts
    db["A"] = {"f": 1, "td": 1, "cov": 1.0, "props": {}, "literal_annotations": [],
               "taxonomy_parent": "B"}
    db["B"] = {"f": 1, "td": 1, "cov": 1.0, "props": {}, "literal_annotations": [],
               "taxonomy_parent": "A"}
    # a healthy skeleton node so the function has something normal too
    db["Machine_Learning"] = {"f": 0, "td": 0, "cov": 1.0, "props": {},
                              "literal_annotations": [], "taxonomy_parent": "owl:Thing",
                              "is_skeleton": True}
    # must return counts without raising RecursionError
    audit = S08.audit_and_repair_taxonomy(db)
    assert isinstance(audit, dict) and "max_depth" in audit
