"""OWL-DL structure + Property-9 & Property-10 tests for S11 (Task 12.1).

Verifies the ported serialization and the genuine OWL-DL / quality work (R16,
R20, R23):

  * the produced ontology PARSES in `owlready2` (R16.2),
  * the 13 core object properties each carry their curated axioms — domain,
    range, inverse, and the Transitive/Symmetric/Irreflexive/Asymmetric
    characteristics read from `common.PROPERTY_AXIOMS` (R16.2/3/4),
  * the five top-level domains are asserted pairwise disjoint; ML leaves are
    NOT (cautious disjointness, R16.6),
  * mined sub-properties declare ONLY `subPropertyOf` a core property — no
    domain/range/characteristic/disjointness of their own (Property 9, R23.2/3),
  * `consolidated_definitions` are emitted as both `rdfs:comment` and
    `skos:definition` (R20.3), and merged surface forms as `skos:altLabel`
    (R20.1),
  * `literal_annotations` are rendered as annotations, never object-property
    edges (R12.3),
  * `run()` reads the latest S10 artifact, writes ONE versioned `.owl`, and
    returns it; re-runs never overwrite (R1.1, R2.3, R13.3).

Property 9 (sub-property safety): every mined sub-property declares exactly one
`subPropertyOf` a core property, inherits its parent's domain/range, and
introduces no transitivity/functional/disjointness axiom of its own.

Property 10 (definition preservation end-to-end): for every concept present in
both the S07 input and the S11 output, its `consolidated_definitions` set at S11
is a superset-or-equal of the set at S07 — definitions are never silently
dropped by grounding, taxonomy, formalization, or export.

**Validates: Requirements 16.2, 20.3, 20.4, 23.2, 23.3**

Run:  pytest test_result/pipeline_v2/tests/test_s12_export_owl.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rdflib import Graph, RDF, RDFS, OWL, URIRef, Literal
from rdflib.namespace import SKOS

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s07_ground_to_master as S07  # noqa: E402
import s12_export_owl as S11  # noqa: E402

CORE_PROPERTIES = list(C.CORE_PROPERTIES)


# ── seeding / redirection helpers ───────────────────────────────────────────
def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    monkeypatch.setattr(C, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    (tmp_path / "caches").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)


def _seed_s10(db, tmp_path, name="20990101-000000__deadbeef.json"):
    d = tmp_path / "artifacts" / "s11_formalize_properties"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(db), encoding="utf-8")
    return p


def _make_db():
    """A synthetic S10-shaped DB exercising every S11 feature: skeleton nodes,
    core-property edges with surface forms, a demoted literal_annotation, class
    definitions, and a non-omitted verb→core sub-property mapping."""
    return {
        "Machine_Learning": {
            "f": 0, "td": 0, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "Artificial_Intelligence",
            "is_skeleton": True, "consolidated_definitions": [],
        },
        "ML_Model": {
            "f": 0, "td": 0, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "Machine_Learning",
            "is_skeleton": True, "consolidated_definitions": [],
        },
        "convolutional_neural_network": {
            "f": 42, "td": 6, "cov": 0.9,
            "props": {
                "hasComponent": {
                    "convolution": {"f": 8, "v": {"use": 8}, "e": "ex1",
                                    "sf": ["conv layer", "convolutional layer"]}
                },
                "learnsFrom": {
                    "training_data": {"f": 5, "v": {"learn": 3, "train": 2}, "e": "ex2"}
                },
                "producesOutput": {
                    "prediction": {"f": 4, "v": {"predict": 4}, "e": "ex3"}
                },
            },
            "literal_annotations": [
                {"prop": "hasCharacteristic",
                 "value": "achieves state of the art accuracy on image tasks",
                 "weight": 2, "raw_verbs": ["achieve"]}
            ],
            "taxonomy_parent": "ML_Model",
            "consolidated_definitions": [
                "A convolutional neural network used for image classification.",
                "A deep model that processes images via convolutional layers.",
            ],
        },
        "gradient_descent": {
            "f": 30, "td": 4, "cov": 0.8,
            "props": {
                "optimizes": {
                    "loss_function": {"f": 7, "v": {"minimize": 4, "optimize": 3}, "e": "ex4"}
                },
                "modifies": {
                    "weights": {"f": 3, "v": {"update": 3}, "e": "ex5"}
                },
            },
            "literal_annotations": [],
            "taxonomy_parent": "Machine_Learning",
            "consolidated_definitions": [
                "An iterative optimization algorithm that minimizes a loss function."
            ],
        },
        "__meta__": {
            "stage": "s11_formalize_properties",
            "property_mapping": {
                "use": "hasComponent",
                "learn": "learnsFrom",
                "train": "learnsFrom",
                "predict": "producesOutput",
                "minimize": "optimizes",
                "optimize": "optimizes",
                "update": "modifies",
            },
            "sub_property_layer_omitted": False,
            "uncertain_verbs": [],
        },
    }


def _load_owlready(owl_path):
    """Load an .owl file into owlready2 with a fresh world to avoid cross-test
    IRI clashes; returns the loaded ontology."""
    from owlready2 import World
    world = World()
    onto = world.get_ontology("file://" + str(Path(owl_path).resolve())).load()
    return onto, world


# ── owlready2 parse + core-property axioms ──────────────────────────────────
def test_owl_parses_and_core_properties_carry_axioms(tmp_path, monkeypatch):
    from owlready2 import (TransitiveProperty, SymmetricProperty,
                           IrreflexiveProperty, AsymmetricProperty,
                           FunctionalProperty, InverseFunctionalProperty)
    _redirect(tmp_path, monkeypatch)
    _seed_s10(_make_db(), tmp_path)
    out_path = S11.run()
    assert Path(out_path).suffix == ".owl"

    onto, _world = _load_owlready(out_path)

    char_class = {
        "Transitive": TransitiveProperty, "Symmetric": SymmetricProperty,
        "Irreflexive": IrreflexiveProperty, "Asymmetric": AsymmetricProperty,
    }
    for cp in CORE_PROPERTIES:
        p = onto.search_one(iri="*#" + cp)
        assert p is not None, f"core property {cp} not declared"
        spec = C.PROPERTY_AXIOMS[cp]
        # domain + range present (R16.2 Tier 1).
        assert len(list(p.domain)) == 1, f"{cp} must carry exactly one domain"
        assert len(list(p.range)) == 1, f"{cp} must carry exactly one range"
        # characteristics from the curated table (R16.3/4).
        for ch in spec.get("characteristics", []):
            if ch in char_class:
                assert char_class[ch] in p.is_a, f"{cp} missing {ch}"
        # forbidden characteristics never appear (R16.5).
        assert FunctionalProperty not in p.is_a
        assert InverseFunctionalProperty not in p.is_a
        # inverse declared + linked when specified.
        if spec.get("inverse"):
            inv = onto.search_one(iri="*#" + spec["inverse"])
            assert inv is not None, f"{cp} inverse {spec['inverse']} not declared"
            assert p.inverse_property == inv or inv.inverse_property == p


# ── Property 9: sub-property safety ─────────────────────────────────────────
def test_property9_subproperty_safety(tmp_path, monkeypatch):
    """Every mined sub-property declares exactly one subPropertyOf a core
    property, inherits its parent's domain/range, and introduces no
    transitivity/functional/disjointness axiom of its own (R23.2, R23.3)."""
    _redirect(tmp_path, monkeypatch)
    db = _make_db()
    _seed_s10(db, tmp_path)
    out_path = S11.run()

    # Parse the raw RDF graph so we can assert on the EXACT triples emitted.
    g = Graph()
    g.parse(str(out_path), format="xml")

    mapping = db["__meta__"]["property_mapping"]
    forbidden_type_axioms = {
        OWL.TransitiveProperty, OWL.SymmetricProperty, OWL.IrreflexiveProperty,
        OWL.AsymmetricProperty, OWL.FunctionalProperty,
        OWL.InverseFunctionalProperty, OWL.ReflexiveProperty,
    }

    for verb, core in mapping.items():
        sub = URIRef(C.get_uri(verb))
        # Core properties are declared under their EXACT name (camelCase), not
        # the lowercased slug — the sub-property's parent must match that.
        core_uri = URIRef(C.ONTOLOGY_NS + core)

        # exactly one subPropertyOf, and it targets the mapped core property.
        supers = list(g.objects(sub, RDFS.subPropertyOf))
        assert supers == [core_uri], (
            f"sub-property '{verb}' must declare exactly one subPropertyOf "
            f"'{core}', got {supers}"
        )

        # declared as an object property.
        assert (sub, RDF.type, OWL.ObjectProperty) in g

        # NO own domain / range — it inherits the parent's (R23.2).
        assert list(g.objects(sub, RDFS.domain)) == [], \
            f"sub-property '{verb}' must not declare its own domain"
        assert list(g.objects(sub, RDFS.range)) == [], \
            f"sub-property '{verb}' must not declare its own range"

        # NO characteristic axioms of its own (R23.3).
        sub_types = set(g.objects(sub, RDF.type))
        assert not (sub_types & forbidden_type_axioms), (
            f"sub-property '{verb}' must not carry characteristic axioms, "
            f"found {sub_types & forbidden_type_axioms}"
        )

        # NO disjointness of its own.
        assert list(g.objects(sub, OWL.propertyDisjointWith)) == []

        # The parent core property it inherits from IS typed (domain/range).
        assert list(g.objects(core_uri, RDFS.domain)), \
            f"parent '{core}' must carry a domain to inherit"
        assert list(g.objects(core_uri, RDFS.range)), \
            f"parent '{core}' must carry a range to inherit"


def test_omitted_layer_declares_no_subproperties(tmp_path, monkeypatch):
    """R23.5: when S10 omits the sub-property layer (empty mapping), S11 declares
    NO sub-properties, but the 13 core properties still apply."""
    _redirect(tmp_path, monkeypatch)
    db = _make_db()
    db["__meta__"]["property_mapping"] = {}
    db["__meta__"]["sub_property_layer_omitted"] = True
    _seed_s10(db, tmp_path)
    out_path = S11.run()

    g = Graph()
    g.parse(str(out_path), format="xml")

    # No verb sub-property triples.
    assert list(g.subjects(RDFS.subPropertyOf, None)) == []
    # The 13 core are still present with axioms (declared under their exact name).
    for cp in CORE_PROPERTIES:
        cp_uri = URIRef(C.ONTOLOGY_NS + cp)
        assert (cp_uri, RDF.type, OWL.ObjectProperty) in g
        assert list(g.objects(cp_uri, RDFS.domain))


# ── disjointness: top-level domains yes, leaves no ──────────────────────────
def test_top_level_domains_pairwise_disjoint_leaves_not(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s10(_make_db(), tmp_path)
    out_path = S11.run()

    g = Graph()
    g.parse(str(out_path), format="xml")

    # Gather every class that appears in an AllDisjointClasses members list.
    disjoint_members = set()
    for node in g.subjects(RDF.type, OWL.AllDisjointClasses):
        members_head = next(g.objects(node, OWL.members), None)
        if members_head is not None:
            from rdflib.collection import Collection
            for m in Collection(g, members_head):
                disjoint_members.add(m)

    for d in C.TOP_LEVEL_DOMAINS:
        assert URIRef(C.get_uri(d)) in disjoint_members, \
            f"top-level domain '{d}' must be pairwise disjoint"
    # ML leaves are NOT force-disjoint (cautious — R16.6).
    for leaf in C.ML_LEAVES:
        assert URIRef(C.get_uri(leaf)) not in disjoint_members, \
            f"ML leaf '{leaf}' must NOT be asserted disjoint (R16.6)"


# ── definitions + alt-labels + literal annotations ──────────────────────────
def test_definitions_altlabels_and_literal_annotations(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    db = _make_db()
    _seed_s10(db, tmp_path)
    out_path = S11.run()

    g = Graph()
    g.parse(str(out_path), format="xml")

    cnn = URIRef(C.get_uri("convolutional_neural_network"))
    # R20.3: each definition present as BOTH rdfs:comment and skos:definition.
    comments = {str(o) for o in g.objects(cnn, RDFS.comment)}
    skos_defs = {str(o) for o in g.objects(cnn, SKOS.definition)}
    for d in db["convolutional_neural_network"]["consolidated_definitions"]:
        assert d in comments, f"definition missing as rdfs:comment: {d}"
        assert d in skos_defs, f"definition missing as skos:definition: {d}"

    # R20.1: merged surface forms → skos:altLabel on the target class.
    conv = URIRef(C.get_uri("convolution"))
    alt = {str(o) for o in g.objects(conv, SKOS.altLabel)}
    assert {"conv layer", "convolutional layer"} <= alt

    # R12.3: literal_annotations rendered as annotation (rdfs:comment), NOT as an
    # object-property edge. The demoted value text appears in a comment ...
    assert any("achieves state of the art accuracy" in c for c in comments)
    # ... and there is no object-property edge to a slugged version of it.
    demoted_uri = URIRef(C.get_uri("achieves state of the art accuracy on image tasks"))
    assert list(g.subjects(None, demoted_uri)) == [], \
        "literal_annotation must not become an object-property target"


# ── reified triples carry weight + raw verbs ────────────────────────────────
def test_reified_triples_carry_weight_and_raw_verbs(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s10(_make_db(), tmp_path)
    out_path = S11.run()

    g = Graph()
    g.parse(str(out_path), format="xml")

    ns = C.ONTOLOGY_NS
    weight_p = URIRef(ns + "extraction_weight")
    verb_p = URIRef(ns + "raw_extracted_verb")

    cnn = URIRef(C.get_uri("convolutional_neural_network"))
    conv = URIRef(C.get_uri("convolution"))
    has_component = URIRef(ns + "hasComponent")

    # the logical edge exists.
    assert (cnn, has_component, conv) in g

    # a reified statement for it carries the weight (8) and raw verb ("use").
    found = False
    for stmt in g.subjects(RDF.type, RDF.Statement):
        if ((stmt, RDF.subject, cnn) in g and
                (stmt, RDF.predicate, has_component) in g and
                (stmt, RDF.object, conv) in g):
            weights = [int(o) for o in g.objects(stmt, weight_p)]
            verbs = " ".join(str(o) for o in g.objects(stmt, verb_p))
            assert 8 in weights
            assert "use" in verbs
            found = True
    assert found, "no reified statement found for the hasComponent edge"


# ── run() contract: one versioned artifact, re-runs never overwrite ─────────
def test_run_writes_one_versioned_owl_and_never_overwrites(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s10(_make_db(), tmp_path)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S11.run()
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    p2 = S11.run()

    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()
    art = tmp_path / "artifacts" / "s12_export_owl"
    assert len(list(art.glob("*.owl"))) == 2


def test_manifest_records_counts(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s10(_make_db(), tmp_path)
    S11.run()
    lines = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["stage"] == "s12_export_owl"
    assert rec["counts"]["core_object_properties"] == 13
    assert rec["counts"]["sub_properties"] >= 1
    assert rec["counts"]["disjoint_class_axioms"] == 1


def test_run_raises_when_no_s10_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        S11.run()


# ════════════════════════════════════════════════════════════════════════════
# Property 9 (PBT): sub-property safety over random verb→core mappings.
# Generator: random verb→core mappings. The property asserts every declared
# sub-property carries exactly one subPropertyOf a core property and no own
# domain/range/characteristic/disjointness axiom.
# ════════════════════════════════════════════════════════════════════════════
_verbs = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=10)
_cores = st.sampled_from(CORE_PROPERTIES)


@st.composite
def _mapping(draw):
    keys = draw(st.lists(_verbs, min_size=0, max_size=8, unique=True))
    # Keep only verbs with a non-empty slug, and ensure the SLUGS are unique so
    # two distinct verbs cannot map onto the same sub-property URI (a real
    # many-to-one slug collision the design documents, out of scope for P9).
    seen: set[str] = set()
    filtered = {}
    for k in keys:
        slug = C.get_uri_name(k)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        filtered[k] = draw(_cores)
    return filtered


@settings(max_examples=100, deadline=None)
@given(mapping=_mapping())
def test_property9_pbt_subproperty_safety(mapping):
    """PBT for Property 9: for ANY verb→core mapping, S11's sub-property layer is
    safe — each sub-property narrows exactly one consistent core parent and
    introduces no axiom of its own (R23.2, R23.3)."""
    db = {
        "cnn": {
            "f": 1, "td": 1, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "ML_Model",
            "consolidated_definitions": [],
        },
        "__meta__": {
            "stage": "s11_formalize_properties",
            "property_mapping": mapping,
            "sub_property_layer_omitted": not mapping,
            "uncertain_verbs": [],
        },
    }
    g, counts = S11.build_graph(db)

    forbidden_type_axioms = {
        OWL.TransitiveProperty, OWL.SymmetricProperty, OWL.IrreflexiveProperty,
        OWL.AsymmetricProperty, OWL.FunctionalProperty,
        OWL.InverseFunctionalProperty, OWL.ReflexiveProperty,
    }

    # URIs occupied by the 13 core properties and their inverses; a mined verb
    # colliding with one of these is intentionally NOT emitted as a sub-property
    # (it would corrupt the curated core), so it is excluded from the assertions.
    core_uris = set()
    for _p, _spec in C.PROPERTY_AXIOMS.items():
        core_uris.add(C.ONTOLOGY_NS + _p)
        if _spec.get("inverse"):
            core_uris.add(C.ONTOLOGY_NS + _spec["inverse"])

    for verb, core in mapping.items():
        if not C.get_uri_name(verb):
            # verb slugs to empty → S11 skips it (no degenerate URI); skip here too.
            continue
        sub = URIRef(C.get_uri(verb))
        if str(sub) in core_uris:
            # collides with a core property URI → S11 skips it; not a sub-property.
            continue
        core_uri = URIRef(C.ONTOLOGY_NS + core)
        supers = list(g.objects(sub, RDFS.subPropertyOf))
        assert supers == [core_uri]
        assert list(g.objects(sub, RDFS.domain)) == []
        assert list(g.objects(sub, RDFS.range)) == []
        assert not (set(g.objects(sub, RDF.type)) & forbidden_type_axioms)
        assert list(g.objects(sub, OWL.propertyDisjointWith)) == []
        # parent stays typed (domain+range) so the child inherits a consistent one.
        assert list(g.objects(core_uri, RDFS.domain))
        assert list(g.objects(core_uri, RDFS.range))


# ════════════════════════════════════════════════════════════════════════════
# Property 10 (PBT): definitions preserved end-to-end (S07 → S11).
# Generator: random property DBs flowed through the real S07 grounding transform
# and then through S11's graph builder. The property asserts that for every
# concept present in BOTH the S07 input and the S11 output, its
# consolidated_definitions set at S11 ⊇ the set at S07 (R20.4, R20.3).
# ════════════════════════════════════════════════════════════════════════════
_defs = st.lists(st.text(min_size=1, max_size=14), max_size=5, unique=True)
_targets = st.sampled_from(["image", "kernel", "magic dust", "widget", "images"])
_p10_verbs = st.sampled_from(["process", "use", "transforms", "optimizes"])


@st.composite
def _p10_concept(draw):
    props = {}
    for _ in range(draw(st.integers(min_value=0, max_value=3))):
        verb = draw(_p10_verbs)
        tgt = draw(_targets)
        props.setdefault(verb, {})[tgt] = {
            "f": draw(st.integers(min_value=1, max_value=9)),
            "v": {tgt: 1}, "e": "ex",
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
def _p10_db(draw):
    names = draw(st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_",
                                  min_size=1, max_size=8),
                          min_size=1, max_size=6, unique=True))
    # "__meta__" is S11's reserved metadata key, not a concept — exclude it so the
    # generator can't ask S11 to serialize definitions for the metadata slot.
    names = [n for n in names if n != "__meta__"] or ["concept0"]
    return {name: draw(_p10_concept()) for name in names}


def _seed_master_s02(master_names, tmp_path):
    s02_dir = tmp_path / "artifacts" / "s02_consolidate"
    s02_dir.mkdir(parents=True, exist_ok=True)
    payload = [{"target_concept": n, "corpus_frequency": 5,
                "consolidated_definitions": []} for n in master_names]
    (s02_dir / "20990101-000000__cafebabe.json").write_text(
        json.dumps(payload), encoding="utf-8")


def _seed_s06(db, tmp_path):
    d = tmp_path / "artifacts" / "s06_clean_vocab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "20990101-000000__beefcafe.json").write_text(
        json.dumps(db), encoding="utf-8")


@settings(max_examples=60, deadline=None)
@given(db=_p10_db())
def test_property10_definitions_preserved_end_to_end(db):
    """Property 10: for every concept in both the S07 input and the S11 output,
    the S11 consolidated_definitions set ⊇ the S07 input set (R20.4).

    Flows the generated DB through the REAL S07 grounding transform, adds the
    S10 taxonomy_parent + __meta__ shape S11 expects, then reads back the
    definitions S11 serialized into the OWL graph. State (ARTIFACTS/MANIFEST +
    a fixed RUN_ID) is managed manually because Hypothesis reuses one process.
    """
    tmp_path = Path(tempfile.mkdtemp(prefix="s11_p10_"))
    saved = (C.ARTIFACTS, C.MANIFEST, C.SEED, C.RUN_ID)
    try:
        C.ARTIFACTS = tmp_path / "artifacts"
        C.MANIFEST = tmp_path / "manifest.jsonl"
        C.RUN_ID = "20990101-000000"

        # Master whitelist grounds only image/images/kernel; others demote.
        _seed_master_s02(["image", "kernel"], tmp_path)
        _seed_s06(db, tmp_path)

        s07_out = json.loads(Path(S07.run()).read_text())

        # Shape the S07 output into the S10 contract S11 consumes: every concept
        # needs a taxonomy_parent; add the reserved __meta__ key. Definitions are
        # carried through verbatim (this is exactly what S08/S10 must NOT drop).
        s10_db = {}
        for name, concept in s07_out.items():
            c = dict(concept)
            c.setdefault("taxonomy_parent", "Machine_Learning")
            s10_db[name] = c
        s10_db["__meta__"] = {
            "stage": "s11_formalize_properties",
            "property_mapping": {},
            "sub_property_layer_omitted": True,
            "uncertain_verbs": [],
        }

        g, _counts = S11.build_graph(s10_db)

        for name, in_concept in db.items():
            in_defs = set(in_concept.get("consolidated_definitions", []))
            cls = URIRef(C.get_uri(name))
            out_defs = {str(o) for o in g.objects(cls, RDFS.comment)}
            out_defs |= {str(o) for o in g.objects(cls, SKOS.definition)}
            assert in_defs <= out_defs, (
                f"S11 dropped definitions for '{name}': missing "
                f"{in_defs - out_defs}"
            )
    finally:
        C.ARTIFACTS, C.MANIFEST, C.SEED, C.RUN_ID = saved
        shutil.rmtree(tmp_path, ignore_errors=True)


# ── Knowledge-guided alignment links (mode == "guided") ─────────────────────
def test_guided_emits_skos_alignment_links(monkeypatch):
    """In guided mode, S11 emits skos:exactMatch/closeMatch to reference URIs and
    adds NO subClassOf/logical axioms; baseline emits none."""
    import knowledge as K

    monkeypatch.setattr(C, "SCOP_MODE", "guided", raising=False)
    monkeypatch.setattr(K, "load", lambda force=False: None)
    monkeypatch.setattr(K, "REF_NS", "http://h-da.de/ml-ontology/", raising=False)

    def fake_match(label, definition=None, use_semantic=True):
        s = C.get_uri_name(label)
        if s == "convolutional_neural_network":
            return K.KnowledgeMatch("exact", "convolutional neural network", s, None, 1.0)
        if s == "gradient_descent":
            return K.KnowledgeMatch("semantic", "gradient descent", s, None, 0.9)
        return K.KnowledgeMatch("none")
    monkeypatch.setattr(K, "match", fake_match)

    g, counts = S11.build_graph(_make_db())

    ns = "http://h-da.de/ml-ontology/"
    cnn = URIRef(C.get_uri("convolutional_neural_network"))
    gd = URIRef(C.get_uri("gradient_descent"))
    assert (cnn, SKOS.exactMatch, URIRef(ns + "convolutional_neural_network")) in g
    assert (gd, SKOS.closeMatch, URIRef(ns + "gradient_descent")) in g
    assert counts["kg_alignment_links"] >= 2


def test_baseline_emits_no_alignment_links(monkeypatch):
    monkeypatch.setattr(C, "SCOP_MODE", "baseline", raising=False)
    g, counts = S11.build_graph(_make_db())
    assert counts["kg_alignment_links"] == 0
    assert len(list(g.triples((None, SKOS.exactMatch, None)))) == 0
    assert len(list(g.triples((None, SKOS.closeMatch, None)))) == 0
