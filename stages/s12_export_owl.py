"""
s11_export_owl.py — Stage 11: export the OWL-DL ontology (Port+Extend) — R12, R16, R20, R23.

(Task 17 smoke test: trivial no-op comment to change this stage's code hash and
demonstrate code-hash discrimination on re-run — Requirement 1.2.)

Input : latest artifacts/s10_formalize_properties/*.json  (the formalized DB:
        every concept carries a `taxonomy_parent`, its `props` keyed by the 13
        core object properties (`{core_prop: {target: {f, v, e[, sf]}}}`), any
        `literal_annotations` ({prop, value, weight, raw_verbs}), its
        `consolidated_definitions`, and — under the reserved `__meta__` key —
        the verb→core `property_mapping` for the sub-property layer).
Output: artifacts/s11_export_owl/<RUN_ID>__<codehash>.owl  (`s11_ontology.owl`,
        RDF/XML). Never overwritten; one versioned file per run (R1.1).
LLM   : no. This stage is purely deterministic serialization.

Port (from the original master_ontology_pipeline.py OWL block, preserved
byte-identical under scripts/route_db/): declare concepts + every referenced
parent as `owl:Class`; emit `subClassOf` from the taxonomy; reify each property
triple to attach its extraction weight + originating raw verbs; render demoted
`literal_annotations` as annotations rather than object-property edges (R12.3).

Extend (the genuine OWL-DL / quality work — R16, R20, R23):
  * The 13 core properties are emitted as `owl:ObjectProperty` WITH their
    domain/range, inverses, and characteristics read verbatim from the curated
    `common.PROPERTY_AXIOMS` table (never LLM-written — R16.7). Transitive /
    Symmetric / Irreflexive / Asymmetric map to the matching OWL characteristic
    classes; each inverse is declared and linked with `owl:inverseOf` (R16.3/4).
  * The five top-level domain classes are asserted **pairwise disjoint**
    (`owl:AllDisjointClasses`); ML leaf disjointness is applied cautiously — it
    is deliberately OMITTED here so classification noise cannot force a spurious
    inconsistency (R16.6).
  * The mined sub-property layer (R23): every verb in `__meta__.property_mapping`
    is declared `subPropertyOf` its mapped core property and NOTHING ELSE — it
    introduces no domain/range/characteristic/disjointness axiom of its own, so
    it only narrows a consistent parent and can never make the ontology
    inconsistent (R23.2, R23.3). When S10 omitted the layer the mapping is empty
    and no sub-property is declared, while the 13 core still apply (R23.5).
  * Definitions & synonyms (R20): each class carries its `consolidated_definitions`
    as both `rdfs:comment` and `skos:definition` (R20.3); merged surface forms
    (`sf`, recorded by S06/S07) are emitted as `skos:altLabel` on the canonical
    class (R20.1).

Uses the SINGLE shared `common.get_uri` slug helper so S11's URIs can never
disagree with S09's (R6.2). Exposes `run() -> Path` (R13.3).
"""

import re
import sys
from pathlib import Path

from rdflib import Graph, Literal, RDF, RDFS, OWL, Namespace, URIRef, BNode
from rdflib.namespace import XSD, SKOS

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s12_export_owl"

# Reserved, non-concept top-level key carrying S10's run metadata (R23).
META_KEY = "__meta__"

ONTO_NS = Namespace(C.ONTOLOGY_NS)

# OWL characteristic name → the OWL class a property of that kind is typed with.
_CHARACTERISTIC_CLASS = {
    "Transitive": OWL.TransitiveProperty,
    "Symmetric": OWL.SymmetricProperty,
    "Irreflexive": OWL.IrreflexiveProperty,
    "Asymmetric": OWL.AsymmetricProperty,
    "Functional": OWL.FunctionalProperty,
    "InverseFunctional": OWL.InverseFunctionalProperty,
    "Reflexive": OWL.ReflexiveProperty,
}


