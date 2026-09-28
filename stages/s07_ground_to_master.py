"""
s07_ground_to_master.py — Stage 7: ground targets against the master list (Port).

Input : latest artifacts/s06_clean_vocab/*.json   (the cleaned property DB).
Master: the verified concept whitelist. Per the S07 decision (design R12,
        R2.2): use the LATEST S02 output when present (so the whitelist matches
        the concepts actually produced by THIS run, including normalization),
        falling back to the frozen `seed/gemma_payload.json` when S02 has not
        been run. Both are lists of `{target_concept, ...}` records, so the
        whitelist is built identically from either source.
Output: artifacts/s07_ground_to_master/<RUN_ID>__<codehash>.json  (never overwritten)
LLM   : no

This is the pipeline's anti-hallucination gate: a mined property edge survives
as a formal edge ONLY if its target matches a verified master-list concept;
every unmatched edge is demoted to a `literal_annotations` entry of the form
`{prop, value, weight, raw_verbs}` (R12.1). This keeps the ontology's object
properties pointing only at real, verified concepts while retaining the demoted
facts as annotations for S08–S11.

Port (from scripts/route_db/ground_to_master.py, preserved byte-identical under
the legacy tree): the grounding logic is UNCHANGED —
  * `normalize_concept` fuzzy-matches on lowercase + strip + naive singular,
  * a target whose normalized form is in the master whitelist is KEPT as a
    formal edge under its canonical master name (frequencies + raw-verb counts
    of multiple raw targets that map to the same canonical are merged),
  * a target not in the whitelist is DEMOTED to a `literal_annotations` entry.

Changes from the original (allowed port categories only):
  * I/O — read the LATEST S06 artifact via `common.require_latest` instead of a
    hardcoded `cleaned_ontology_db.json`; build the master whitelist from the
    LATEST S02 output when present, else the frozen `seed/gemma_payload.json`
    (via `common.SEED`) instead of a hardcoded `data/gemma_payload.json`
    (R2.2, R8.1). Write a NEW versioned artifact via `common.output_path(...)`
    instead of overwriting `grounded_ontology_db.json` (R1.1, R2.3, R13.3).
  * Mutation removal — the original mutated the loaded `db` dict in place; this
    port builds a fresh grounded DB and never mutates its input.
  * R20.4 guard — every per-concept key OTHER than `props` (notably
    `consolidated_definitions`, and the `f/td/cov/unt` bookkeeping) is carried
    through UNCHANGED; grounding rewrites only `props` and adds
    `literal_annotations`. Definitions are never dropped.
  * Surface-form carry (R20.1) — when S06 recorded merged surface forms on a
    target (`sf`), those are carried onto the canonical formal edge (merged
    across raw targets) so S11 can still emit `skos:altLabel`. The original
    `{f, v, e}` edge shape is otherwise preserved.
  * Manifest — one line per run reporting kept-edge vs demoted-edge counts and
    the master-list source (R4.2).
  * Exposes `run() -> Path` returning the new artifact path (R13.3).

Output contract per concept (S06 shape, `props` regrounded + literal_annotations):
  {f, td, cov, props:{verb:{canonical_target:{f, v, e[, sf]}}},
   unt:[], literal_annotations:[{prop, value, weight, raw_verbs}], ...}
"""

import sys
from pathlib import Path

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s07_ground_to_master"


def normalize_concept(name: str) -> str:
    """Normalize a concept name for fuzzy master-list matching (Port — unchanged).

    Lowercase + strip, then a naive plural fold (drop a trailing 's' that is not
    part of 'ss') so simple plural/casing variants match the master list.
    """
    name = str(name).lower().strip()
    # Simple plural handling
    if name.endswith('s') and not name.endswith('ss') and len(name) > 2:
        name = name[:-1]
    return name


