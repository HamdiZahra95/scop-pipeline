"""S12 quality-gate fixture tests (Task 14.1).

Verifies the gate's four required behaviors on hand-built fixture ontologies
(design "OWL-DL / S12 tests"; R16.8, R17.1, R17.2, R15.2):

  1. a consistent tiny ontology PASSES the gate (verdict "pass", no hard
     failures, and — when the reasoner accepts the axioms — consistency
     "consistent");
  2. an injected disjointness contradiction (a class subsumed under two
     pairwise-disjoint top-level domains) is flagged INCONSISTENT and hard-fails
     the gate (R16.8, R17.1);
  3. a planted `subClassOf` cycle is DETECTED and hard-fails the gate (R17.2);
  4. each competency question runs against a fixture ontology and returns a
     status (answerable / gap / hard_fail) — the CQ machinery evaluates end to
     end (R15.2).

The fixtures are built directly as `rdflib` graphs (not via S11) so each test
controls exactly the axioms under test — including the ability to build a
DELIBERATELY inconsistent or cyclic ontology, which S11 would never emit. To
keep the positive-consistency test reasoner-friendly we omit the transitive +
asymmetric characteristics that place the real axiom box outside HermiT's
simple-property subset; consistency of the fixtures themselves is what matters
here.

Run:  pytest test_result/pipeline_v2/tests/test_s13_quality_gate.py -q
"""

import json
import sys
from pathlib import Path

import pytest
from rdflib import Graph, RDF, RDFS, OWL, URIRef, Literal, BNode
from rdflib.collection import Collection
from rdflib.namespace import SKOS

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s13_quality_gate as S12  # noqa: E402

NS = C.ONTOLOGY_NS


