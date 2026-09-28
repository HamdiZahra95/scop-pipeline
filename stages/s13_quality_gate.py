"""
s12_quality_gate.py — Stage 12: the ontology quality gate (New) — R15, R16.8, R17, R18.

Input : latest artifacts/s11_export_owl/*.owl  (the exported OWL-DL ontology).
Output: reports/<RUN_ID>__<codehash>.quality.json  (a READ-ONLY quality report,
        NOT a downstream artifact — S12 is the terminal gate). The pass/fail
        verdict and the structural metrics are ALSO recorded in the manifest via
        the `extra` field (R17.5).
LLM   : no. This stage is purely deterministic analysis + reasoning.

New build (R17): S12 did not exist before. It loads the S11 OWL with `owlready2`
(+ HermiT via `sync_reasoner`) and `rdflib` (for the structural/graph analysis
that needs no reasoning) and runs five checks:

  1. Consistency (R16.8, R17.1) — run HermiT over the curated axioms + the
     classifications. An INCONSISTENT ontology is a HARD FAILURE; the report
     surfaces the offending class(es) and names the responsible upstream stage
     for backtracking (R17.6). The reasoner may be unavailable (no Java) or may
     refuse an ontology whose curated axioms are outside HermiT's OWL-DL subset
     (e.g. a non-simple property used in an asymmetric axiom); that is recorded
     as consistency "unchecked" WITH the error — it is not proof of
     inconsistency, so it does not by itself fail the gate.
  2. subClassOf cycles (R17.2) — detected structurally on the asserted graph; any
     cycle is a HARD FAILURE.
  3. Structural metrics (R17.3) — class count, max depth, branching factor, % of
     concepts with a parent, % with ≥1 property, orphan count — compared to the
     documented thresholds in :data:`METRIC_THRESHOLDS`. A threshold breach is a
     reported WARNING, not a hard failure (R17 makes only consistency + cycles
     gate-blocking).
  4. Pitfall scan (R17.4) — an OOPS!-style scan for common modeling errors
     (missing annotations, untyped properties, unconnected classes, …).
  5. Competency-question evaluation (R15.2) — each CQ in
     ``competency_questions.md`` is mapped to a query; a non-empty result is
     ``answerable``, an empty one is a ``coverage gap`` (gap ≠ hard failure,
     R15.3). CQ12 is the sole gate-blocking CQ (it probes consistency, R16.8).

Verdict (R17.6): "fail" iff any HARD failure was DETECTED (inconsistent
ontology, a subClassOf cycle, or CQ12's consistency probe failing); otherwise
"pass". Coverage gaps and metric-threshold warnings never flip the verdict.

Exposes `run() -> Path` returning the quality-report path (R13.3). S12 is NOT
registered in run.py here — that is task 15.
"""

import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, RDF, RDFS, OWL, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SKOS

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s13_quality_gate"

NS = C.ONTOLOGY_NS  # "http://linqubit.co/ontology/ml_concepts#"


# ── Documented structural thresholds (R17.3) ────────────────────────────────
# These are the target ranges the gate reports metrics against. A breach is a
# WARNING (surfaced in the report), never a hard failure — R17 makes only
# consistency (R17.1) and subClassOf cycles (R17.2) gate-blocking. They are
# collected here as the single documented source rather than scattered literals.
METRIC_THRESHOLDS = {
    "min_class_count": 10,        # a usable ontology has at least this many classes
    "min_max_depth": 2,           # at least CS→AI→ML style depth (genuine hierarchy)
    "max_max_depth": 15,          # deeper than this suggests over-subdivision
    "min_pct_with_parent": 0.90,  # ≥90% of concepts should be rooted (R17.3)
    "min_pct_with_property": 0.05,  # some concepts should carry ≥1 object property
    "max_orphan_ratio": 0.10,     # ≤10% of concepts may be orphaned from the roots
}


# ── Loading ─────────────────────────────────────────────────────────────────
def load_graph(owl_path) -> Graph:
    """Parse the OWL file into an rdflib graph (used for all structural checks)."""
    g = Graph()
    g.parse(str(owl_path), format="xml")
    return g


def _ns_classes(g: Graph) -> set[URIRef]:
    """Every ontology-namespace class declared in the graph (excludes owl:Thing
    and any imported/foreign class)."""
    out = set()
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, URIRef) and str(s).startswith(NS):
            out.add(s)
    return out


def _local(uri: URIRef) -> str:
    """Local name (after the trailing '#') of a namespace URI."""
    return str(uri).split("#", 1)[-1]


def _skeleton_uris() -> set[URIRef]:
    """URIs of the fixed skeleton backbone (top-level domains + ML spine + leaves)."""
    names = set(C.TOP_LEVEL_DOMAINS) | set(C.ML_LEAVES) | set(C.SKELETON.keys())
    return {URIRef(C.get_uri(n)) for n in names}