def _format_label(cls: str) -> str:
    """Human-readable, valid label for an ontology concept.

    1. Strips case-insensitive [NEW] prefix.
    2. Replaces '&' with 'and'.
    3. Preserves trailing domain symbols (like '++' in 'k-means++').
    4. Splits PascalCase boundaries (e.g. BinarizedNeuralNetwork -> Binarized Neural Network).
    5. Deletes special characters between words except hyphens '-' and underscores '_'.
    6. Formats as clean Title Case with spaces.
    """
    s = str(cls).strip()
    s = re.sub(r"^\[NEW\][\s_]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[NEW\][\s_]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*&\s*", " and ", s)

    trailing_match = re.search(r"([^a-zA-Z0-9\s\-_)]+)$", s)
    trailing_sym = ""
    if trailing_match:
        sym = trailing_match.group(1)
        if sym in ("++", "+", "#", "*"):
            trailing_sym = sym
            s = s[:-len(trailing_sym)].rstrip()

    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"[^a-zA-Z0-9\s\-_]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    label = s.replace("_", " ").title()
    if trailing_sym:
        label += trailing_sym
    return label


def _uri(name: str) -> URIRef:
    """Full URIRef for a concept/target/property name via the shared slug (R6.2)."""
    return URIRef(C.get_uri(name))


def _class_ref(name: str) -> URIRef:
    """Class reference for a domain/range token: ``owl:Thing`` maps to OWL.Thing,
    everything else to its slugged class URI."""
    return OWL.Thing if name == "owl:Thing" else _uri(name)