# ── graph-building helpers ───────────────────────────────────────────────────
def _new_graph() -> Graph:
    g = Graph()
    g.bind("ml", NS)
    g.bind("owl", OWL)
    g.bind("skos", SKOS)
    onto = URIRef(NS.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    return g


def _cls(g: Graph, name: str) -> URIRef:
    """Declare a class by its slugged local name and give it a label."""
    u = URIRef(C.get_uri(name))
    g.add((u, RDF.type, OWL.Class))
    g.add((u, RDFS.label, Literal(name, lang="en")))
    return u


def _subclass(g: Graph, child: str, parent: str):
    g.add((URIRef(C.get_uri(child)), RDFS.subClassOf, URIRef(C.get_uri(parent))))


def _declare_domains_disjoint(g: Graph):
    """Declare the five top-level domains and assert them pairwise disjoint."""
    uris = [_cls(g, d) for d in C.TOP_LEVEL_DOMAINS]
    node = BNode()
    g.add((node, RDF.type, OWL.AllDisjointClasses))
    head = BNode()
    Collection(g, head, uris)
    g.add((node, OWL.members, head))


def _obj_property(g: Graph, name: str, domain: str, rnge: str, inverse: str | None = None):
    p = URIRef(NS + name)
    g.add((p, RDF.type, OWL.ObjectProperty))
    g.add((p, RDFS.label, Literal(name, lang="en")))
    g.add((p, RDFS.domain, URIRef(C.get_uri(domain)) if domain != "owl:Thing" else OWL.Thing))
    g.add((p, RDFS.range, URIRef(C.get_uri(rnge)) if rnge != "owl:Thing" else OWL.Thing))
    if inverse:
        inv = URIRef(NS + inverse)
        g.add((inv, RDF.type, OWL.ObjectProperty))
        g.add((p, OWL.inverseOf, inv))
    return p


def _edge(g: Graph, subj: str, prop: str, obj: str):
    g.add((URIRef(C.get_uri(subj)), URIRef(NS + prop), URIRef(C.get_uri(obj))))


def _consistent_fixture(g: Graph):
    """A small, reasoner-friendly, structurally sound ontology.

    Backbone: CS→AI→ML plus the other four disjoint top-level domains; a couple
    of ML leaves; a handful of concepts typed cleanly under exactly one branch;
    a few well-typed object-property edges; definitions + an altLabel so the
    annotation CQs are answerable. It carries NO transitive/asymmetric axioms so
    HermiT accepts it (it stays inside the simple-property subset)."""
    _declare_domains_disjoint(g)

    # CS → AI → ML spine.
    _cls(g, "Artificial_Intelligence")
    _cls(g, "Machine_Learning")
    _subclass(g, "Artificial_Intelligence", "Computer_Science")
    _subclass(g, "Machine_Learning", "Artificial_Intelligence")

    # two ML leaves under ML.
    for leaf in ("ML_Model", "ML_Algorithm", "ML_Task",
                 "ML_Objective_and_Constraint", "ML_Data_and_Representation"):
        _cls(g, leaf)
        _subclass(g, leaf, "Machine_Learning")

    # concepts typed under exactly one leaf (genuine subsumption).
    _cls(g, "neural_network")
    _subclass(g, "neural_network", "ML_Model")
    _cls(g, "convolutional_neural_network")
    _subclass(g, "convolutional_neural_network", "neural_network")
    _cls(g, "unsupervised_learning")
    _subclass(g, "unsupervised_learning", "ML_Task")
    _cls(g, "clustering")
    _subclass(g, "clustering", "unsupervised_learning")
    _cls(g, "gradient_descent")
    _subclass(g, "gradient_descent", "ML_Algorithm")
    _cls(g, "classification")
    _subclass(g, "classification", "ML_Task")
    _cls(g, "cross_entropy_loss")
    _subclass(g, "cross_entropy_loss", "ML_Objective_and_Constraint")
    _cls(g, "training_data")
    _subclass(g, "training_data", "ML_Data_and_Representation")
    _cls(g, "convolution")
    _subclass(g, "convolution", "ML_Model")
    _cls(g, "prediction")
    _subclass(g, "prediction", "ML_Model")

    # object properties (typed) + edges.
    _obj_property(g, "optimizes", "ML_Algorithm", "ML_Objective_and_Constraint",
                  inverse="isOptimizedBy")
    _obj_property(g, "learnsFrom", "ML_Model", "ML_Data_and_Representation")
    _obj_property(g, "producesOutput", "owl:Thing", "owl:Thing")
    _obj_property(g, "hasComponent", "owl:Thing", "owl:Thing")
    _obj_property(g, "hasPurpose", "owl:Thing", "owl:Thing")

    _edge(g, "gradient_descent", "optimizes", "cross_entropy_loss")
    _edge(g, "convolutional_neural_network", "learnsFrom", "training_data")
    _edge(g, "convolutional_neural_network", "hasComponent", "convolution")
    _edge(g, "convolutional_neural_network", "producesOutput", "prediction")
    _edge(g, "neural_network", "hasComponent", "convolution")
    _edge(g, "neural_network", "hasPurpose", "classification")

    # annotations for the annotation CQs.
    gd = URIRef(C.get_uri("gradient_descent"))
    g.add((gd, RDFS.comment, Literal("An iterative optimization algorithm.", lang="en")))
    g.add((gd, SKOS.definition, Literal("An iterative optimization algorithm.", lang="en")))
    cnn = URIRef(C.get_uri("convolutional_neural_network"))
    g.add((cnn, SKOS.altLabel, Literal("CNN", lang="en")))
    g.add((cnn, SKOS.altLabel, Literal("convnet", lang="en")))


def _write(g: Graph, tmp_path: Path, name: str = "fixture.owl") -> Path:
    p = tmp_path / name
    g.serialize(destination=str(p), format="xml")
    return p


# ── 1. consistent tiny ontology passes ───────────────────────────────────────
def test_consistent_ontology_passes(tmp_path):
    g = _new_graph()
    _consistent_fixture(g)
    owl = _write(g, tmp_path)

    report = S12.analyze(owl)

    assert report["verdict"] == "pass", report["hard_failures"]
    assert report["hard_failures"] == []
    assert report["subclass_cycles"] == []
    # The reasoner should accept this simple-property ontology and find it
    # consistent (if Java is unavailable it would be "unchecked" — still not a
    # failure — but in this environment HermiT runs).
    assert report["consistency"]["status"] in ("consistent", "unchecked")
    if report["consistency"]["status"] == "consistent":
        assert report["consistency"]["inconsistent_classes"] == []


# ── 2. injected disjointness contradiction is flagged inconsistent ───────────
def test_disjointness_contradiction_is_inconsistent(tmp_path):
    g = _new_graph()
    _consistent_fixture(g)
    # Plant the contradiction: a concept that is a subclass of BOTH
    # Computer_Science and Mathematics, which are asserted pairwise disjoint.
    _cls(g, "contradiction_concept")
    _subclass(g, "contradiction_concept", "Computer_Science")
    _subclass(g, "contradiction_concept", "Mathematics")
    owl = _write(g, tmp_path, "inconsistent.owl")

    report = S12.analyze(owl)

    cons = report["consistency"]
    if cons["status"] == "unchecked":
        pytest.skip(f"reasoner unavailable: {cons.get('reasoner_error')}")

    assert cons["status"] == "inconsistent", cons
    assert report["verdict"] == "fail"
    assert any(hf["type"] == "inconsistent" for hf in report["hard_failures"])
    # the offending stage is surfaced for backtracking (R17.6).
    hf = next(hf for hf in report["hard_failures"] if hf["type"] == "inconsistent")
    assert hf["responsible_stage"]
    # CQ12 (consistency probe) hard-fails.
    cq12 = next(c for c in report["competency_questions"]["results"] if c["id"] == "CQ12")
    assert cq12["status"] == "hard_fail"


# ── 3. planted subClassOf cycle is detected ──────────────────────────────────
def test_subclass_cycle_is_detected(tmp_path):
    g = _new_graph()
    _consistent_fixture(g)
    # Plant a cycle: a → b → c → a (all fresh classes, off to the side).
    for n in ("cycle_a", "cycle_b", "cycle_c"):
        _cls(g, n)
    _subclass(g, "cycle_a", "cycle_b")
    _subclass(g, "cycle_b", "cycle_c")
    _subclass(g, "cycle_c", "cycle_a")
    owl = _write(g, tmp_path, "cyclic.owl")

    report = S12.analyze(owl)

    assert report["subclass_cycles"], "cycle not detected"
    # the detected cycle mentions the planted classes.
    flat = {name for cyc in report["subclass_cycles"] for name in cyc}
    assert {"cycle_a", "cycle_b", "cycle_c"} <= flat
    assert report["verdict"] == "fail"
    assert any(hf["type"] == "subclass_cycle" for hf in report["hard_failures"])


def test_cycle_detector_on_clean_graph_finds_none(tmp_path):
    """A well-formed hierarchy has no cycles (guards against false positives)."""
    g = _new_graph()
    _consistent_fixture(g)
    assert S12.detect_subclass_cycles(g) == []


# ── 4. each CQ query returns for a fixture ontology ──────────────────────────
def test_every_cq_returns_a_status(tmp_path):
    g = _new_graph()
    _consistent_fixture(g)
    owl = _write(g, tmp_path)

    report = S12.analyze(owl)
    cqs = report["competency_questions"]["results"]

    # all 12 CQs evaluated, each with a recognized status.
    assert len(cqs) == 12
    ids = {c["id"] for c in cqs}
    assert ids == {f"CQ{i}" for i in range(1, 13)}
    for c in cqs:
        assert c["status"] in ("answerable", "gap", "hard_fail"), c
        assert c["detail"]  # every CQ reports a human-readable detail

    # On this purpose-built fixture the concept-backed CQs are answerable.
    by_id = {c["id"]: c for c in cqs}
    assert by_id["CQ1"]["status"] == "answerable"    # unsupervised_learning has clustering
    assert by_id["CQ2"]["status"] == "answerable"    # ML_Model has descendants
    assert by_id["CQ4"]["status"] == "answerable"    # an optimizes edge exists
    assert by_id["CQ5"]["status"] == "answerable"    # gd optimizes cross_entropy_loss
    assert by_id["CQ7"]["status"] == "answerable"    # neural_network hasComponent
    assert by_id["CQ10"]["status"] == "answerable"   # gradient_descent has a definition
    assert by_id["CQ11"]["status"] == "answerable"   # CNN altLabels


def test_gaps_are_not_hard_failures(tmp_path):
    """A CQ whose concept is absent is a coverage gap, never a hard failure
    (R15.3). Build a minimal-but-consistent ontology missing most concepts."""
    g = _new_graph()
    _declare_domains_disjoint(g)
    _cls(g, "Machine_Learning")
    _subclass(g, "Machine_Learning", "Computer_Science")
    # one leaf, no rich concepts / edges / annotations.
    _cls(g, "ML_Model")
    _subclass(g, "ML_Model", "Machine_Learning")
    owl = _write(g, tmp_path, "sparse.owl")

    report = S12.analyze(owl)
    cqs = {c["id"]: c for c in report["competency_questions"]["results"]}

    # missing-concept CQs are gaps, not failures.
    assert cqs["CQ1"]["status"] == "gap"     # unsupervised_learning absent
    assert cqs["CQ5"]["status"] == "gap"     # cross_entropy_loss absent
    assert cqs["CQ10"]["status"] == "gap"    # gradient_descent absent
    # gaps do NOT flip the verdict (no inconsistency, no cycle here).
    assert report["verdict"] == "pass"
    assert report["competency_questions"]["gaps"] >= 3


# ── run()/report/manifest contract ───────────────────────────────────────────
def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)


