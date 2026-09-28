"""
v10_cq_quality.py — a better competency-question evaluation (deterministic, no LLM).

The pipeline's built-in CQ check (S12 / v04) is a fixed set of 12 questions, each
bound to ONE hardcoded concept slug (e.g. ``unsupervised_learning``,
``gradient_descent``) and scored by bare non-emptiness. For a 2,000-class
ontology that is a spot-check on ~10 entities (~0.5% of classes), and it is
brittle: answerability flips when the taxonomy renames or re-homes a concept for
reasons unrelated to quality. This script replaces that with two population-level,
naming-robust measures that need no LLM and no re-run:

  PART A — Functional coverage rates (intrinsic).
    Each CQ *archetype* (define X, synonyms of X, subtypes of X, categorise X,
    what does X relate to, what relates to X) is evaluated over the FULL set of
    discovered (non-skeleton) classes, iterating real class URIs. We report the
    fraction of the population for which the query returns a non-empty answer —
    a coverage statistic, not a pass/fail on cherry-picked concepts. Reported for
    baseline and guided.

  PART B — Gold-grounded functional subsumption (extrinsic, non-circular).
    Using the three held-out, human-curated references (ACM CCS, ITO, AIO) that
    the pipeline never consumed as guidance, we instantiate the subsumption CQ
    "Is <child> a kind of <parent>?" from expert-asserted is-a pairs and score
    the generated ontology against that key:
      * functional RECALL    — of expert is-a pairs whose BOTH endpoints exist in
        our ontology, how many does our ontology entail (via any is-a path)?
      * functional PRECISION — of the is-a relationships our ontology asserts
        between two concepts that both map to the gold, how many are confirmed by
        the expert hierarchy?
    This is conditional on concept co-presence, so it isolates taxonomic
    correctness from concept coverage (measured separately in v03/v09). It is not
    circular: the answer key is a held-out expert ontology, never the guide.

Guardrail: question SHAPE comes from external archetypes / expert ontologies,
never from the ontology under test — so this does not reintroduce the circularity
of the (removed) balanced-CQ benchmark.

Usage (from pipeline_v2/):
    ./ .venv/bin/python analysis/v10_cq_quality.py
    python analysis/v10_cq_quality.py --no-semantic
    python analysis/v10_cq_quality.py --threshold 0.80
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
from analysis import common as C
from analysis import v03_gold_alignment as v03

MODES = ["baseline", "guided"]
GOLDS = ["ccs", "ito", "aio"]
GOLD_BLURB = v03.GOLD_BLURB

# ML domain-leaf slugs: reaching one of these means a concept is categorised
# under a genuine ML category rather than merely under the top domain spine.
_LEAF_SLUGS = {
    "ml_task", "ml_model", "ml_algorithm", "ml_data_and_representation",
    "ml_objective_and_constraint", "ml_workflow_and_protocol",
    "ml_foundations_and_theory", "ml_infrastructure_and_environment",
    "ml_property_and_quality_attribute", "ml_methodology_and_science_provenance",
}


# ── richer generated-ontology loader (classes, is-a, edges, annotations) ─────
def load_generated_full(owl_path: Path) -> dict:
    from rdflib import Graph, RDF, RDFS, OWL, URIRef
    from rdflib.namespace import SKOS

    g = Graph()
    g.parse(str(owl_path), format="xml")
    ns = C.ONTOLOGY_NS

    classes = {str(s) for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns)}
    label_of = {str(s): str(o) for s, o in g.subject_objects(RDFS.label)
                if str(s) in classes}

    parents = defaultdict(set)
    for c, p in g.subject_objects(RDFS.subClassOf):
        cs, ps = str(c), str(p)
        if cs in classes and isinstance(p, URIRef) and ps.startswith(ns):
            parents[cs].add(ps)

    obj_props = {str(s) for s in g.subjects(RDF.type, OWL.ObjectProperty)
                 if isinstance(s, URIRef)}
    out_edges, in_edges = defaultdict(set), defaultdict(set)
    for s, p, o in g:
        if (str(p) in obj_props and isinstance(s, URIRef) and isinstance(o, URIRef)
                and str(s) in classes and str(o) in classes and str(s) != str(o)):
            out_edges[str(s)].add(str(o))
            in_edges[str(o)].add(str(s))

    has_skos_def, has_comment, has_altlabel = set(), set(), set()
    for s, _ in g.subject_objects(SKOS.definition):
        if str(s) in classes:
            has_skos_def.add(str(s))
    for s, _ in g.subject_objects(RDFS.comment):
        if str(s) in classes:
            has_comment.add(str(s))
    for s, _ in g.subject_objects(SKOS.altLabel):
        if str(s) in classes:
            has_altlabel.add(str(s))

    return {"classes": classes, "label_of": label_of, "parents": dict(parents),
            "obj_props": obj_props, "out_edges": dict(out_edges),
            "in_edges": dict(in_edges), "has_skos_def": has_skos_def,
            "has_comment": has_comment, "has_altlabel": has_altlabel}


def _content_concepts(gen: dict) -> list:
    return [c for c in gen["classes"] if C.local_name(c) not in C.SKELETON_SLUGS]


def _reaches_leaf(concept: str, parents: dict) -> bool:
    for anc in C.transitive_ancestors(parents, concept):
        if C.local_name(anc) in _LEAF_SLUGS:
            return True
    return False


# ── PART A: functional coverage rates over the whole content population ──────
ARCHETYPES = [
    ("define",      "Define <X>. (skos:definition present)"),
    ("comment",     "Describe <X>. (any rdfs:comment present)"),
    ("synonyms",    "What is <X> also called? (skos:altLabel present)"),
    ("subtypes",    "What kinds of <X> are there? (>=1 subclass)"),
    ("categorise",  "Is <X> a model / task / algorithm / ...? (is-a reaches an ML leaf)"),
    ("relates_out", "What does <X> use / optimise / produce? (subject of >=1 relation)"),
    ("relates_in",  "What uses / produces / relates to <X>? (object of >=1 relation)"),
]


def _rate(indicator: list) -> dict:
    ci = C.bootstrap_ci(indicator)
    return {"rate": round(sum(indicator) / len(indicator), 4) if indicator else 0.0,
            "answerable": int(sum(indicator)), "population": len(indicator),
            "ci": [ci["lo"], ci["hi"]]}


def part_a(gen: dict) -> dict:
    concepts = _content_concepts(gen)
    parents = gen["parents"]
    has_child = set()
    for c, ps in parents.items():
        for p in ps:
            has_child.add(p)
    ind = {k: [] for k, _ in ARCHETYPES}
    for c in concepts:
        ind["define"].append(1 if c in gen["has_skos_def"] else 0)
        ind["comment"].append(1 if c in gen["has_comment"] else 0)
        ind["synonyms"].append(1 if c in gen["has_altlabel"] else 0)
        ind["subtypes"].append(1 if c in has_child else 0)
        ind["categorise"].append(1 if _reaches_leaf(c, parents) else 0)
        ind["relates_out"].append(1 if gen["out_edges"].get(c) else 0)
        ind["relates_in"].append(1 if gen["in_edges"].get(c) else 0)
    return {k: _rate(ind[k]) for k, _ in ARCHETYPES}


# ── PART B: gold-grounded functional subsumption precision/recall ────────────
def _direct_gold_pairs(gold, covered_gold: set) -> set:
    """Expert-asserted DIRECT is-a pairs (parent, child) with BOTH endpoints
    present (matched) in the generated ontology."""
    pairs = set()
    for child in covered_gold:
        for par in gold.parents.get(child, ()):
            if par in covered_gold and par != child:
                pairs.add((par, child))
    return pairs


def _direct_gen_pairs(concepts, parents, gen2gold) -> set:
    """DIRECT is-a pairs our ontology asserts between two concepts that both map
    to the gold, expressed in gold-id space."""
    pairs = set()
    for c in concepts:
        mc = gen2gold.get(c)
        if not mc:
            continue
        for par in parents.get(c, ()):
            mp = gen2gold.get(par)
            if mp and mp.gold_id != mc.gold_id:
                pairs.add((mp.gold_id, mc.gold_id))
    return pairs


def part_b_one(gen, gold, *, use_semantic, threshold, model):
    # v03.matches_for expects the (classes, label_of, parents) tuple.
    gen_tuple = (gen["classes"], gen["label_of"], gen["parents"])
    concepts, parents, matches = v03.matches_for(
        gen_tuple, gold, use_semantic=use_semantic, threshold=threshold, model=model)

    out = {}
    for regime in ("strict", "with_semantic"):
        if regime == "with_semantic" and not use_semantic:
            continue
        gen2gold = v03.gen2gold_map(concepts, matches, regime)
        covered_gold, PA, GA = v03.ancestor_sets(concepts, parents, gold, gen2gold)
        gold_direct = _direct_gold_pairs(gold, covered_gold)
        gen_direct = _direct_gen_pairs(concepts, parents, gen2gold)

        # recall: expert DIRECT pair answered via ANY generated is-a path (PA).
        rec_ind = [1 if pair in PA else 0 for pair in gold_direct]
        # precision: our asserted DIRECT pair confirmed as a gold ancestor (GA).
        prec_ind = [1 if pair in GA else 0 for pair in gen_direct]
        rec = C.bootstrap_ci(rec_ind)
        prec = C.bootstrap_ci(prec_ind)
        p, r = prec["point"], rec["point"]
        f1 = round(2 * p * r / (p + r), 4) if (p + r) else 0.0
        out[regime] = {
            "matched_concepts": len(covered_gold),
            "subsumption_recall": {"point": rec["point"], "ci": [rec["lo"], rec["hi"]],
                                   "n_expert_pairs": len(gold_direct)},
            "subsumption_precision": {"point": prec["point"], "ci": [prec["lo"], prec["hi"]],
                                      "n_asserted_pairs": len(gen_direct)},
            "subsumption_f1": f1,
        }
    return out


def part_b(gens: dict, golds: dict, *, use_semantic, threshold):
    model = C.load_embedding_model() if use_semantic else None
    res = {}
    for gname in GOLDS:
        res[gname] = {"blurb": GOLD_BLURB[gname]}
        for mode in MODES:
            res[gname][mode] = part_b_one(
                gens[mode], golds[gname], use_semantic=use_semantic,
                threshold=threshold, model=model)
    return res


# ── report ───────────────────────────────────────────────────────────────────
def render_md(result) -> str:
    cfg = result["config"]
    L = ["# v10. Competency-Question Quality (population + gold-grounded)", "",
         "A naming-robust replacement for the 12 hardcoded-slug CQs. Part~A reports "
         "functional coverage over ALL discovered classes; Part~B reports "
         "gold-grounded functional subsumption precision/recall against held-out "
         "expert ontologies (non-circular).", "",
         f"- baseline OWL: `{Path(result['owls']['baseline']).name}`",
         f"- guided OWL: `{Path(result['owls']['guided']).name}`",
         f"- semantic matching: {'on' if cfg['use_semantic'] else 'off'}; "
         f"threshold {cfg['threshold']}", "",
         "## Part A — functional coverage rates (share of discovered classes)",
         "| CQ archetype | baseline | guided | population |",
         "|---|---|---|---|"]
    labels = dict(ARCHETYPES)
    pop_b = next(iter(result["part_a"]["baseline"].values()))["population"]
    pop_g = next(iter(result["part_a"]["guided"].values()))["population"]
    for k, _ in ARCHETYPES:
        b = result["part_a"]["baseline"][k]
        g = result["part_a"]["guided"][k]
        L.append(f"| {labels[k]} | {b['rate']:.3f} ({b['answerable']}/{b['population']}) "
                 f"| {g['rate']:.3f} ({g['answerable']}/{g['population']}) "
                 f"| base {pop_b} / guided {pop_g} |")
    L += ["",
          "## Part B — gold-grounded functional subsumption (strict matches)",
          "\"Is <child> a kind of <parent>?\" scored against held-out expert is-a "
          "pairs, conditional on both concepts being present in our ontology.", "",
          "| Reference | mode | recall | precision | F1 | expert pairs | matched concepts |",
          "|---|---|---|---|---|---|---|"]
    for gname in GOLDS:
        for mode in MODES:
            d = result["part_b"][gname][mode]["strict"]
            rec, prec = d["subsumption_recall"], d["subsumption_precision"]
            L.append(f"| {gname.upper()} | {mode} | "
                     f"{rec['point']:.3f} | {prec['point']:.3f} | {d['subsumption_f1']:.3f} "
                     f"| {rec['n_expert_pairs']} | {d['matched_concepts']} |")
    L += ["", "## Reading this",
          "- **Part A** iterates real class URIs, so it is immune to the "
          "naming/placement brittleness of the 12 hardcoded CQs; each row is a "
          "coverage statistic over the whole ontology, not a single concept.",
          "- **define / synonyms** rates reflect the `skos:definition` / "
          "`skos:altLabel` channels; a value near 0 is the S04 definition-drop "
          "defect (fixed in code, pending a re-run), consistent with v06.",
          "- **Part B** is conditional on concept co-presence, so it measures "
          "taxonomic correctness independently of concept coverage (v03/v09). "
          "Small `expert pairs` counts mean the estimate is under-powered — read "
          "the bootstrap CIs in the JSON.",
          "- Not circular: the answer key is a held-out expert ontology, never the "
          "guiding ontology."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Better CQ evaluation (v10).")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--no-semantic", action="store_true")
    ap.add_argument("--ito-full", action="store_true")
    args = ap.parse_args()
    use_semantic = not args.no_semantic

    print("Loading generated ontologies (baseline + guided)...")
    gens, owls = {}, {}
    for mode in MODES:
        owl = C.latest_owl(mode)
        owls[mode] = str(owl)
        gens[mode] = load_generated_full(owl)
        print(f"  [{mode}] {owl.name}: {len(gens[mode]['classes'])} classes, "
              f"{len(_content_concepts(gens[mode]))} content concepts")

    print("Part A: functional coverage rates ...")
    part_a_res = {mode: part_a(gens[mode]) for mode in MODES}

    print("Loading held-out golds + Part B: gold-grounded subsumption ...")
    golds = {n: C.load_gold(n, ito_full=(args.ito_full and n == "ito")) for n in GOLDS}
    for n in GOLDS:
        print(f"  {n}: {len(golds[n].concepts)} concepts")
    part_b_res = part_b(gens, golds, use_semantic=use_semantic, threshold=args.threshold)

    result = {
        "config": {"threshold": args.threshold, "use_semantic": use_semantic,
                   "ito_full": args.ito_full},
        "owls": owls,
        "part_a": part_a_res,
        "part_b": part_b_res,
        "note": "Population-level + gold-grounded CQ evaluation; deterministic, no "
                "LLM. Part A = functional coverage over all discovered classes; "
                "Part B = held-out functional subsumption precision/recall.",
    }
    C.write_json(C.RESULTS_DIR / "v10_cq_quality.json", result)
    C.write_md(C.RESULTS_DIR / "v10_cq_quality.md", render_md(result))

    print("\n=== Part A (guided) ===")
    for k, _ in ARCHETYPES:
        g = part_a_res["guided"][k]
        print(f"  {k:12s}: {g['rate']:.3f} ({g['answerable']}/{g['population']})")
    print("=== Part B (strict, functional subsumption recall) ===")
    for gname in GOLDS:
        for mode in MODES:
            d = part_b_res[gname][mode]["strict"]
            print(f"  {gname:4s} {mode:8s}: recall={d['subsumption_recall']['point']:.3f} "
                  f"prec={d['subsumption_precision']['point']:.3f} "
                  f"(n_pairs={d['subsumption_recall']['n_expert_pairs']})")
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v10_cq_quality.json'}"
          f"\n  {C.RESULTS_DIR / 'v10_cq_quality.md'}")


if __name__ == "__main__":
    main()
