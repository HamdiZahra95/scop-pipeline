"""Tests for S09a — semantic taxonomy re-homing (floaters + level refinement).

The LLM client is mocked and the SentenceTransformer fuzzy matcher is stubbed so
the whole suite runs offline and deterministically. Verifies:

  * the Taxonomy graph model (paths, descendants, cycle guard, level);
  * Phase 1 places a floater under the LLM's chosen domain, reusing an existing
    parent when found and creating one under the domain when not;
  * the acyclicity guard refuses a move that would create a cycle;
  * `_resolve_path` walks/creates a proposed path under the target domain;
  * `run()` reads latest S09, writes exactly one versioned artifact + manifest,
    never mutates its input, and leaves NO concept orphaned from the domains.
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

import common as C            # noqa: E402
import s10_taxonomy_rehome as S9A  # noqa: E402


# ── offline harness ──────────────────────────────────────────────────────────
class _FakeModels:
    def __init__(self, responder):
        self._responder = responder

    def generate_content(self, *, model, contents, config):
        return self._responder(contents=contents)


class FakeClient:
    def __init__(self, responder):
        self.models = _FakeModels(responder)


def _install_client(monkeypatch, responder):
    monkeypatch.setattr(C, "_LLM_CLIENT", FakeClient(responder))
    monkeypatch.setattr(C, "_LLM_CACHES", {})


def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    monkeypatch.setattr(C, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(C, "LLM_TRACE_PATH", tmp_path / "logs" / "llm_trace.jsonl")
    monkeypatch.setattr(C, "LLM_TRACE", True)
    (tmp_path / "caches").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)


def _stub_fuzzy_exact_only(monkeypatch):
    """Make _resolve_parent do EXACT-slug matching only (no model download)."""
    def _resolve(tax, proposed, domain):
        if not proposed:
            return None
        pslug = C.get_uri_name(proposed)
        if not pslug:
            return None
        for c in [domain] + sorted(tax.descendants(domain)):
            if C.get_uri_name(c) == pslug:
                return c
        return None
    monkeypatch.setattr(S9A, "_resolve_parent", _resolve)


def _skeleton():
    nodes = {}
    for node, parent in C.SKELETON.items():
        nodes[node] = {
            "f": 0, "td": 0, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": parent,
            "is_intermediary": True, "is_skeleton": True,
        }
    return nodes


def _seed_s09(db, tmp_path):
    d = tmp_path / "artifacts" / "s09_qa_repair"
    d.mkdir(parents=True)
    p = d / "20990101-000000__deadbeef.json"
    p.write_text(json.dumps(db), encoding="utf-8")
    return p


# ── graph model ──────────────────────────────────────────────────────────────
def test_taxonomy_paths_descendants_and_cycle_guard():
    db = dict(_skeleton())
    db["cnn"] = {"taxonomy_parent": "ML_Model"}
    tax = S9A.Taxonomy(db)

    # path_to_root reaches a domain
    assert "Computer_Science" in tax.path_to_root("cnn")
    assert tax.reaches_domain("cnn")
    assert tax.domain_of("cnn") == "Computer_Science"

    # ML_Model is a descendant of Machine_Learning; cnn under ML_Model
    assert "cnn" in tax.descendants("Machine_Learning")

    # set_parent refuses a cycle: attaching ML_Model under its own descendant cnn
    assert tax.set_parent("ML_Model", "cnn") is False
    # a legal move succeeds
    assert tax.set_parent("cnn", "ML_Algorithm") is True
    assert db["cnn"]["taxonomy_parent"] == "ML_Algorithm"


def test_phase1_reuses_existing_parent_and_creates_when_missing(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)   # isolate CACHES so resumable_map can't read real on-disk cache
    _stub_fuzzy_exact_only(monkeypatch)
    db = dict(_skeleton())
    db["ML_Model"]  # exists via skeleton
    # two floaters directly under owl:Thing
    db["concurrent_learning"] = {"taxonomy_parent": "owl:Thing"}
    db["some_new_thing"] = {"taxonomy_parent": "owl:Thing"}
    tax = S9A.Taxonomy(db)

    def responder(*, contents):
        # concurrent_learning -> existing ML_Model; some_new_thing -> brand new parent
        return _pytypes.SimpleNamespace(text=json.dumps({"placements": [
            {"concept": "concurrent_learning", "target_domain": "Computer_Science",
             "proposed_parent": "ML_Model"},
            {"concept": "some_new_thing", "target_domain": "Mathematics",
             "proposed_parent": "Fancy New Parent"},
        ]}))
    _install_client(monkeypatch, responder)
    monkeypatch.setattr(C, "_LLM_CACHES", {})

    res = S9A._phase1_floaters(tax)
    assert res["floaters_total"] == 2
    # existing parent reused
    assert db["concurrent_learning"]["taxonomy_parent"] == "ML_Model"
    # missing parent created under the chosen domain, concept attached under it
    assert db["some_new_thing"]["taxonomy_parent"] == "Fancy New Parent"
    assert db["Fancy New Parent"]["taxonomy_parent"] == "Mathematics"
    # both now reach a domain
    assert tax.reaches_domain("concurrent_learning")
    assert tax.reaches_domain("some_new_thing")


def test_resolve_path_creates_missing_segments(monkeypatch):
    _stub_fuzzy_exact_only(monkeypatch)
    db = dict(_skeleton())
    db["continual_learning"] = {"taxonomy_parent": "Machine_Learning"}
    tax = S9A.Taxonomy(db)

    parent = S9A._resolve_path(
        tax, "Computer_Science",
        ["Computer_Science", "Machine_Learning", "Learning_Paradigm"],
        "continual_learning")
    assert parent == "Learning_Paradigm"
    assert db["Learning_Paradigm"]["taxonomy_parent"] == "Machine_Learning"


def test_run_writes_one_artifact_and_no_orphans(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _stub_fuzzy_exact_only(monkeypatch)
    db = dict(_skeleton())
    db["floaty"] = {"taxonomy_parent": "owl:Thing"}
    in_path = _seed_s09(db, tmp_path)
    before = in_path.read_bytes()

    def responder(*, contents):
        text = contents if isinstance(contents, str) else str(contents)
        if "placements" in text or "orphaned concepts" in text:
            return _pytypes.SimpleNamespace(text=json.dumps({"placements": [
                {"concept": "floaty", "target_domain": "Computer_Science",
                 "proposed_parent": "Machine_Learning"}]}))
        # refinement: everything ok
        return _pytypes.SimpleNamespace(text=json.dumps({"decisions": []}))
    _install_client(monkeypatch, responder)
    monkeypatch.setattr(C, "_LLM_CACHES", {})
    monkeypatch.setattr(C, "RUN_ID", "20990101-000000")

    out_path = S9A.run()
    assert out_path.exists()
    # input untouched
    assert in_path.read_bytes() == before
    out = json.loads(out_path.read_text())
    tax = S9A.Taxonomy(out)
    orphans = [k for k, v in out.items()
               if isinstance(v, dict) and k != "__meta__"
               and k not in S9A.DOMAINS and not v.get("is_skeleton")
               and not tax.reaches_domain(k)]
    assert orphans == []
    assert out["floaty"]["taxonomy_parent"] in ("Machine_Learning",)


def test_refine_parses_flat_path_string_and_moves(tmp_path, monkeypatch):
    """A 'move' with a ' > '-delimited proposed_path re-homes the concept."""
    _redirect(tmp_path, monkeypatch)
    _stub_fuzzy_exact_only(monkeypatch)
    db = dict(_skeleton())
    # a mis-placed child directly under a domain that should move deeper
    db["continual_learning"] = {"taxonomy_parent": "Computer_Science"}
    tax = S9A.Taxonomy(db)

    def responder(*, contents):
        return _pytypes.SimpleNamespace(text=json.dumps({"decisions": [
            {"concept": "continual_learning", "decision": "move",
             "proposed_path": "Computer_Science > Machine_Learning > Learning_Paradigm"}]}))
    _install_client(monkeypatch, responder)
    monkeypatch.setattr(C, "_LLM_CACHES", {})

    moves = S9A._refine_children(tax, "Computer_Science", "Computer_Science",
                                 ["continual_learning"])
    assert moves == 1
    # created the intermediate and attached under it
    assert db["Learning_Paradigm"]["taxonomy_parent"] == "Machine_Learning"
    assert db["continual_learning"]["taxonomy_parent"] == "Learning_Paradigm"
    assert db["continual_learning"].get("rehomed") is True


def test_materialize_referenced_only_creates_floaters():
    """Names referenced only as a parent or property target become real nodes."""
    db = dict(_skeleton())
    # 'overfitting' is referenced ONLY as a property target, never a keyed node.
    db["cnn"] = {"taxonomy_parent": "ML_Model",
                 "props": {"hasCharacteristic": {"overfitting": {"f": 1}}}}
    # 'deep_network' is referenced ONLY as another concept's parent.
    db["resnet"] = {"taxonomy_parent": "deep_network", "props": {}}
    tax = S9A.Taxonomy(db)

    assert "overfitting" not in db and "deep_network" not in db
    res = S9A._materialize_referenced_only(tax)
    assert res["referenced_materialized"] >= 2
    assert "overfitting" in tax.db
    assert "deep_network" in tax.db
    # created as bare floaters (parent owl:Thing) so Phase 1 will place them
    assert tax.db["overfitting"]["taxonomy_parent"] == "owl:Thing"


def _p13_collision_db():
    """Minimal topology reproducing both protocol-v1.3 batch-4 collisions."""
    db = dict(_skeleton())
    db.update({
        "Optimization_Algorithm": {"taxonomy_parent": "Optimization_Methods"},
        "Optimization_Methods": {
            "taxonomy_parent": "Optimization_and_Efficiency"
        },
        "Optimization_and_Efficiency": {"taxonomy_parent": "ML_Algorithm"},
        "differential equation": {"taxonomy_parent": "Dynamical Systems"},
        "Dynamical Systems": {"taxonomy_parent": "Physics"},
        "projection-free algorithm": {"taxonomy_parent": "owl:Thing"},
        "stochastic differential equation": {"taxonomy_parent": "owl:Thing"},
    })
    return db


def _p13_invalid_collision_response():
    return json.dumps({"placements": [
        {
            "concept": "projection-free algorithm",
            "target_domain": "Mathematics",
            "proposed_parent": "Optimization Algorithm",
        },
        {
            "concept": "stochastic differential equation",
            "target_domain": "Mathematics",
            "proposed_parent": "Differential Equation",
        },
    ]})


def _corrected_collision_response():
    return json.dumps({"placements": [
        {
            "concept": "projection-free algorithm",
            "target_domain": "Mathematics",
            "proposed_parent": "Projection-Free Optimization Method",
        },
        {
            "concept": "stochastic differential equation",
            "target_domain": "Mathematics",
            "proposed_parent": "Stochastic Calculus Equation",
        },
    ]})


def test_phase1_feedback_corrects_all_collisions_before_v4_cache(
        tmp_path, monkeypatch):
    """A rejected p13-shaped reply feeds both collisions into one full retry."""
    _redirect(tmp_path, monkeypatch)
    _stub_fuzzy_exact_only(monkeypatch)
    monkeypatch.setattr(C, "LLM_MAX_SCHEMA_ATTEMPTS", 3)
    namespace = "feedback_accept"
    prompts = []
    responses = [
        _p13_invalid_collision_response(),
        _corrected_collision_response(),
    ]

    def responder(*, contents):
        prompts.append(contents)
        index = min(len(prompts) - 1, len(responses) - 1)
        return _pytypes.SimpleNamespace(text=responses[index])

    _install_client(monkeypatch, responder)
    tax = S9A.Taxonomy(_p13_collision_db())
    result = S9A._phase1_floaters(
        tax, cache_namespace=namespace, input_sha="frozen-input-sha"
    )

    assert result["floaters_placed"] == 2
    assert len(prompts) == 2
    assert "CORRECTION REQUIRED" not in prompts[0]
    assert prompts[1].startswith(
        prompts[0] + "\n\nCORRECTION REQUIRED AFTER VALIDATION FAILURE:"
    )
    assert "Return the COMPLETE response again" in prompts[1]
    assert "projection-free algorithm" in prompts[1]
    assert "Optimization_Algorithm" in prompts[1]
    assert (
        "Optimization_Algorithm → Optimization_Methods → "
        "Optimization_and_Efficiency → ML_Algorithm → Machine_Learning → "
        "Artificial_Intelligence → Computer_Science"
    ) in prompts[1]
    assert "existing_domain='Computer_Science'" in prompts[1]
    assert "stochastic differential equation" in prompts[1]
    assert "differential equation → Dynamical Systems → Physics" in prompts[1]
    assert "existing_domain='Physics'" in prompts[1]

    cache_dir = tmp_path / "caches" / namespace
    llm_cache = json.loads((cache_dir / "llm_cache.json").read_text())
    map_cache = json.loads((cache_dir / "map_cache.json").read_text())
    assert len(llm_cache) == len(map_cache) == 1
    assert next(iter(llm_cache)).startswith("floater_llm_v4_")
    assert next(iter(map_cache)).startswith("floater_map_v4_")
    cached_text = json.dumps(
        [next(iter(llm_cache.values())), next(iter(map_cache.values()))]
    )
    assert "Projection-Free Optimization Method" in cached_text
    assert "Stochastic Calculus Equation" in cached_text
    assert "Optimization Algorithm" not in cached_text
    assert "Differential Equation" not in cached_text

    rows = [
        json.loads(line)
        for line in (tmp_path / "logs" / "llm_trace.jsonl").read_text().splitlines()
    ]
    malformed = [row for row in rows if row["outcome"] == "malformed"]
    responses_traced = [row for row in rows if row["outcome"] == "response"]
    assert len(malformed) == 1
    assert malformed[0]["prompt"] == prompts[0]
    assert "Optimization_Algorithm" in malformed[0]["validation_feedback"]
    assert "differential equation" in malformed[0]["validation_feedback"]
    assert responses_traced[0]["prompt"] == prompts[0]
    assert responses_traced[1]["prompt"] == prompts[1]


def test_phase1_persistent_collisions_exhaust_retries_without_cache(
        tmp_path, monkeypatch):
    """Persistent topology-invalid replies fail closed and checkpoint nothing."""
    _redirect(tmp_path, monkeypatch)
    _stub_fuzzy_exact_only(monkeypatch)
    monkeypatch.setattr(C, "LLM_MAX_SCHEMA_ATTEMPTS", 3)
    namespace = "feedback_reject"
    prompts = []
    invalid = _p13_invalid_collision_response()

    def responder(*, contents):
        prompts.append(contents)
        return _pytypes.SimpleNamespace(text=invalid)

    _install_client(monkeypatch, responder)
    tax = S9A.Taxonomy(_p13_collision_db())
    with pytest.raises(S9A.TreatmentIncomplete):
        S9A._phase1_floaters(
            tax, cache_namespace=namespace, input_sha="frozen-input-sha"
        )

    assert len(prompts) == C.LLM_MAX_SCHEMA_ATTEMPTS == 3
    assert "CORRECTION REQUIRED" not in prompts[0]
    assert all("Return the COMPLETE response again" in p for p in prompts[1:])
    cache_dir = tmp_path / "caches" / namespace
    assert not (cache_dir / "llm_cache.json").exists()
    assert not (cache_dir / "map_cache.json").exists()
    assert tax.parent["projection-free algorithm"] == "owl:Thing"
    assert tax.parent["stochastic differential equation"] == "owl:Thing"

    rows = [
        json.loads(line)
        for line in (tmp_path / "logs" / "llm_trace.jsonl").read_text().splitlines()
    ]
    malformed = [row for row in rows if row["outcome"] == "malformed"]
    assert len(malformed) == 3
    assert all("Optimization_Algorithm" in row["validation_feedback"]
               for row in malformed)
    assert all("differential equation" in row["validation_feedback"]
               for row in malformed)


def test_floater_validator_reports_all_structural_errors_and_resets_feedback():
    validator = S9A._complete_floater_validator(["alpha", "beta"])
    assert validator("{not complete") is None
    assert "complete valid JSON" in validator.validation_feedback

    malformed_shape = json.dumps({"placements": [
        {
            "concept": "alpha",
            "target_domain": "Not_A_Domain",
            "proposed_parent": "",
        },
        {
            "concept": "alpha",
            "target_domain": "Mathematics",
            "proposed_parent": "Parent",
        },
        {
            "concept": "unexpected",
            "target_domain": "Mathematics",
            "proposed_parent": "Valid Parent",
        },
    ]})
    assert validator(malformed_shape) is None
    feedback = validator.validation_feedback
    assert "Placement count is 3; exactly 2" in feedback
    assert "Duplicate concept placements" in feedback
    assert "Missing requested concepts" in feedback and "beta" in feedback
    assert "Unexpected concepts" in feedback and "unexpected" in feedback
    assert "invalid target_domain" in feedback
    assert "empty or invalid proposed_parent" in feedback

    valid = json.dumps({"placements": [
        {
            "concept": "alpha",
            "target_domain": "Mathematics",
            "proposed_parent": "Parent A",
        },
        {
            "concept": "beta",
            "target_domain": "Mathematics",
            "proposed_parent": "Parent B",
        },
    ]})
    assert validator(valid) is not None
    assert validator.validation_feedback is None


def _stub_prefix_exact_only(monkeypatch):
    """Make _resolve_under_prefix do EXACT-slug matching only (no model)."""
    def _resolve(tax, proposed, parent, *, exclude=None):
        pslug = C.get_uri_name(proposed)
        if not pslug:
            return None
        for candidate in sorted(tax.descendants(parent)):
            if (candidate != exclude
                    and C.get_uri_name(candidate) == pslug
                    and not S9A._is_excluded(tax.db.get(candidate))):
                return candidate
        return None
    monkeypatch.setattr(S9A, "_resolve_under_prefix", _resolve)


def _p14_phase2_collision_db():
    """Topology reproducing the protocol-v1.4 Phase-2 batch collision."""
    db = dict(_skeleton())
    db["Dynamical Systems"] = {"taxonomy_parent": "Physics"}
    db["region of attraction"] = {"taxonomy_parent": "Mathematics"}
    return db


def test_phase2_feedback_corrects_collision_before_v5_cache(tmp_path, monkeypatch):
    """A p14-shaped out-of-prefix move is rejected, fed back, then corrected."""
    _redirect(tmp_path, monkeypatch)
    _stub_prefix_exact_only(monkeypatch)
    monkeypatch.setattr(C, "LLM_MAX_SCHEMA_ATTEMPTS", 3)
    namespace = "phase2_accept"
    prompts = []
    responses = [
        json.dumps({"decisions": [
            {"concept": "region of attraction", "decision": "move",
             "proposed_path": "Mathematics > Dynamical_Systems"}]}),
        json.dumps({"decisions": [
            {"concept": "region of attraction", "decision": "move",
             "proposed_path": "Mathematics > Stability Theory"}]}),
    ]

    def responder(*, contents):
        prompts.append(contents)
        index = min(len(prompts) - 1, len(responses) - 1)
        return _pytypes.SimpleNamespace(text=responses[index])

    _install_client(monkeypatch, responder)
    tax = S9A.Taxonomy(_p14_phase2_collision_db())
    moves = S9A._refine_children(
        tax, "Mathematics", "Mathematics", ["region of attraction"],
        cache_namespace=namespace, input_sha="frozen-input-sha",
    )

    assert moves == 1
    assert tax.parent["region of attraction"] == "Stability Theory"
    assert tax.parent["Stability Theory"] == "Mathematics"
    assert len(prompts) == 2
    assert "CORRECTION REQUIRED" not in prompts[0]
    assert prompts[1].startswith(
        prompts[0] + "\n\nCORRECTION REQUIRED AFTER VALIDATION FAILURE:"
    )
    assert "Return the COMPLETE response again" in prompts[1]
    assert "region of attraction" in prompts[1]
    assert "'Dynamical_Systems'" in prompts[1]
    assert "'Dynamical Systems'" in prompts[1]
    assert "existing_domain='Physics'" in prompts[1]
    assert "Dynamical Systems → Physics" in prompts[1]

    cache_dir = tmp_path / "caches" / namespace
    llm_cache = json.loads((cache_dir / "llm_cache.json").read_text())
    assert len(llm_cache) == 1
    assert next(iter(llm_cache)).startswith("refine_llm_v5_")
    cached_text = json.dumps(next(iter(llm_cache.values())))
    assert "Stability Theory" in cached_text
    assert "Dynamical_Systems" not in cached_text

    rows = [
        json.loads(line)
        for line in (tmp_path / "logs" / "llm_trace.jsonl").read_text().splitlines()
    ]
    malformed = [row for row in rows if row["outcome"] == "malformed"]
    assert len(malformed) == 1
    assert malformed[0]["prompt"] == prompts[0]
    assert "Dynamical Systems" in malformed[0]["validation_feedback"]
    assert "Physics" in malformed[0]["validation_feedback"]


def test_phase2_persistent_collision_exhausts_retries_without_cache(
        tmp_path, monkeypatch):
    """Persistent out-of-prefix moves fail closed and checkpoint nothing."""
    _redirect(tmp_path, monkeypatch)
    _stub_prefix_exact_only(monkeypatch)
    monkeypatch.setattr(C, "LLM_MAX_SCHEMA_ATTEMPTS", 3)
    namespace = "phase2_reject"
    prompts = []
    invalid = json.dumps({"decisions": [
        {"concept": "region of attraction", "decision": "move",
         "proposed_path": "Mathematics > Dynamical_Systems"}]})

    def responder(*, contents):
        prompts.append(contents)
        return _pytypes.SimpleNamespace(text=invalid)

    _install_client(monkeypatch, responder)
    tax = S9A.Taxonomy(_p14_phase2_collision_db())
    with pytest.raises(S9A.TreatmentIncomplete):
        S9A._refine_children(
            tax, "Mathematics", "Mathematics", ["region of attraction"],
            cache_namespace=namespace, input_sha="frozen-input-sha",
        )

    assert len(prompts) == C.LLM_MAX_SCHEMA_ATTEMPTS == 3
    assert "CORRECTION REQUIRED" not in prompts[0]
    assert all("Return the COMPLETE response again" in p for p in prompts[1:])
    assert tax.parent["region of attraction"] == "Mathematics"
    assert "Dynamical_Systems" not in tax.db
    cache_dir = tmp_path / "caches" / namespace
    assert not (cache_dir / "llm_cache.json").exists()


def test_phase2_intra_batch_dependency_is_accepted_not_falsely_rejected(
        tmp_path, monkeypatch):
    """The p15 false-rejection: a later move may target a node an earlier move
    in the same sorted batch relocates. Validation must be as permissive as the
    sequential, mutating application and accept it in one attempt."""
    _redirect(tmp_path, monkeypatch)
    _stub_prefix_exact_only(monkeypatch)
    monkeypatch.setattr(C, "LLM_MAX_SCHEMA_ATTEMPTS", 3)
    namespace = "phase2_intrabatch"

    db = dict(_skeleton())
    # All three are direct children of Mathematics before refinement.
    db["Probabilistic Inference & Statistics"] = {"taxonomy_parent": "Mathematics"}
    db["Estimator"] = {"taxonomy_parent": "Mathematics"}
    db["Gradient Estimate"] = {"taxonomy_parent": "Mathematics"}
    tax = S9A.Taxonomy(db)

    # Sorted batch order => Estimator is applied before Gradient Estimate.
    children = sorted(["Probabilistic Inference & Statistics",
                       "Estimator", "Gradient Estimate"])
    assert children.index("Estimator") < children.index("Gradient Estimate")

    prompts = []
    response = json.dumps({"decisions": [
        {"concept": "Probabilistic Inference & Statistics",
         "decision": "ok", "proposed_path": ""},
        {"concept": "Estimator", "decision": "move",
         "proposed_path": "Mathematics > Probabilistic Inference & Statistics"},
        {"concept": "Gradient Estimate", "decision": "move",
         "proposed_path":
             "Mathematics > Probabilistic Inference & Statistics > Estimator"},
    ]})

    def responder(*, contents):
        prompts.append(contents)
        return _pytypes.SimpleNamespace(text=response)

    _install_client(monkeypatch, responder)
    moves = S9A._refine_children(
        tax, "Mathematics", "Mathematics", children,
        cache_namespace=namespace, input_sha="frozen-input-sha",
    )

    # Accepted on the FIRST attempt: no retry, no correction feedback.
    assert len(prompts) == 1
    assert "CORRECTION REQUIRED" not in prompts[0]
    assert moves == 2
    assert tax.parent["Estimator"] == "Probabilistic Inference & Statistics"
    assert tax.parent["Gradient Estimate"] == "Estimator"

    cache_dir = tmp_path / "caches" / namespace
    llm_cache = json.loads((cache_dir / "llm_cache.json").read_text())
    assert len(llm_cache) == 1
    assert next(iter(llm_cache)).startswith("refine_llm_v5_")