def build_graph(db: dict) -> tuple[Graph, dict]:
    """Build the OWL-DL graph for ``db`` and return (graph, counts).

    Pure function (no I/O) so tests can exercise it directly on a hand-built DB.
    ``db`` is the S10 output shape (concepts + the reserved ``__meta__`` key).
    """
    g = Graph()
    g.bind("ml", ONTO_NS)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("skos", SKOS)

    onto_uri = URIRef(C.ONTOLOGY_NS.rstrip("#"))
    g.add((onto_uri, RDF.type, OWL.Ontology))
    g.add((onto_uri, RDFS.label,
           Literal("Machine Learning Concepts Ontology", lang="en")))

    # Custom annotation properties for the reified metadata.
    for ann, label in (("extraction_weight", "Extraction Weight"),
                       ("raw_extracted_verb", "Raw Extracted Verb"),
                       ("corpus_frequency", "Corpus Frequency")):
        g.add((ONTO_NS[ann], RDF.type, OWL.AnnotationProperty))
        g.add((ONTO_NS[ann], RDFS.label, Literal(label, lang="en")))

    meta = db.get(META_KEY, {}) or {}
    concepts = {k: v for k, v in db.items() if k != META_KEY}

    # ── 1. Collect every class that must be declared ─────────────────────
    #    concepts, their taxonomy parents, every property target, the shared
    #    domain skeleton, and every domain/range class named in PROPERTY_AXIOMS.
    all_classes: set[str] = set(concepts.keys())
    for data in concepts.values():
        parent = data.get("taxonomy_parent")
        if parent and parent != "owl:Thing":
            all_classes.add(parent)
        for targets in (data.get("props") or {}).values():
            all_classes.update(targets.keys())
    all_classes.update(C.TOP_LEVEL_DOMAINS)
    all_classes.update(C.ML_LEAVES)
    for spec in C.PROPERTY_AXIOMS.values():
        for token in (spec.get("domain"), spec.get("range")):
            if token and token != "owl:Thing":
                all_classes.add(token)

    # ── 2. Declare classes (+ label, definitions, alt-labels) ────────────
    definitions_emitted = 0
    alt_labels_emitted = 0
    emitted_class_labels: set[URIRef] = set()
    for cls in sorted(all_classes):
        uri = _uri(cls)
        g.add((uri, RDF.type, OWL.Class))
        if uri not in emitted_class_labels:
            label = _format_label(cls)
            g.add((uri, RDFS.label, Literal(label, lang="en")))
            emitted_class_labels.add(uri)

        data = db.get(cls, {}) or {}
        # R20.3: definitions as BOTH rdfs:comment and skos:definition.
        for definition in data.get("consolidated_definitions", []) or []:
            if not definition:
                continue
            g.add((uri, RDFS.comment, Literal(definition, lang="en")))
            g.add((uri, SKOS.definition, Literal(definition, lang="en")))
            definitions_emitted += 1

    # ── 2b. Knowledge-guided alignment links (mode == "guided", R-KG) ─────
    #    Emit interoperability links from each generated class to the guiding
    #    reference ontology (ML Ontology) via SKOS mapping properties:
    #      exact/lexical match  -> skos:exactMatch
    #      semantic match       -> skos:closeMatch
    #    This adds NO subClassOf/logical axioms (cannot affect reasoning or
    #    consistency); it only annotates alignment. In baseline mode the block is
    #    inert, so the baseline OWL is unchanged.
    alignment_links = 0
    if getattr(C, "SCOP_MODE", "baseline") == "guided":
        import knowledge as K
        K.load()
        ref_base = K.REF_NS
        for cls in sorted(all_classes):
            m = K.match(cls)
            if not m.matched or not m.ref_slug:
                continue
            ref_uri = URIRef(ref_base + m.ref_slug)
            pred = SKOS.exactMatch if m.kind in ("exact", "lexical") else SKOS.closeMatch
            g.add((_uri(cls), pred, ref_uri))
            alignment_links += 1
        print(f"🧭 Guided mode: emitted {alignment_links} skos alignment link(s) "
              f"to the reference ontology.")

    # ── 3. subClassOf from the taxonomy ──────────────────────────────────
    #    URIs are many-to-one: several DB keys can slugify to the same class
    #    (e.g. "Signal Processing" vs "Signal_Processing"). If those variants have
    #    DIFFERENT parents, emitting a subClassOf for each would place ONE class
    #    under multiple parents — and if two of those parents are pairwise-disjoint
    #    top-level domains, the class becomes unsatisfiable (owl:Nothing) and the
    #    reasoner reports the ontology inconsistent. So we collapse by child URI
    #    and emit exactly ONE parent per class, chosen deterministically:
    #      prefer a non-domain (more specific) parent, then lexicographic slug.
    child_to_parents: dict[str, set] = {}
    for concept, data in concepts.items():
        parent = data.get("taxonomy_parent", "owl:Thing")
        if not parent or parent == "owl:Thing":
            continue
        c_slug, p_slug = C.get_uri_name(concept), C.get_uri_name(parent)
        if not c_slug or not p_slug or c_slug == p_slug:
            continue                     # skip empty slugs and self-loops
        child_to_parents.setdefault(c_slug, set()).add(parent)

    _domain_slugs = {C.get_uri_name(d) for d in C.TOP_LEVEL_DOMAINS}

    def _pick_parent(parents: set) -> str:
        # Prefer a specific (non-domain) parent over a bare top-level domain;
        # break ties lexicographically on the slug for determinism.
        ranked = sorted(parents,
                        key=lambda p: (C.get_uri_name(p) in _domain_slugs,
                                       C.get_uri_name(p)))
        return ranked[0]

    subclass_axioms = 0
    collisions_resolved = 0
    for c_slug, parents in sorted(child_to_parents.items()):
        chosen = _pick_parent(parents)
        if len({C.get_uri_name(p) for p in parents}) > 1:
            collisions_resolved += 1
        g.add((ONTO_NS[c_slug], RDFS.subClassOf, _uri(chosen)))
        subclass_axioms += 1
    if collisions_resolved:
        print(f"   ⚠️ Resolved {collisions_resolved} URI collision(s) with "
              f"conflicting parents to a single deterministic parent "
              f"(prevents disjoint-domain unsatisfiability).")

    # ── 3b. Anchor referenced-only classes so NO class is orphaned ───────
    #    Some classes are declared only because they are a property target or a
    #    taxonomy_parent of another concept, yet carry no taxonomy_parent of their
    #    own (they were never keyed nodes). Without a subClassOf edge they float
    #    free of every top-level domain (S12 orphan_count). Attach each such class
    #    under Machine_Learning (the domain-reachable catch-all, matching S09a's
    #    root-sweep) so every declared class reaches a top-level domain.
    _ml_anchor = "Machine_Learning"
    _domain_and_skeleton = ({C.get_uri_name(d) for d in C.TOP_LEVEL_DOMAINS}
                            | {C.get_uri_name(s) for s in C.SKELETON}
                            | {C.get_uri_name(leaf) for leaf in C.ML_LEAVES})
    _has_parent = set(child_to_parents.keys())
    anchored_referenced = 0
    for cls in sorted(all_classes):
        c_slug = C.get_uri_name(cls)
        if not c_slug or c_slug in _has_parent or c_slug in _domain_and_skeleton:
            continue
        g.add((ONTO_NS[c_slug], RDFS.subClassOf, _uri(_ml_anchor)))
        subclass_axioms += 1
        anchored_referenced += 1
    if anchored_referenced:
        print(f"   🌱 Anchored {anchored_referenced} referenced-only class(es) "
              f"under '{_ml_anchor}' (no class left orphaned).")

    # ── 4. The 13 core object properties WITH their curated axioms ───────
    core_props_emitted = 0
    for prop, spec in C.PROPERTY_AXIOMS.items():
        p_uri = ONTO_NS[prop]
        g.add((p_uri, RDF.type, OWL.ObjectProperty))
        g.add((p_uri, RDFS.label, Literal(prop, lang="en")))
        g.add((p_uri, RDFS.domain, _class_ref(spec["domain"])))
        g.add((p_uri, RDFS.range, _class_ref(spec["range"])))

        for ch in spec.get("characteristics", []) or []:
            ch_class = _CHARACTERISTIC_CLASS.get(ch)
            if ch_class is not None:
                g.add((p_uri, RDF.type, ch_class))

        inverse = spec.get("inverse")
        if inverse:
            inv_uri = ONTO_NS[inverse]
            g.add((inv_uri, RDF.type, OWL.ObjectProperty))
            g.add((inv_uri, RDFS.label, Literal(inverse, lang="en")))
            g.add((p_uri, OWL.inverseOf, inv_uri))
            # An inverse property's domain/range are the SWAP of the forward
            # property's (if optimizes: ML_Algorithm -> ML_Objective, then
            # isOptimizedBy: ML_Objective -> ML_Algorithm). Declaring them removes
            # the OOPS! P11 "missing domain or range" pitfall and is logically
            # entailed by the inverse axiom anyway.
            g.add((inv_uri, RDFS.domain, _class_ref(spec["range"])))
            g.add((inv_uri, RDFS.range, _class_ref(spec["domain"])))
        core_props_emitted += 1

    # ── 5. Mined sub-property layer (subPropertyOf ONLY — R23.2/3) ────────
    property_mapping = meta.get("property_mapping", {}) or {}
    # URIs already occupied by the 13 core properties AND their inverses. A mined
    # verb whose slug collides with one of these must NOT be re-emitted as a
    # sub-property: the core property already carries a domain/range/inverse, so
    # adding `subPropertyOf` on the same URI would corrupt the curated core and
    # violate sub-property safety (the sub-property would appear to own a domain).
    _core_uris = set()
    for _p, _spec in C.PROPERTY_AXIOMS.items():
        _core_uris.add(str(ONTO_NS[_p]))
        if _spec.get("inverse"):
            _core_uris.add(str(ONTO_NS[_spec["inverse"]]))
    sub_props_emitted = 0
    sub_props_skipped_core = 0
    for verb, core in property_mapping.items():
        if core not in C.PROPERTY_AXIOMS:
            # Only ever narrow one of the 13 curated core properties.
            continue
        if not C.get_uri_name(verb):
            # A verb that slugs to the empty string would collide with the
            # ontology namespace root — skip it rather than emit a degenerate URI.
            continue
        sub_uri = _uri(verb)
        if str(sub_uri) in _core_uris:
            # The mined verb IS one of the core properties (or a core inverse);
            # never redeclare it as a sub-property of itself/another core.
            sub_props_skipped_core += 1
            continue
        # A sub-property declares its type + EXACTLY ONE subPropertyOf and
        # nothing else: no domain/range/characteristic/disjointness of its own.
        g.add((sub_uri, RDF.type, OWL.ObjectProperty))
        g.add((sub_uri, RDFS.subPropertyOf, ONTO_NS[core]))
        sub_props_emitted += 1
    if sub_props_skipped_core:
        print(f"   ⚠️ Skipped {sub_props_skipped_core} mined verb(s) that collide "
              f"with a core property URI (kept the curated core intact).")

    # ── 6. Property triples + reification (weight + raw verbs) ────────────
    #    Also emit skos:altLabel from merged surface forms on the target edges.
    triples_emitted = 0
    for concept, data in concepts.items():
        c_uri = _uri(concept)
        for core_prop, targets in (data.get("props") or {}).items():
            # props are already keyed to the 13 core by S10; guard anyway.
            prop_uri = ONTO_NS[core_prop] if core_prop in C.PROPERTY_AXIOMS \
                else ONTO_NS["hasCharacteristic"]
            for target, t_data in targets.items():
                t_uri = _uri(target)
                # 6a. the logical edge.
                g.add((c_uri, prop_uri, t_uri))

                # 6b. reify to attach extraction weight + raw verbs.
                stmt = BNode()
                g.add((stmt, RDF.type, RDF.Statement))
                g.add((stmt, RDF.subject, c_uri))
                g.add((stmt, RDF.predicate, prop_uri))
                g.add((stmt, RDF.object, t_uri))
                g.add((stmt, ONTO_NS.extraction_weight,
                       Literal(int(t_data.get("f", 1)), datatype=XSD.integer)))
                raw_verbs = list((t_data.get("v") or {}).keys())
                if raw_verbs:
                    g.add((stmt, ONTO_NS.raw_extracted_verb,
                           Literal(", ".join(raw_verbs), lang="en")))
                triples_emitted += 1

                # 6c. merged surface forms → skos:altLabel on the target (R20.1).
                for sform in t_data.get("sf", []) or []:
                    if sform:
                        g.add((t_uri, SKOS.altLabel, Literal(sform, lang="en")))
                        alt_labels_emitted += 1

    # ── 7. literal_annotations rendered as annotations (R12.3) ────────────
    literal_annotations_emitted = 0
    for concept, data in concepts.items():
        c_uri = _uri(concept)
        for ann in data.get("literal_annotations", []) or []:
            verbs_str = ", ".join(ann.get("raw_verbs", []) or [])
            value = ann.get("value", "")
            literal_text = f"[{verbs_str}] {value}" if verbs_str else str(value)
            g.add((c_uri, RDFS.comment, Literal(literal_text, lang="en")))
            literal_annotations_emitted += 1

    # ── 8. Top-level domains pairwise disjoint (leaves cautiously — R16.6) ─
    disjoint_axioms = 0
    domain_uris = [_uri(d) for d in C.TOP_LEVEL_DOMAINS]
    if len(domain_uris) >= 2:
        node = BNode()
        g.add((node, RDF.type, OWL.AllDisjointClasses))
        members = BNode()
        # Build an RDF list of the domain classes for owl:members.
        from rdflib.collection import Collection
        Collection(g, members, domain_uris)
        g.add((node, OWL.members, members))
        disjoint_axioms = 1

    counts = {
        "classes": len(all_classes),
        "core_object_properties": core_props_emitted,
        "sub_properties": sub_props_emitted,
        "sub_property_layer_omitted": meta.get("sub_property_layer_omitted", False),
        "subclass_axioms": subclass_axioms,
        "property_triples": triples_emitted,
        "definitions_emitted": definitions_emitted,
        "alt_labels_emitted": alt_labels_emitted,
        "literal_annotations": literal_annotations_emitted,
        "disjoint_class_axioms": disjoint_axioms,
        "kg_alignment_links": alignment_links,
    }
    return g, counts