def _seed_s11(g: Graph, tmp_path: Path, name="20990101-000000__deadbeef.owl") -> Path:
    d = tmp_path / "artifacts" / "s12_export_owl"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    g.serialize(destination=str(p), format="xml")
    return p


def test_run_writes_report_and_manifest_extra(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    g = _new_graph()
    _consistent_fixture(g)
    _seed_s11(g, tmp_path)

    out_path = S12.run()

    # report written under reports/, is the quality report.
    assert Path(out_path).is_file()
    assert out_path.name.endswith(".quality.json")
    rep = json.loads(Path(out_path).read_text())
    assert rep["stage"] == "s13_quality_gate"
    assert rep["verdict"] == "pass"

    # manifest records verdict + metrics via `extra` (R17.5).
    lines = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["stage"] == "s13_quality_gate"
    assert rec["extra"]["quality_verdict"] == "pass"
    assert "metrics" in rec["extra"]
    assert "class_count" in rec["extra"]["metrics"]


def test_run_raises_when_no_s11_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        S12.run()


def test_run_reports_fail_verdict_on_inconsistent(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    g = _new_graph()
    _consistent_fixture(g)
    _cls(g, "contradiction_concept")
    _subclass(g, "contradiction_concept", "Computer_Science")
    _subclass(g, "contradiction_concept", "Mathematics")
    _seed_s11(g, tmp_path, name="20990101-000001__cafe0001.owl")

    out_path = S12.run()
    rep = json.loads(Path(out_path).read_text())
    if rep["consistency"]["status"] == "unchecked":
        pytest.skip("reasoner unavailable")
    assert rep["verdict"] == "fail"
