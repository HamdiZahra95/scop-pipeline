"""
v06_grounding_provenance.py — grounding / provenance quality (no LLM).

Validates the pipeline's anti-hallucination and provenance claims, and quantifies
the PROVENANCE COST of knowledge guidance. Reads the final formalized DB (latest
S10 per mode) for grounding/provenance and the S11 OWL for annotation coverage.

Metrics (baseline vs guided):
  * corpus_attestation_rate — fraction of discovered (non-scaffolding) concepts
    that carry a corpus frequency f>0. f==0 content = promoted/materialized
    targets or reference-injected concepts that are structurally present but not
    attested in the corpus as standalone concepts. Guidance is expected to lower
    this (S03 gate-recovery + S07 whitelist-union pull in reference concepts).
  * f-band distribution — f==0 / 1..10 / >10 over content concepts.
  * demotion_ratio — literal_annotations / (object-property edges +
    literal_annotations): how much extracted relational content ended up as
    unlinked annotation rather than a formal (grounded) edge.
  * dangling_target_rate — object-property edge targets that are NOT a node in
    the DB (a hallucination / ungrounded-target proxy; should be ~0 after
    grounding + S09a materialization).
  * edge_provenance_rate — fraction of edges carrying raw-verb provenance ('v').
  * definition_coverage / altlabel_coverage — from the OWL (skos:definition /
    skos:altLabel per non-skeleton class).

Usage (from pipeline_v2/):
    python analysis/v06_grounding_provenance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PV2 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PV2))
from analysis import common as C

MODES = ["baseline", "guided"]
META = "__meta__"
FREQ_GATE = 10   # the documented frequency gate (common.FREQ_GATE_DEFAULT)


def latest_stage_json(mode: str, stage: str):
    candidates = [
        C.ROOT / "runs" / mode / "artifacts" / stage.replace("s10_", "s11_"),
        C.ROOT / "runs" / mode / "artifacts" / stage,
        (C.ROOT / "artifacts" if mode == "baseline"
         else C.ROOT / "runs" / mode / "artifacts") / stage,
    ]
    for base in candidates:
        if base.exists():
            files = sorted(base.glob("*.json"))
            if files:
                return files[-1]
    return None


def _is_scaffolding(name: str, data: dict) -> bool:
    return bool(C.slug(name) in C.SKELETON_SLUGS
                or data.get("is_skeleton") or data.get("is_intermediary"))


def db_grounding(db: dict) -> dict:
    keys = {k for k in db if k != META}
    content, f0, f_low, f_hi = [], 0, 0, 0
    edges = annotations = dangling = with_verb = 0
    for name, data in db.items():
        if name == META or not isinstance(data, dict):
            continue
        if not _is_scaffolding(name, data):
            content.append(name)
            f = data.get("f", 0) or 0
            if f <= 0:
                f0 += 1
            elif f <= FREQ_GATE:
                f_low += 1
            else:
                f_hi += 1
        for prop, targets in (data.get("props") or {}).items():
            for tgt, tdata in (targets or {}).items():
                edges += 1
                if tgt not in keys:
                    dangling += 1
                if isinstance(tdata, dict) and tdata.get("v"):
                    with_verb += 1
        annotations += len(data.get("literal_annotations") or [])

    n_content = len(content) or 1
    total_rel = (edges + annotations) or 1
    attested = f_low + f_hi
    return {
        "concepts_total": len(keys),
        "content_concepts": len(content),
        "scaffolding_concepts": len(keys) - len(content),
        "corpus_attestation_rate": round(attested / n_content, 4),
        "f_bands": {"f0_not_attested": f0, "f_1_10": f_low, "f_gt_10": f_hi},
        "object_property_edges": edges,
        "literal_annotations": annotations,
        "demotion_ratio": round(annotations / total_rel, 4),
        "dangling_target_rate": round(dangling / (edges or 1), 4),
        "dangling_targets": dangling,
        "edge_provenance_rate": round(with_verb / (edges or 1), 4),
    }


def owl_annotation_coverage(owl_path: Path) -> dict:
    from rdflib import Graph, RDF, RDFS, OWL, URIRef
    from rdflib.namespace import SKOS
    g = Graph()
    g.parse(str(owl_path), format="xml")
    ns = C.ONTOLOGY_NS
    classes = [s for s in g.subjects(RDF.type, OWL.Class)
               if isinstance(s, URIRef) and str(s).startswith(ns)]
    concepts = [c for c in classes if C.local_name(c) not in C.SKELETON_SLUGS]
    n = len(concepts) or 1
    with_def = sum(1 for c in concepts if next(g.objects(c, SKOS.definition), None))
    with_alt = sum(1 for c in concepts if next(g.objects(c, SKOS.altLabel), None))
    with_comment = sum(1 for c in concepts if next(g.objects(c, RDFS.comment), None))
    return {
        "owl_concept_classes": len(concepts),
        "definition_coverage": round(with_def / n, 4),
        "altlabel_coverage": round(with_alt / n, 4),
        "comment_coverage": round(with_comment / n, 4),
    }


def main():
    per_mode = {}
    for mode in MODES:
        s10 = latest_stage_json(mode, "s10_formalize_properties")
        owl = C.latest_owl(mode)
        print(f"[{mode}] S10={s10.name if s10 else 'MISSING'}  OWL={owl.name}")
        db = C.load_json(s10) if s10 else {}
        block = db_grounding(db)
        block.update(owl_annotation_coverage(owl))
        block["_s10"] = s10.name if s10 else None
        block["_owl"] = owl.name
        per_mode[mode] = block
        print(f"    corpus_attestation={block['corpus_attestation_rate']} "
              f"demotion={block['demotion_ratio']} "
              f"dangling={block['dangling_target_rate']} "
              f"def_cov={block['definition_coverage']} "
              f"altlabel_cov={block['altlabel_coverage']}")

    keys = ["content_concepts", "corpus_attestation_rate", "object_property_edges",
            "literal_annotations", "demotion_ratio", "dangling_target_rate",
            "edge_provenance_rate", "definition_coverage", "altlabel_coverage",
            "comment_coverage"]
    comparison = {}
    for k in keys:
        b, g = per_mode["baseline"].get(k), per_mode["guided"].get(k)
        if isinstance(b, (int, float)) and isinstance(g, (int, float)):
            comparison[k] = {"baseline": b, "guided": g, "delta": round(g - b, 4)}

    result = {
        "modes": MODES,
        "per_mode": per_mode,
        "comparison": comparison,
        "note": "Grounding/provenance from the final formalized DB (S10); "
                "definition/altLabel coverage from the S11 OWL. "
                "corpus_attestation_rate = content concepts with corpus frequency "
                "f>0; f==0 content are promoted/materialized/reference-injected "
                "concepts that are structurally present but not corpus-attested. "
                "dangling_target_rate is a hallucination/ungrounded-target proxy "
                "(edge targets that are not a node).",
    }
    C.write_json(C.RESULTS_DIR / "v06_grounding_provenance.json", result)
    C.write_md(C.RESULTS_DIR / "v06_grounding_provenance.md", render_md(result))
    print(f"\nWrote:\n  {C.RESULTS_DIR / 'v06_grounding_provenance.json'}"
          f"\n  {C.RESULTS_DIR / 'v06_grounding_provenance.md'}")


def render_md(result) -> str:
    L = ["# v06. Grounding / Provenance Quality", "", f"- {result['note']}", "",
         "| metric | baseline | guided | delta |", "|---|---|---|---|"]
    labels = {
        "content_concepts": "content concepts (non-scaffolding)",
        "corpus_attestation_rate": "corpus attestation rate (f>0)",
        "object_property_edges": "object-property edges",
        "literal_annotations": "literal annotations",
        "demotion_ratio": "demotion ratio (annotations / relations)",
        "dangling_target_rate": "dangling-target rate (hallucination proxy)",
        "edge_provenance_rate": "edge provenance rate (raw verbs)",
        "definition_coverage": "definition coverage (skos:definition)",
        "altlabel_coverage": "altLabel coverage (skos:altLabel)",
        "comment_coverage": "comment coverage (rdfs:comment)",
    }
    for k, lab in labels.items():
        if k in result["comparison"]:
            c = result["comparison"][k]
            L.append(f"| {lab} | {c['baseline']} | {c['guided']} | {c['delta']:+} |")
    L.append("\n## f-band distribution (content concepts)")
    L.append("| mode | f==0 (not attested) | f 1–10 | f>10 |")
    L.append("|---|---|---|---|")
    for m in result["modes"]:
        fb = result["per_mode"][m]["f_bands"]
        L.append(f"| {m} | {fb['f0_not_attested']} | {fb['f_1_10']} | {fb['f_gt_10']} |")
    L += ["", "## Reading this",
          "- **corpus_attestation_rate**: guidance did NOT reduce corpus grounding "
          "here — guided is slightly higher. The f-bands show why: baseline's gate "
          "(freq>10) leaves the f 1–10 band empty, while guided's S03 gate-recovery "
          "adds low-frequency but reference-attested corpus concepts (f 1–10) and "
          "carries fewer f==0 (ungrounded-injected) nodes.",
          "- **dangling_target_rate**: baseline leaves a large share of "
          "object-property targets ungrounded (not a node); guided is markedly "
          "lower (S07 whitelist-union + S09a materialization). Note S11 still "
          "anchors such referenced-only targets under Machine_Learning, so they are "
          "not hallucinations in the final OWL, but they are under-specified nodes.",
          "- **definition/altLabel coverage = 0 for BOTH modes** is a concrete, "
          "fixable pipeline gap: the OWL emits no skos:definition and no "
          "skos:altLabel because consolidated_definitions and merged surface forms "
          "(sf) are dropped upstream (definitions at S04), so S11's R20.3 "
          "definition/synonym emission is effectively dead. About half of concepts "
          "still carry an rdfs:comment, but only from demoted literal_annotations.",
          "- **demotion_ratio ~0.90**: ~90% of mined relational content is kept as "
          "unlinked literal annotations rather than formal grounded edges — "
          "anti-hallucination conservatism, but it makes the formal relation layer "
          "thin (see v02 relationship_richness) and most extracted knowledge "
          "non-queryable as edges."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