def run() -> Path:
    print("🚀 S11: exporting the OWL-DL ontology (curated axiom box + sub-properties)...")

    in_path = C.latest_output("s11_formalize_properties", ext="json") or C.require_latest("s10_formalize_properties", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)

    g, counts = build_graph(db)

    out_path = C.output_path(STAGE, __file__, ext="owl")
    g.serialize(destination=str(out_path), format="xml")

    C.write_manifest(STAGE, __file__, in_path=in_path, out_path=out_path,
                     counts=counts,
                     extra={"sub_property_layer_omitted":
                            counts["sub_property_layer_omitted"]})
    print(f"[{STAGE}] OWL export complete -> {out_path}")
    print(f"   classes={counts['classes']}, "
          f"core_props={counts['core_object_properties']}, "
          f"sub_props={counts['sub_properties']}, "
          f"subClassOf={counts['subclass_axioms']}, "
          f"triples={counts['property_triples']}, "
          f"disjoint={counts['disjoint_class_axioms']}")

    onto_dir = Path(__file__).resolve().parent.parent / "ontologies"
    if onto_dir.exists():
        import shutil
        mode = getattr(C, "SCOP_MODE", "baseline") or "baseline"
        target_file = onto_dir / f"scop_{mode}.owl"
        shutil.copyfile(out_path, target_file)
        print(f"   📋 Mirrored export to {target_file}")

    return out_path


if __name__ == "__main__":
    run()