def _load_master_concepts() -> tuple[dict, Path, int]:
    """Build the normalized master whitelist and report its source.

    Per the S07 decision (design R12): prefer the LATEST S02 output; fall back to
    the frozen `seed/gemma_payload.json` when S02 has not been run. Both are
    lists of `{target_concept, ...}`.

    Returns:
        (master_concepts, source_path) where master_concepts maps a normalized
        name -> the canonical (original) master name.
    """
    source = C.latest_output("s02_consolidate", ext="json")
    if source is None:
        source = C.SEED / "gemma_payload.json"
        if not source.is_file():
            raise FileNotFoundError(
                f"No S02 output and no frozen master list at {source}. "
                f"Run S02 or provide seed/gemma_payload.json."
            )
    master_payload = C.load_json(source)

    master_concepts: dict[str, str] = {}
    for item in master_payload:
        name = item.get('target_concept', '')
        if name:
            master_concepts[normalize_concept(name)] = name

    # Knowledge-guided extension (mode == "guided", R-KG): UNION the corpus master
    # list with the guiding reference ontology's concepts. An edge whose target is
    # a reference concept then survives grounding as a formal edge even if the
    # corpus alone never attested it — external authority expands what counts as
    # "verified". This is a strict superset of the baseline whitelist (nothing is
    # removed), so in baseline mode the whitelist is unchanged.
    added = 0
    if getattr(C, "SCOP_MODE", "baseline") == "guided":
        import knowledge as K
        K.load()
        for slug, label in K.concepts.items():
            key = normalize_concept(label)
            if key not in master_concepts:
                master_concepts[key] = label
                added += 1
        print(f"🧭 Guided mode: unioned {added} reference concept(s) into the "
              f"master whitelist.")
    return master_concepts, source, added


def run() -> Path:
    print("🚀 S07: grounding property targets against the master whitelist...")

    # ── 1. LOAD the master whitelist (latest S02, else frozen seed) ───────
    master_concepts, master_src, kg_added = _load_master_concepts()
    print(f"✅ Loaded {len(master_concepts):,} verified master concepts "
          f"from {master_src}.")

    # ── 2. LOAD latest S06 cleaned property DB ────────────────────────────
    in_path = C.require_latest("s06_clean_vocab", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)

    grounded_edges = 0
    demoted_literals = 0
    grounded_db: dict = {}

    # ── 3. GROUND: keep verified targets, demote the rest (Port logic) ────
    print("🔗 Filtering targets against the master whitelist...")
    for concept, data in db.items():
        formal_props: dict = {}
        literal_annotations: list = []

        for core_prop, targets in data.get('props', {}).items():
            for target, t_data in targets.items():
                norm_target = normalize_concept(target)

                # THE CORE LOGIC: is this target a verified master concept?
                if norm_target in master_concepts:
                    # ✅ verified — keep as a formal edge under the canonical name.
                    canonical_target = master_concepts[norm_target]

                    if core_prop not in formal_props:
                        formal_props[core_prop] = {}

                    # Merge if multiple raw targets map to the same canonical.
                    if canonical_target not in formal_props[core_prop]:
                        formal_props[core_prop][canonical_target] = {
                            'f': 0, 'v': {}, 'e': t_data.get('e', ''),
                        }
                    edge = formal_props[core_prop][canonical_target]
                    edge['f'] += t_data.get('f', 0)
                    for raw_v, count in t_data.get('v', {}).items():
                        edge['v'][raw_v] = edge['v'].get(raw_v, 0) + count
                    # Carry S06's merged surface forms (alt-label source, R20.1).
                    sf = t_data.get('sf')
                    if sf:
                        merged = set(edge.get('sf', [])) | set(sf)
                        edge['sf'] = sorted(merged)
                    grounded_edges += 1

                else:
                    # ❌ unverified — demote to a literal annotation.
                    raw_verbs = list(t_data.get('v', {}).keys())
                    literal_annotations.append({
                        'prop': core_prop,
                        'value': target,
                        'weight': t_data.get('f', 0),
                        'raw_verbs': raw_verbs,
                    })
                    demoted_literals += 1

        # Build a fresh grounded concept: carry EVERY other key through
        # unchanged (R20.4 — consolidated_definitions and all bookkeeping are
        # never dropped); rewrite only `props`, add `literal_annotations`.
        new_data = {k: v for k, v in data.items() if k != 'props'}
        new_data['props'] = formal_props
        new_data['literal_annotations'] = literal_annotations
        grounded_db[concept] = new_data

    print(f"\n📊 GROUNDING STATS:")
    print(f"   🏛️ Kept edges (target is a verified master concept): {grounded_edges}")
    print(f"   📝 Demoted to literals (target is just a noun phrase): {demoted_literals}")

    # ── 4. SAVE new versioned artifact + manifest ─────────────────────────
    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, grounded_db)

    C.write_manifest(
        STAGE, __file__, in_path=in_path, out_path=out_path,
        counts={
            "concepts": len(grounded_db),
            "master_concepts": len(master_concepts),
            "kept_edges": grounded_edges,
            "demoted_edges": demoted_literals,
            "kg_reference_concepts_added": kg_added,
        },
        extra={"master_source": str(master_src),
               "mode": getattr(C, "SCOP_MODE", "baseline")},
    )
    print(f"[{STAGE}] grounded {len(grounded_db)} concepts "
          f"({grounded_edges} kept, {demoted_literals} demoted) -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