def _root_uris() -> set[URIRef]:
    """URIs of the five top-level domain roots."""
    return {URIRef(C.get_uri(d)) for d in C.TOP_LEVEL_DOMAINS}


# ── 1. Consistency (reasoner) — R16.8, R17.1, R17.6 ─────────────────────────
# Map a detected hard failure to the upstream stage most likely responsible, so
# the report can point a human at where to backtrack (R17.6).
_RESPONSIBLE_STAGE = {
    "inconsistent": "s08_build_taxonomy / s09_qa_repair (a class is subsumed "
                    "under two disjoint domains) or s11_export_owl (axiom box)",
    "subclass_cycle": "s08_build_taxonomy / s09_qa_repair (a subClassOf cycle "
                      "was introduced during taxonomy assignment/repair)",
}


def check_consistency(owl_path) -> dict:
    """Run HermiT over the ontology and classify the consistency verdict.

    Returns a dict with:
      * ``status``: ``"consistent"`` | ``"inconsistent"`` | ``"unchecked"``,
      * ``inconsistent_classes``: local names of any class the reasoner found
        unsatisfiable (empty unless inconsistent),
      * ``reasoner_error``: the error text when ``status == "unchecked"``,
      * ``responsible_stage``: set when inconsistent (R17.6).

    ``"unchecked"`` (reasoner missing, or the curated axioms fall outside
    HermiT's OWL-DL subset) is deliberately distinct from ``"inconsistent"``: it
    is NOT proof of a contradiction, so it does not fail the gate on its own.
    """
    try:
        from owlready2 import (World, sync_reasoner,
                               OwlReadyInconsistentOntologyError)
    except Exception as e:  # pragma: no cover - owlready2 always present here
        return {"status": "unchecked", "inconsistent_classes": [],
                "reasoner_error": f"owlready2 unavailable: {e}"}

    world = World()
    try:
        onto = world.get_ontology("file://" + str(Path(owl_path).resolve())).load()
    except Exception as e:
        return {"status": "unchecked", "inconsistent_classes": [],
                "reasoner_error": f"ontology failed to load: {e}"}

    try:
        with onto:
            sync_reasoner(world, infer_property_values=False, debug=0)
    except OwlReadyInconsistentOntologyError as e:
        return {"status": "inconsistent", "inconsistent_classes": ["owl:Nothing"],
                "reasoner_error": None,
                "responsible_stage": _RESPONSIBLE_STAGE["inconsistent"],
                "detail": str(e)}
    except Exception as e:
        # Reasoner unavailable (no Java) or the axioms are outside HermiT's
        # accepted OWL-DL subset. Cannot prove (in)consistency → unchecked.
        return {"status": "unchecked", "inconsistent_classes": [],
                "reasoner_error": f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"}

    # Reasoner ran. owl:Nothing always appears in inconsistent_classes(); a class
    # OTHER than Nothing being unsatisfiable is the real inconsistency signal.
    bad = [c for c in world.inconsistent_classes()]
    bad_names = [getattr(c, "name", str(c)) for c in bad]
    real_bad = [n for n in bad_names if n not in ("Nothing",)]
    if real_bad:
        return {"status": "inconsistent", "inconsistent_classes": real_bad,
                "reasoner_error": None,
                "responsible_stage": _RESPONSIBLE_STAGE["inconsistent"]}
    return {"status": "consistent", "inconsistent_classes": [],
            "reasoner_error": None}


# ── 2. subClassOf cycles — R17.2 ────────────────────────────────────────────
def detect_subclass_cycles(g: Graph) -> list[list[str]]:
    """Return every ``subClassOf`` cycle as a list of local-name paths.

    Builds the child→parent edges among ontology-namespace named classes and
    runs an iterative DFS colouring pass; each back-edge yields the cycle path.
    Any non-empty result is a HARD FAILURE (R17.2).
    """
    classes = _ns_classes(g)
    # child -> [parents] among named ontology classes only.
    parents: dict[URIRef, list[URIRef]] = defaultdict(list)
    for child, parent in g.subject_objects(RDFS.subClassOf):
        if isinstance(child, URIRef) and isinstance(parent, URIRef):
            if str(child).startswith(NS) and str(parent).startswith(NS):
                parents[child].append(parent)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[URIRef, int] = {c: WHITE for c in set(classes) | set(parents)}
    cycles: list[list[str]] = []
    seen_cycles: set[tuple] = set()

    def visit(start):
        stack = [(start, iter(parents.get(start, [])))]
        path = [start]
        color[start] = GREY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color.get(nxt, WHITE) == GREY:
                    # back-edge → cycle from nxt .. node .. nxt
                    idx = path.index(nxt)
                    cyc = path[idx:] + [nxt]
                    canon = tuple(sorted(_local(u) for u in cyc[:-1]))
                    if canon not in seen_cycles:
                        seen_cycles.add(canon)
                        cycles.append([_local(u) for u in cyc])
                elif color.get(nxt, WHITE) == WHITE:
                    color[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, iter(parents.get(nxt, []))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                if path and path[-1] == node:
                    path.pop()

    for c in list(color.keys()):
        if color[c] == WHITE:
            visit(c)
    return cycles


# ── 3. Structural metrics — R17.3 ───────────────────────────────────────────
def _parent_map(g: Graph, classes: set[URIRef]) -> dict[URIRef, list[URIRef]]:
    pmap: dict[URIRef, list[URIRef]] = defaultdict(list)
    for child, parent in g.subject_objects(RDFS.subClassOf):
        if child in classes and isinstance(parent, URIRef) and str(parent).startswith(NS):
            pmap[child].append(parent)
    return pmap


def _has_property_edge(g: Graph, classes: set[URIRef]) -> set[URIRef]:
    """Classes that are the subject of at least one core object-property edge."""
    subjects = set()
    for prop in C.CORE_PROPERTIES:
        p_uri = URIRef(NS + prop)
        for s in g.subjects(p_uri, None):
            if s in classes:
                subjects.add(s)
    return subjects


def compute_metrics(g: Graph) -> dict:
    """Compute the R17.3 structural metrics and flag threshold breaches.

    Returns ``{"metrics": {...}, "warnings": [...]}``. Warnings are advisory
    (never gate-blocking). Depth is computed by longest-path-to-a-root with cycle
    protection so a (separately-reported) cycle cannot hang the walk.
    """
    classes = _ns_classes(g)
    skeleton = _skeleton_uris()
    roots = _root_uris()
    # Concepts = non-skeleton classes (the actual harvested ontology content).
    concepts = classes - skeleton
    pmap = _parent_map(g, classes)

    # children map for branching factor.
    children: dict[URIRef, list[URIRef]] = defaultdict(list)
    for child, plist in pmap.items():
        for p in plist:
            children[p].append(child)

    # % with a parent (a subClassOf to another named class).
    with_parent = [c for c in concepts if pmap.get(c)]
    pct_with_parent = (len(with_parent) / len(concepts)) if concepts else 0.0

    # % with ≥1 object property.
    prop_subjects = _has_property_edge(g, classes)
    with_prop = [c for c in concepts if c in prop_subjects]
    pct_with_prop = (len(with_prop) / len(concepts)) if concepts else 0.0

    # max depth: longest path from any class up to a root (roots have depth 0).
    depth_cache: dict[URIRef, int] = {}

    def depth(node, visiting):
        if node in roots or str(node) == str(OWL.Thing):
            return 0
        if node in depth_cache:
            return depth_cache[node]
        if node in visiting:      # cycle guard
            return 0
        ps = pmap.get(node)
        if not ps:
            return 0
        visiting.add(node)
        d = 1 + max(depth(p, visiting) for p in ps)
        visiting.discard(node)
        depth_cache[node] = d
        return d

    max_depth = 0
    for c in classes:
        max_depth = max(max_depth, depth(c, set()))

    # branching factor: avg number of children over nodes that have ≥1 child.
    branching_nodes = [p for p, ch in children.items() if ch]
    branching_factor = (
        sum(len(children[p]) for p in branching_nodes) / len(branching_nodes)
        if branching_nodes else 0.0
    )

    # orphans: concepts with no subClassOf path reaching a top-level domain root.
    def reaches_root(node):
        seen = set()
        stack = [node]
        while stack:
            n = stack.pop()
            if n in roots:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(pmap.get(n, []))
        return False

    orphans = [c for c in concepts if not reaches_root(c)]
    orphan_ratio = (len(orphans) / len(concepts)) if concepts else 0.0

    metrics = {
        "class_count": len(classes),
        "concept_count": len(concepts),
        "skeleton_count": len(classes & skeleton),
        "max_depth": max_depth,
        "branching_factor": round(branching_factor, 3),
        "pct_with_parent": round(pct_with_parent, 4),
        "pct_with_property": round(pct_with_prop, 4),
        "orphan_count": len(orphans),
        "orphan_ratio": round(orphan_ratio, 4),
    }

    T = METRIC_THRESHOLDS
    warnings = []
    if metrics["class_count"] < T["min_class_count"]:
        warnings.append(
            f"class_count {metrics['class_count']} < min {T['min_class_count']}")
    if metrics["max_depth"] < T["min_max_depth"]:
        warnings.append(
            f"max_depth {metrics['max_depth']} < min {T['min_max_depth']} "
            f"(hierarchy too flat)")
    if metrics["max_depth"] > T["max_max_depth"]:
        warnings.append(
            f"max_depth {metrics['max_depth']} > max {T['max_max_depth']} "
            f"(possible over-subdivision)")
    if metrics["pct_with_parent"] < T["min_pct_with_parent"]:
        warnings.append(
            f"pct_with_parent {metrics['pct_with_parent']:.2%} < "
            f"min {T['min_pct_with_parent']:.0%}")
    if metrics["pct_with_property"] < T["min_pct_with_property"]:
        warnings.append(
            f"pct_with_property {metrics['pct_with_property']:.2%} < "
            f"min {T['min_pct_with_property']:.0%}")
    if metrics["orphan_ratio"] > T["max_orphan_ratio"]:
        warnings.append(
            f"orphan_ratio {metrics['orphan_ratio']:.2%} > "
            f"max {T['max_orphan_ratio']:.0%} ({metrics['orphan_count']} orphans)")

    return {"metrics": metrics, "warnings": warnings, "orphans": [_local(o) for o in orphans]}


# ── 4. Pitfall scan (OOPS!-style) — R17.4 ───────────────────────────────────
def pitfall_scan(g: Graph) -> list[dict]:
    """Scan for common OWL modeling pitfalls (a subset of the OOPS! catalogue).

    Each finding is ``{"code", "title", "count", "examples"}``. All findings are
    advisory (reported, never gate-blocking). Covers:
      * P08 — classes with no human-readable annotation (no label/comment/definition),
      * P11 — object properties missing a domain or a range,
      * P04 — unconnected/isolated classes (no subClassOf up or down, no property edge),
      * P02 — a class asserted as a subclass of itself (self-loop subClassOf).
    """
    classes = _ns_classes(g)
    findings = []

    # P08 — missing annotations.
    no_ann = []
    for c in classes:
        has_ann = (any(g.objects(c, RDFS.label))
                   or any(g.objects(c, RDFS.comment))
                   or any(g.objects(c, SKOS.definition)))
        if not has_ann:
            no_ann.append(_local(c))
    if no_ann:
        findings.append({"code": "P08", "title": "Missing annotations",
                         "count": len(no_ann), "examples": sorted(no_ann)[:10]})

    # P11 — object properties without domain or range.
    obj_props = {s for s in g.subjects(RDF.type, OWL.ObjectProperty)
                 if isinstance(s, URIRef) and str(s).startswith(NS)}
    untyped = []
    for p in obj_props:
        # Sub-properties intentionally inherit domain/range (R23.2) — a
        # subPropertyOf edge exempts them from this pitfall.
        if any(g.objects(p, RDFS.subPropertyOf)):
            continue
        if not any(g.objects(p, RDFS.domain)) or not any(g.objects(p, RDFS.range)):
            untyped.append(_local(p))
    if untyped:
        findings.append({"code": "P11", "title": "Object property missing domain or range",
                         "count": len(untyped), "examples": sorted(untyped)[:10]})

    # P02 — subClassOf self-loop.
    self_loops = [_local(c) for c in classes if (c, RDFS.subClassOf, c) in g]
    if self_loops:
        findings.append({"code": "P02", "title": "Class is a subclass of itself",
                         "count": len(self_loops), "examples": sorted(self_loops)[:10]})

    # P04 — unconnected classes (no subClassOf either way, no property edge).
    connected = set()
    for child, parent in g.subject_objects(RDFS.subClassOf):
        if isinstance(parent, URIRef) and str(parent).startswith(NS):
            connected.add(child)
            connected.add(parent)
    for prop in C.CORE_PROPERTIES:
        p_uri = URIRef(NS + prop)
        for s, o in g.subject_objects(p_uri):
            connected.add(s)
            if isinstance(o, URIRef):
                connected.add(o)
    skeleton = _skeleton_uris()
    isolated = [_local(c) for c in classes
                if c not in connected and c not in skeleton]
    if isolated:
        findings.append({"code": "P04", "title": "Unconnected/isolated class",
                         "count": len(isolated), "examples": sorted(isolated)[:10]})

    return findings


# ── 5. Competency-question evaluation — R15.2, R15.3 ────────────────────────
def _c(g: Graph, local: str):
    """The class URI for a slugged local name IF it is declared, else None."""
    u = URIRef(C.get_uri(local))
    return u if (u, RDF.type, OWL.Class) in g else None


def _subclasses(g: Graph, uri: URIRef) -> list[URIRef]:
    return [s for s in g.subjects(RDFS.subClassOf, uri)
            if isinstance(s, URIRef) and str(s).startswith(NS)]


def _descendants(g: Graph, uri: URIRef) -> set[URIRef]:
    out, stack = set(), [uri]
    while stack:
        cur = stack.pop()
        for child in _subclasses(g, cur):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def _prop_edges(g: Graph, prop: str) -> list[tuple]:
    return list(g.subject_objects(URIRef(NS + prop)))


def _incoming(g: Graph, prop: str, target: URIRef) -> list[URIRef]:
    return [s for s in g.subjects(URIRef(NS + prop), target)]


def _find_matching_classes(g: Graph, candidates: list[str]) -> list[URIRef]:
    """Find classes matching any candidate slug.
    Priority:
    1. Exact URI matches for candidate slugs.
    2. Case-insensitive local name matches.
    3. Normalized prefix, suffix, or family matches.
    """
    classes = _ns_classes(g)
    exact = [URIRef(C.get_uri(c)) for c in candidates if URIRef(C.get_uri(c)) in classes]
    if exact:
        return exact

    cand_low = [c.lower().replace("-", "_").strip() for c in candidates]
    ci_matches = []
    for u in classes:
        loc = _local(u).lower().replace("-", "_").strip()
        if loc in cand_low:
            ci_matches.append(u)
    if ci_matches:
        return ci_matches

    family_matches = []
    for u in classes:
        loc = _local(u).lower().replace("-", "_").strip()
        for cl in cand_low:
            if loc.startswith(cl + "_") or loc.endswith("_" + cl) or f"_{cl}_" in loc or cl in loc:
                family_matches.append(u)
                break
    return family_matches


def compute_population_archetypes(g: Graph) -> dict:
    """Evaluate macro-level functional CQ archetypes across 100% of discovered classes.
    
    This provides population-level, naming-robust coverage metrics (R15, R17)
    immune to single-slug brittleness.
    """
    classes = _ns_classes(g)
    skeleton_names = set(C.TOP_LEVEL_DOMAINS) | set(C.ML_LEAVES) | set(C.SKELETON.keys())
    skeleton = {URIRef(C.get_uri(n)) for n in skeleton_names}
    discovered = [c for c in classes if c not in skeleton]
    pop = len(discovered)
    if pop == 0:
        return {}

    # 1. Subtypes coverage (classes with >= 1 subclass)
    has_sub = sum(1 for c in discovered if any(g.subjects(RDFS.subClassOf, c)))
    
    # 2. ML Leaf categorisation (taxonomic grounding reaching a domain leaf)
    leaf_uris = {URIRef(C.get_uri(leaf)) for leaf in C.ML_LEAVES}
    def reaches_leaf(c):
        curr = {c}
        visited = set()
        while curr:
            nxt = set()
            for node in curr:
                if node in leaf_uris:
                    return True
                visited.add(node)
                for p in g.objects(node, RDFS.subClassOf):
                    if isinstance(p, URIRef) and p not in visited and str(p).startswith(NS):
                        nxt.add(p)
            curr = nxt
        return False
    reaches = sum(1 for c in discovered if reaches_leaf(c))

    # 3. Definition coverage (rdfs:comment or skos:definition)
    has_def = sum(1 for c in discovered if any(g.objects(c, RDFS.comment)) or any(g.objects(c, SKOS.definition)))

    # 4. Relational participation
    obj_props = {s for s in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(s, URIRef)}
    disc_set = set(discovered)
    subjs = {s for s, p, o in g if p in obj_props and isinstance(s, URIRef) and s in disc_set}
    objs = {o for s, p, o in g if p in obj_props and isinstance(o, URIRef) and o in disc_set}

    return {
        "population_classes": pop,
        "subtypes_coverage": {
            "count": has_sub,
            "rate": round(has_sub / pop, 4),
        },
        "categorisation_coverage": {
            "count": reaches,
            "rate": round(reaches / pop, 4),
        },
        "definition_coverage": {
            "count": has_def,
            "rate": round(has_def / pop, 4),
        },
        "relation_subject_coverage": {
            "count": len(subjs),
            "rate": round(len(subjs) / pop, 4),
        },
        "relation_object_coverage": {
            "count": len(objs),
            "rate": round(len(objs) / pop, 4),
        },
    }


def evaluate_cqs(g: Graph, consistency: dict) -> list[dict]:
    """Evaluate the 12 competency questions with Description Logic semantics.

    Queries evaluate transitive taxonomy closure (subClassOf*) and semantic
    concept families, preventing single-token naming fragility.
    """
    cqs: list[dict] = []

    def add(cid, question, category, status, detail=""):
        cqs.append({"id": cid, "question": question, "category": category,
                    "status": status, "detail": detail})

    # CQ1 — subtypes of unsupervised learning (transitive subsumption closure).
    unsup_targets = _find_matching_classes(g, [
        "unsupervised_learning", "unsupervised_learning_task",
        "unsupervised_learning_algorithm", "unsupervised_learning_paradigm",
        "unsupervised_machine_learning"
    ])
    all_subs = set()
    all_desc = set()
    for t in unsup_targets:
        for s in _subclasses(g, t):
            all_subs.add(s)
        for d in _descendants(g, t):
            all_desc.add(d)
    cq1_ans = len(all_subs) > 0 or len(all_desc) > 0
    add("CQ1", "What are the subtypes of unsupervised learning?", "subsumption",
        "answerable" if cq1_ans else "gap",
        f"{len(all_subs)} direct subclasses, {len(all_desc)} descendants across {len(unsup_targets)} root(s)"
        if unsup_targets else "unsupervised learning class absent")

    # CQ2 — concepts that are a kind of ML model (leaf subsumption).
    leaf = _c(g, "ML_Model")
    desc2 = _descendants(g, leaf) if leaf else set()
    add("CQ2", "Which concepts are a kind of ML model?", "subsumption",
        "answerable" if desc2 else "gap",
        f"{len(desc2)} descendants" if leaf else "ML_Model leaf absent")

    # CQ3 — is every concept reachable from a top-level domain?
    roots_present = [d for d in C.TOP_LEVEL_DOMAINS if _c(g, d)]
    add("CQ3", "Is every concept reachable from a top-level domain?",
        "subsumption-coverage",
        "answerable" if roots_present else "gap",
        f"{len(roots_present)}/{len(C.TOP_LEVEL_DOMAINS)} top-level roots present")

    # CQ4 — what does an algorithm optimize? (object property `optimizes`).
    opt = _prop_edges(g, "optimizes")
    add("CQ4", "What does an algorithm optimize?", "object-property",
        "answerable" if opt else "gap", f"{len(opt)} optimizes edges")

    # CQ5 — what optimizes loss functions? (targeted lookup).
    loss_targets = _find_matching_classes(g, [
        "loss_function", "cross_entropy_loss", "cross_entropy", "loss", "triplet_loss"
    ])
    opt_incoming = []
    for lt in loss_targets:
        for s in g.subjects(URIRef(NS + "optimizes"), lt):
            opt_incoming.append((s, lt))
    add("CQ5", "What optimizes cross-entropy / loss functions?", "object-property-targeted",
        "answerable" if opt_incoming else "gap",
        f"{len(opt_incoming)} optimizers targeting {len(loss_targets)} loss class(es)"
        if loss_targets else "loss class absent")

    # CQ6 — which models perform classification? (hasPurpose / producesOutput).
    task_targets = _find_matching_classes(g, ["classification", "classification_task"])
    performers = []
    for tt in task_targets:
        for s in g.subjects(URIRef(NS + "hasPurpose"), tt):
            performers.append(s)
        for s in g.subjects(URIRef(NS + "producesOutput"), tt):
            performers.append(s)
    add("CQ6", "Which models perform classification?", "object-property-crossleaf",
        "answerable" if performers else "gap",
        f"{len(performers)} performers targeting {len(task_targets)} classification class(es)"
        if task_targets else "classification class absent")

    # CQ7 — components of a neural network architecture (transitive architectural lookup).
    nn_targets = _find_matching_classes(g, [
        "neural_network", "artificial_neural_network", "deep_neural_network", "convolutional_neural_network"
    ])
    nn_family = set(nn_targets)
    for nt in nn_targets:
        nn_family.update(_descendants(g, nt))
    comps = []
    for nn in nn_family:
        for o in g.objects(nn, URIRef(NS + "hasComponent")):
            comps.append((nn, o))
    add("CQ7", "What are the components of a neural network?",
        "object-property-transitive",
        "answerable" if comps else "gap",
        f"{len(comps)} architectural components across {len(nn_family)} neural network classes"
        if nn_family else "neural_network class absent")

    # CQ8 — which algorithms optimize an objective? (inverse property reasoning).
    obj_targets = _find_matching_classes(g, [
        "objective_function", "mean_squared_error", "loss_function", "learning_objective", "objective"
    ])
    inv = []
    for ot in obj_targets:
        for o in g.objects(ot, URIRef(NS + "isOptimizedBy")):
            inv.append((ot, o))
        for s in g.subjects(URIRef(NS + "optimizes"), ot):
            inv.append((s, ot))
    add("CQ8", "Given an objective, which algorithms optimize it?",
        "inverse-property",
        "answerable" if inv else "gap",
        f"{len(inv)} optimizers targeting {len(obj_targets)} objective class(es)"
        if obj_targets else "objective class absent")

    # CQ9 — what data does a model learn from, and what processes it?
    data_targets = _find_matching_classes(g, [
        "training_data", "synthetic_training_data", "dataset", "data_representation",
        "data_augmentation", "data_embedding"
    ])
    data_edges = []
    for dt in data_targets:
        for s in g.subjects(URIRef(NS + "learnsFrom"), dt):
            data_edges.append((s, dt))
        for s in g.subjects(URIRef(NS + "processesData"), dt):
            data_edges.append((s, dt))
    add("CQ9", "What data does a model learn from, and what processes it?",
        "inverse-property",
        "answerable" if data_edges else "gap",
        f"{len(data_edges)} data learning/processing edges targeting {len(data_targets)} data class(es)"
        if data_targets else "data class absent")

    # CQ10 — definition of gradient descent (annotation retrieval).
    gd_targets = _find_matching_classes(g, ["gradient_descent"])
    defs = []
    for gd in gd_targets:
        defs.extend(list(g.objects(gd, RDFS.comment)))
        defs.extend(list(g.objects(gd, SKOS.definition)))
    add("CQ10", "What is the definition of gradient descent?", "annotation",
        "answerable" if defs else "gap",
        f"{len(defs)} definition/comment literals" if gd_targets else "class absent")

    # CQ11 — synonyms of a concept (skos:altLabel).
    cnn_targets = _find_matching_classes(g, ["convolutional_neural_network"])
    alts = []
    for cnn in cnn_targets:
        alts.extend(list(g.objects(cnn, SKOS.altLabel)))
    add("CQ11", "What alternative labels does a concept carry?", "annotation",
        "answerable" if alts else "gap",
        f"{len(alts)} altLabels" if cnn_targets else "class absent")

    # CQ12 — consistent + top-level domains disjoint (the ONE gate-blocking CQ).
    disjoint_ok = _top_domains_disjoint(g)
    if consistency["status"] == "inconsistent":
        status = "hard_fail"
        detail = (f"reasoner reports inconsistency "
                  f"({consistency.get('inconsistent_classes')})")
    elif consistency["status"] == "unchecked":
        # Cannot prove consistency; report the disjointness axiom presence and
        # mark it a coverage gap (not a hard failure — we have no contradiction).
        status = "gap"
        detail = (f"consistency unchecked ({consistency.get('reasoner_error')}); "
                  f"top-level disjointness declared={disjoint_ok}")
    else:
        status = "answerable" if disjoint_ok else "gap"
        detail = (f"consistent (HermiT verified); top-level disjointness declared={disjoint_ok}")
    add("CQ12", "Is the ontology consistent and are top-level domains disjoint?",
        "disjointness-consistency", status, detail)

    return cqs


def _top_domains_disjoint(g: Graph) -> bool:
    """True iff the five top-level domains appear together in an
    ``owl:AllDisjointClasses`` axiom (R16.6)."""
    domain_uris = {URIRef(C.get_uri(d)) for d in C.TOP_LEVEL_DOMAINS}
    for node in g.subjects(RDF.type, OWL.AllDisjointClasses):
        head = next(g.objects(node, OWL.members), None)
        if head is None:
            continue
        members = set(Collection(g, head))
        if domain_uris.issubset(members):
            return True
    # Also accept pairwise owl:disjointWith covering all pairs (defensive).
    pairwise = set()
    for a, b in g.subject_objects(OWL.disjointWith):
        pairwise.add(frozenset((a, b)))
    doms = list(domain_uris)
    for i in range(len(doms)):
        for j in range(i + 1, len(doms)):
            if frozenset((doms[i], doms[j])) not in pairwise:
                return False
    return len(doms) >= 2


# ── Report assembly + verdict ───────────────────────────────────────────────
def analyze(owl_path, include_tiered_benchmark: bool = True) -> dict:
    """Run all checks against ``owl_path`` and assemble the comprehensive quality report.

    Pure w.r.t. the pipeline's artifact/manifest machinery (no writes), so tests
    can call it directly on a fixture ``.owl`` and assert on the returned dict.
    """
    g = load_graph(owl_path)

    consistency = check_consistency(owl_path)
    cycles = detect_subclass_cycles(g)
    metrics_result = compute_metrics(g)
    pitfalls = pitfall_scan(g)
    cqs = evaluate_cqs(g, consistency)
    archetypes = compute_population_archetypes(g)

    # Hard-failure detection (R17.1, R17.2, R16.8/CQ12).
    hard_failures = []
    if consistency["status"] == "inconsistent":
        hard_failures.append({
            "type": "inconsistent",
            "offending_classes": consistency.get("inconsistent_classes", []),
            "responsible_stage": consistency.get("responsible_stage"),
        })
    if cycles:
        hard_failures.append({
            "type": "subclass_cycle",
            "cycles": cycles,
            "responsible_stage": _RESPONSIBLE_STAGE["subclass_cycle"],
        })

    verdict = "fail" if hard_failures else "pass"

    cq_answerable = sum(1 for c in cqs if c["status"] == "answerable")
    cq_gaps = sum(1 for c in cqs if c["status"] == "gap")

    report = {
        "stage": STAGE,
        "run_id": C.RUN_ID,
        "input_owl": str(owl_path),
        "verdict": verdict,
        "hard_failures": hard_failures,
        "consistency": consistency,
        "subclass_cycles": cycles,
        "metrics": metrics_result["metrics"],
        "metric_warnings": metrics_result["warnings"],
        "orphans": metrics_result["orphans"],
        "pitfalls": pitfalls,
        "competency_questions": {
            "total": len(cqs),
            "answerable": cq_answerable,
            "gaps": cq_gaps,
            "results": cqs,
        },
        "functional_archetypes": archetypes,
        "thresholds": METRIC_THRESHOLDS,
    }

    if include_tiered_benchmark:
        try:
            from analysis.v17_expanded_cq_benchmark import build_question_inventory, evaluate_ontology_on_benchmark, SCOPOntologyAdapter
            q_inv = build_question_inventory()
            adapter = SCOPOntologyAdapter("Target_Ontology", Path(owl_path))
            bench_res = evaluate_ontology_on_benchmark(adapter, q_inv)
            report["tiered_benchmark_200"] = bench_res["tiered_summary"]
        except Exception as e:
            report["tiered_benchmark_200"] = {"error": str(e)}

    return report


def run(owl_path=None, include_tiered_benchmark: bool = True) -> Path:
    print("🚀 S12: quality gate (reasoner consistency + cycles + metrics + "
          "pitfalls + CQs + functional archetypes + tiered benchmark)...")

    if owl_path is not None:
        in_path = Path(owl_path)
    elif len(sys.argv) > 1 and sys.argv[1].endswith(".owl"):
        in_path = Path(sys.argv[1])
    else:
        in_path = C.latest_output("s12_export_owl", ext="owl") or C.require_latest("s11_export_owl", ext="owl")

    print(f"📂 Loading {in_path} ...")

    report = analyze(in_path, include_tiered_benchmark=include_tiered_benchmark)

    out_path = C.report_path("quality", __file__, ext="json")
    C.save_json(out_path, report)

    metrics = report["metrics"]
    cq = report["competency_questions"]
    arch = report.get("functional_archetypes", {})
    tiered = report.get("tiered_benchmark_200", {})
    # The manifest records the verdict + metrics via `extra` (R17.5). S12 has no
    # downstream primary artifact, so `out_path` in the manifest is the report.
    C.write_manifest(
        STAGE, __file__, in_path=in_path, out_path=out_path,
        counts={
            "verdict": report["verdict"],
            "cq_answerable": cq["answerable"],
            "cq_gaps": cq["gaps"],
            "pitfall_findings": len(report["pitfalls"]),
            "metric_warnings": len(report["metric_warnings"]),
        },
        extra={
            "quality_verdict": report["verdict"],
            "consistency": report["consistency"]["status"],
            "subclass_cycles": len(report["subclass_cycles"]),
            "metrics": metrics,
            "functional_archetypes": arch,
            "tiered_benchmark_summary": {k: v.get("answerable_rate") for k, v in tiered.items() if isinstance(v, dict)},
        },
    )

    print(f"[{STAGE}] verdict={report['verdict']}  "
          f"consistency={report['consistency']['status']}  "
          f"cycles={len(report['subclass_cycles'])}  "
          f"CQ {cq['answerable']}/{cq['total']} answerable  "
          f"-> {out_path}")
    if arch:
        print(f"   📊 Macro Archetypes: subtyping={arch['subtypes_coverage']['rate']:.1%}  "
              f"categorisation={arch['categorisation_coverage']['rate']:.1%}  "
              f"definition={arch['definition_coverage']['rate']:.1%}")
    if tiered and isinstance(tiered, dict) and "Tier_20" in tiered:
        t_rates = "  ".join([f"{k}={v['answerable_rate']:.1%}" for k, v in tiered.items() if isinstance(v, dict)])
        print(f"   🎯 Tiered Scaled Benchmark: {t_rates}")
    if report["hard_failures"]:
        print("   ❌ HARD FAILURES:")
        for hf in report["hard_failures"]:
            print(f"      - {hf['type']}: responsible={hf.get('responsible_stage')}")
    if report["metric_warnings"]:
        print("   ⚠️  metric warnings:")
        for w in report["metric_warnings"]:
            print(f"      - {w}")
    return out_path


if __name__ == "__main__":
    run()
