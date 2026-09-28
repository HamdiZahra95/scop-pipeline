"""Unit tests for the common.py foundation helpers added in Task 1 / 1.1.

Covers:
  * output_dir never collides across runs (distinct RUN_ID / code hash),
  * get_uri / get_uri_name determinism + documented collision behavior,
  * PROPERTY_AXIOMS passes validate_property_axioms(), plus mutation cases that
    MUST make the validator raise.

Run:  pytest test_result/pipeline_v2/tests/test_common_foundation.py
"""

import copy
import importlib
import sys
from pathlib import Path

import pytest

# Make the pipeline_v2 dir importable so `import common` works regardless of the
# pytest invocation directory.
PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))

import common as C  # noqa: E402


# ── output_dir: never overwrites a prior run ───────────────────────────────
def test_output_dir_creates_versioned_directory():
    """output_dir returns an existing dir named <RUN_ID>__<codehash8>/."""
    d = C.output_dir("s03_test_stage", __file__)
    assert d.is_dir()
    assert d.parent == C.ARTIFACTS / "s03_test_stage"
    assert d.name == f"{C.RUN_ID}__{C.code_hash(__file__)}"


def test_output_dir_same_run_same_code_is_idempotent():
    """Same RUN_ID + same caller code hash → same directory (reuse, no crash)."""
    d1 = C.output_dir("s03_test_stage", __file__)
    d2 = C.output_dir("s03_test_stage", __file__)
    assert d1 == d2
    assert d1.is_dir()


def test_output_dir_distinct_run_id_distinct_dir(monkeypatch):
    """A different RUN_ID yields a different directory (no collision)."""
    d_original = C.output_dir("s03_collide", __file__)

    monkeypatch.setattr(C, "RUN_ID", C.RUN_ID + "_LATER")
    d_new = C.output_dir("s03_collide", __file__)

    assert d_new != d_original
    assert d_original.is_dir() and d_new.is_dir()


def test_output_dir_distinct_code_hash_distinct_dir(tmp_path):
    """A different caller source (different code hash) yields a different dir."""
    file_a = tmp_path / "stage_a.py"
    file_b = tmp_path / "stage_b.py"
    file_a.write_text("# version A\nprint('a')\n")
    file_b.write_text("# version B — different bytes\nprint('bbbb')\n")

    d_a = C.output_dir("s03_codehash", str(file_a))
    d_b = C.output_dir("s03_codehash", str(file_b))

    assert C.code_hash(str(file_a)) != C.code_hash(str(file_b))
    assert d_a != d_b
    assert d_a.is_dir() and d_b.is_dir()


def test_output_dir_matches_output_path_naming():
    """output_dir uses the same <RUN_ID>__<hash> stem as output_path."""
    d = C.output_dir("s03_naming", __file__)
    p = C.output_path("s03_naming", __file__, ext="json")
    # p stem is "<RUN_ID>__<hash>"; d name is the same string.
    assert d.name == p.stem


# ── get_uri / get_uri_name: determinism + collision behavior ───────────────
def test_get_uri_name_deterministic():
    """Same input always produces the same slug."""
    for name in ["Neural Network", "  Gradient Descent  ", "K-Means!!"]:
        assert C.get_uri_name(name) == C.get_uri_name(name)


def test_get_uri_name_normalization():
    assert C.get_uri_name("Neural Network") == "neural_network"
    assert C.get_uri_name("  Neural--Network!! ") == "neural_network"
    assert C.get_uri_name("K-Means") == "k_means"
    # all-punctuation / empty normalizes to the empty string.
    assert C.get_uri_name("!!!") == ""
    assert C.get_uri_name("   ") == ""


def test_get_uri_name_collision_is_defined():
    """Documented many-to-one behavior: case/space/punctuation variants collide."""
    variants = ["Neural Network", "neural_network", "neural-network",
                "NEURAL   NETWORK"]
    slugs = {C.get_uri_name(v) for v in variants}
    assert slugs == {"neural_network"}


def test_get_uri_full_form():
    assert C.get_uri("Neural Network") == C.ONTOLOGY_NS + "neural_network"
    assert C.get_uri("Neural Network").startswith("http")
    assert "#" in C.get_uri("x")


def test_get_uri_shares_collision_with_get_uri_name():
    """Names sharing a slug share a URI (single source of truth for S09/S11)."""
    assert C.get_uri("Support Vector Machine") == C.get_uri("support-vector-machine")


# ── PROPERTY_AXIOMS + validate_property_axioms ─────────────────────────────
def test_property_axioms_covers_all_core_properties():
    assert set(C.PROPERTY_AXIOMS) == set(C.CORE_PROPERTIES)


def test_validate_property_axioms_passes_on_real_table():
    # The real table must validate (also enforced at import time).
    C.validate_property_axioms()


def test_no_functional_or_inverse_functional_on_the_13():
    for prop, spec in C.PROPERTY_AXIOMS.items():
        chars = set(spec.get("characteristics", []))
        assert not chars & {"Functional", "InverseFunctional"}, prop


def test_every_entry_has_domain_and_range():
    for prop, spec in C.PROPERTY_AXIOMS.items():
        assert spec.get("domain"), prop
        assert spec.get("range"), prop


# ── Mutation cases: the validator MUST raise ───────────────────────────────
def test_mutation_transitive_plus_cardinality_raises():
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    bad["hasComponent"]["cardinality"] = 1  # hasComponent is Transitive
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


def test_mutation_functional_characteristic_raises():
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    bad["optimizes"]["characteristics"] = ["Functional"]
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


def test_mutation_inverse_functional_characteristic_raises():
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    bad["selects"]["characteristics"] = ["InverseFunctional"]
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


def test_mutation_missing_domain_raises():
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    del bad["transforms"]["domain"]
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


def test_mutation_missing_range_raises():
    bad = copy.deepcopy(C.PROPERTY_AXIOMS)
    del bad["transforms"]["range"]
    with pytest.raises(ValueError):
        C.validate_property_axioms(bad)


def test_import_time_validation_runs():
    """Re-importing common re-runs the fail-fast validation without error."""
    importlib.reload(C)
