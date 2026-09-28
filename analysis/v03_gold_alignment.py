"""
v03_gold_alignment.py — held-out gold-standard alignment (the non-circular test).

Validates the pipeline by comparing the GENERATED ontology (baseline vs guided
S11 OWL exports) against THREE human-curated, held-out reference ontologies that
the pipeline never consumed as guidance:

  * ACM CCS 2012  (skos:broader)  — purest institutional human curation
  * ITO           (subClassOf / task tree) — manual expert curation of AI tasks
  * AIO           (rdfs:subClassOf) — richest ML-model/architecture coverage
                    (LLM-assisted construction -> reported as supplementary)

For each (mode x gold) it reports:
  * coverage_of_generated : fraction of our (non-skeleton) concepts a gold recognises,
  * recall_of_gold        : fraction of gold concepts our ontology covers,
  * taxonomic precision/recall/F1 : agreement of is-a ANCESTOR pairs in gold-id
    space (a generated ancestor pair (a,d) is correct iff a is an ancestor of d
    in the gold hierarchy). For CCS this is hierarchical (skos:broader) agreement.

Two match regimes are always reported side by side:
  * strict        : exact-slug + normalized-lexical matches only (conservative),
  * with_semantic : adds embedding matches >= threshold (higher recall, noisier).

Coverage/recall carry bootstrap 95% CIs. A random sample of matches (esp.
semantic) is written to results/v03_match_samples.json for manual precision review.

Usage (from pipeline_v2/):
    python analysis/v03_gold_alignment.py
    python analysis/v03_gold_alignment.py --threshold 0.80 --no-semantic
    python analysis/v03_gold_alignment.py --ito-full        # parse the 124MB ITO OWL
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import common as C

MODES = ["baseline", "guided"]
# Purest human curation first; AIO last (LLM-assisted -> supplementary).
GOLDS = ["ccs", "ito", "aio"]

GOLD_BLURB = {
    "ccs": "ACM CCS 2012 (institutional human curation; skos:broader)",
    "ito": "ITO (manual expert curation; AI task hierarchy)",
    "aio": "AIO (expert + LLM-assisted; ML model/architecture is-a) — supplementary",
}


# ── load the generated ontology from an S11 OWL export ──────────────────────
def load_generated(owl_path: Path):
    from rdflib import Graph, RDF, RDFS, OWL, URIRef
    g = Graph()
    g.parse(str(owl_path), format="xml")
    ns = C.ONTOLOGY_NS
    classes = {str(s) for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns)}
    label_of = {}
    for s, o in g.subject_objects(RDFS.label):
        if str(s) in classes:
            label_of[str(s)] = str(o)
    parents = defaultdict(set)
    for c, p in g.subject_objects(RDFS.subClassOf):
        cs, ps = str(c), str(p)
        if cs in classes and isinstance(p, URIRef) and ps.startswith(ns):
            parents[cs].add(ps)
    return classes, label_of, dict(parents)


def concept_nodes(classes: set) -> list:
    """Non-skeleton generated classes (the discovered content)."""
    return [c for c in classes if C.local_name(c) not in C.SKELETON_SLUGS]


def _label(c: str, label_of: dict) -> str:
    return label_of.get(c) or C.local_name(c).replace("_", " ")


# ── reusable alignment primitives (also imported by v09) ────────────────────
def matches_for(gen, gold, *, use_semantic=True, threshold=0.85, model=None):
    """Return (concepts, parents, matches) for one (generated ontology, gold)."""
    classes, label_of, parents = gen
    concepts = concept_nodes(classes)
    labels = [_label(c, label_of) for c in concepts]
    matcher = C.GoldMatcher(gold, use_semantic=use_semantic,
                            threshold=threshold, model=model)
    return concepts, parents, matcher.match_many(labels)


def gen2gold_map(concepts, matches, regime):
    """concept -> Match, keeping either all matches ('with_semantic') or only
    exact+lexical ('strict')."""
    if regime == "strict":
        return {c: m for c, m in zip(concepts, matches)
                if m.kind in ("exact", "lexical")}
    return {c: m for c, m in zip(concepts, matches) if m.matched}


def ancestor_sets(concepts, parents, gold, gen2gold):
    """(covered_gold, PA, GA): matched gold concepts; PA = generated is-a closure
    mapped to gold-id space; GA = gold ancestor pairs among matched concepts.
    Shared by v03 metrics and v09 significance so both use identical definitions.
    """
    covered_gold = {m.gold_id for m in gen2gold.values()}
    GA = set()
    for d in covered_gold:
        for a in gold.ancestors(d):
            if a in covered_gold and a != d:
                GA.add((a, d))
    PA = set()
    for c in concepts:
        m_c = gen2gold.get(c)
        if not m_c:
            continue
        for a in C.transitive_ancestors(parents, c):
            m_a = gen2gold.get(a)
            if m_a and m_a.gold_id != m_c.gold_id:
                PA.add((m_a.gold_id, m_c.gold_id))
    return covered_gold, PA, GA


# ── metric computation given a concept->gold mapping ────────────────────────
def _metrics(concepts, parents, gold, gen2gold):
    covered = [1 if c in gen2gold else 0 for c in concepts]
    coverage = (sum(covered) / len(concepts)) if concepts else 0.0
    covered_gold, PA, GA = ancestor_sets(concepts, parents, gold, gen2gold)
    recall_gold = (len(covered_gold) / len(gold.concepts)) if gold.concepts else 0.0

    overlap = len(PA & GA)
    prec = overlap / len(PA) if PA else 0.0
    rec = overlap / len(GA) if GA else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

    return {
        "concepts_evaluated": len(concepts),
        "gold_concepts": len(gold.concepts),
        "matched_concepts": sum(covered),
        "coverage_of_generated": round(coverage, 4),
        "coverage_ci": C.bootstrap_ci(covered),
        "recall_of_gold": round(recall_gold, 4),
        "taxonomic": {
            "predicted_ancestor_pairs": len(PA),
            "gold_ancestor_pairs": len(GA),
            "overlap": overlap,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        },
    }


def evaluate(mode, gold, gen, matcher, rng, samples_out):
    classes, label_of, parents = gen
    concepts = concept_nodes(classes)
    labels = [_label(c, label_of) for c in concepts]
    matches = matcher.match_many(labels)

    full = gen2gold_map(concepts, matches, "with_semantic")
    strict = gen2gold_map(concepts, matches, "strict")

    kinds = Counter(m.kind for m in matches)
    sem_scores = [m.score for m in matches if m.kind == "semantic"]

    # sample for manual precision review (favour semantic matches)
    sem_items = [(labels[i], matches[i]) for i in range(len(matches))
                 if matches[i].kind == "semantic"]
    rng.shuffle(sem_items)
    for lab, m in sem_items[:25]:
        samples_out.append({"mode": mode, "gold": gold.name, "kind": m.kind,
                            "generated_label": lab, "gold_label": m.gold_label,
                            "score": m.score, "correct": None})

    return {
        "match_kind_counts": dict(kinds),
        "semantic_score_mean": round(sum(sem_scores) / len(sem_scores), 3)
        if sem_scores else None,
        "with_semantic": _metrics(concepts, parents, gold, full),
        "strict": _metrics(concepts, parents, gold, strict),
    }


# ── report assembly ─────────────────────────────────────────────────────────
def _winner(base, guided, key_path):
    def dig(d):
        for k in key_path:
            d = d[k]
        return d
    b, g = dig(base), dig(guided)
    return {"baseline": b, "guided": g, "delta": round(g - b, 4),
            "winner": "guided" if g > b else "baseline" if b > g else "tie"}


def build_comparison(runs):
    comp = {}
    for gold in GOLDS:
        b, g = runs["baseline"][gold], runs["guided"][gold]
        comp[gold] = {
            "strict": {
                "coverage_of_generated": _winner(b, g, ["strict", "coverage_of_generated"]),
                "recall_of_gold": _winner(b, g, ["strict", "recall_of_gold"]),
                "taxonomic_f1": _winner(b, g, ["strict", "taxonomic", "f1"]),
            },
            "with_semantic": {
                "coverage_of_generated": _winner(b, g, ["with_semantic", "coverage_of_generated"]),
                "recall_of_gold": _winner(b, g, ["with_semantic", "recall_of_gold"]),
                "taxonomic_f1": _winner(b, g, ["with_semantic", "taxonomic", "f1"]),
            },
        }
    return comp


def render_md(result) -> str:
    L = ["# v03. Held-out Gold-Standard Alignment", "",
         "Compares the generated baseline and guided ontologies against three "
         "**held-out, human-curated** reference ontologies the pipeline never "
         "used as guidance. This breaks the circularity of evaluating against "
         "the guiding ontology.", "",
         f"- threshold (semantic): {result['config']['threshold']}",
         f"- semantic matching: {'on' if result['config']['use_semantic'] else 'off'}",
         f"- baseline OWL: `{Path(result['runs']['baseline']['_owl']).name}`",
         f"- guided OWL: `{Path(result['runs']['guided']['_owl']).name}`", ""]
    for gold in GOLDS:
        L.append(f"## {gold.upper()} — {GOLD_BLURB[gold]}")
        for regime in ("strict", "with_semantic"):
            L.append(f"\n### {regime}")
            L.append("| metric | baseline | guided | delta | winner |")
            L.append("|---|---|---|---|---|")
            c = result["comparison"][gold][regime]
            for label, key in (("coverage of generated", "coverage_of_generated"),
                               ("recall of gold", "recall_of_gold"),
                               ("taxonomic F1", "taxonomic_f1")):
                w = c[key]
                L.append(f"| {label} | {w['baseline']:.4f} | {w['guided']:.4f} "
                         f"| {w['delta']:+.4f} | {w['winner']} |")
        L.append("")
    L.append("## Notes")
    L.append("- **strict** = exact + normalized-lexical matches only "
             "(conservative). **with_semantic** adds embedding matches; treat as "
             "an upper bound and check `v03_match_samples.json` for matcher precision.")
    L.append("- Taxonomic F1 is agreement of is-a ANCESTOR pairs in gold-id space "
             "(hierarchical/`skos:broader` agreement for CCS).")
    L.append("- Coverage carries a bootstrap 95% CI (see JSON). Taxonomic-F1 "
             "significance testing is deferred to the v09 stats script.")
    L.append("- Held-out breaks pipeline circularity but not LLM pretraining "
             "contamination; structural (is-a) agreement is reported for that reason.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Held-out gold-standard alignment (v03).")
    ap.add_argument("--threshold", type=float, default=0.85,
                    help="Embedding cosine threshold for semantic matches.")
    ap.add_argument("--no-semantic", action="store_true",
                    help="Disable embedding matching (strict only, no model load).")
    ap.add_argument("--ito-full", action="store_true",
                    help="Use the full 124MB ITO.owl instead of the task tree.")
    args = ap.parse_args()
    use_semantic = not args.no_semantic

    print("Loading held-out gold ontologies...")
    golds = {}
    for name in GOLDS:
        golds[name] = C.load_gold(name, ito_full=(args.ito_full and name == "ito"))
        print(f"  {name}: {len(golds[name].concepts)} concepts, "
              f"{sum(len(v) for v in golds[name].parents.values())} hierarchy edges")

    rng = random.Random(42)
    samples = []
    runs = {}
    for mode in MODES:
        owl = C.latest_owl(mode)
        print(f"\n[{mode}] loading {owl.name} ...")
        gen = load_generated(owl)
        n_concepts = len(concept_nodes(gen[0]))
        print(f"  {len(gen[0])} classes ({n_concepts} non-skeleton concepts)")
        runs[mode] = {"_owl": str(owl)}
        for name in GOLDS:
            matcher = C.GoldMatcher(golds[name], use_semantic=use_semantic,
                                    threshold=args.threshold)
            res = evaluate(mode, golds[name], gen, matcher, rng, samples)
            runs[mode][name] = res
            s = res["strict"]["taxonomic"]
            print(f"    vs {name:4s}: cover={res['strict']['coverage_of_generated']:.3f} "
                  f"recall={res['strict']['recall_of_gold']:.3f} "
                  f"taxF1(strict)={s['f1']:.3f} "
                  f"[matched {res['strict']['matched_concepts']}]")

    result = {
        "config": {"threshold": args.threshold, "use_semantic": use_semantic,
                   "ito_full": args.ito_full},
        "golds": {k: {"blurb": GOLD_BLURB[k], "concepts": len(golds[k].concepts)}
                  for k in GOLDS},
        "runs": runs,
        "comparison": build_comparison(runs),
    }

    C.write_json(C.RESULTS_DIR / "v03_gold_alignment.json", result)
    C.write_json(C.RESULTS_DIR / "v03_match_samples.json", samples)
    C.write_md(C.RESULTS_DIR / "v03_gold_alignment.md", render_md(result))

    print("\n=== summary (taxonomic F1, strict) ===")
    for gold in GOLDS:
        w = result["comparison"][gold]["strict"]["taxonomic_f1"]
        print(f"  {gold:4s}: baseline={w['baseline']:.3f}  guided={w['guided']:.3f}  "
              f"delta={w['delta']:+.3f}  -> {w['winner']}")
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v03_gold_alignment.json'}"
          f"\n  {C.RESULTS_DIR / 'v03_gold_alignment.md'}"
          f"\n  {C.RESULTS_DIR / 'v03_match_samples.json'} "
          f"({len(samples)} samples for manual precision review)")


if __name__ == "__main__":
    main()
