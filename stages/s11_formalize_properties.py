"""
s10_formalize_properties.py — Stage 10: formalize properties only (Port+Extend, LLM).

Input : latest artifacts/s09_qa_repair/*.json  (the QA-repaired taxonomized
        property DB — every concept carries a `taxonomy_parent`, its regex/LLM
        mined `props` keyed by RAW verb, and any S07/S09 `literal_annotations`).
Output: artifacts/s10_formalize_properties/<RUN_ID>__<codehash>.json
        (`s10_formalized.json` — the SAME DB with each concept's `props` re-keyed
        from raw verbs to the 13 core object properties, sentence-like targets
        demoted to `literal_annotations`, and a `__meta__.property_mapping`
        recording the verb→core mapping for S11's sub-property layer). Never
        overwritten; promoted ONLY on completion.
LLM   : yes (guarded via common.call_llm — schema-validated, deterministic,
        cached; resumable via common.resumable_map over verb batches).

Port (from the original master_ontology_pipeline.py, preserved byte-identical
under test_result/scripts/route_db/): the LLM verb→core-property mapping (Step 1
of the original) and the sentence-demotion + property re-keying (Step 4 of the
original) are PRESERVED. The 13 core properties, the batch mapping prompt, the
batch size (20), and the >4-word demotion rule are UNCHANGED.

MANDATED SCOPE REDUCTION (R10 — this is the explicitly required logic change):
this stage now formalizes PROPERTIES ONLY. The following are REMOVED from the
original master pipeline and MUST NOT run here:
  * `build_taxonomy_with_intermediaries` — S08/S09 own the taxonomy now;
  * the `taxonomy_parent` (re)assignment — S10 leaves `taxonomy_parent`
    byte-identical to its input (R10.2, R10.3);
  * the OWL serialization block — S11 is the sole OWL exporter; S10 writes JSON
    only and emits NO `.owl` file (R10.2);
  * `extract_regex_superclasses` (and the `regex_superclass` field) — dropped
    (R10.4).

Changes from the original (allowed port categories + the mandated scope fix):
  * Secrets — REMOVED the hardcoded `GEMINI_API_KEY` fallback and the
    module-level `genai.Client(...)`. Every LLM call goes through
    `common.call_llm(...)`: key from `.env` (R5), temperature 0 + fixed seed
    (R22.1), reject-and-retry on malformed output (R19.2), wait-and-retry on 429
    (R19.3), `QuotaExhausted` on daily quota so the stage pauses cleanly (R19.4).
  * Cache relocation — the `data/property_mapping_cache.json` sidecar is gone;
    the verb mapping runs through `common.resumable_map` (checkpoint under
    `caches/s10_formalize_properties/`) + `call_llm`'s own per-stage cache, so an
    interrupted run resumes without repeating completed batches (R8.1, R19.5).
  * Mutation removal + promote-on-complete — the original overwrote
    `formalized_ontology_db.json` in place; this reads a versioned S09 input,
    mutates ONLY an in-memory copy, and writes a NEW versioned artifact ONLY
    after all verb batches complete (R1.1, R2.4, R19.6). A `QuotaExhausted`
    pause writes NO primary artifact.
  * literal_annotations contract — demoted sentence-like targets are appended as
    `{prop, value, weight, raw_verbs}` dicts onto the concept's existing
    `literal_annotations` list (the S07/S09 contract, R12.2), rather than the
    original's free-text `annotations` strings. Existing S07 annotations are
    preserved; definitions are never dropped (R20.4).
  * Sub-property layer (R23) — the verb→core mapping is recorded as
    `__meta__.property_mapping` so S11 can declare each mined verb
    `subPropertyOf` its core property. Verbs the LLM did not confidently map are
    surfaced as `__meta__.uncertain_verbs`; if the mapping quality is too low
    (too many uncertain verbs), the sub-property layer is OMITTED for the run
    (`__meta__.sub_property_layer_omitted = true`) while the 13 core properties
    still apply (R23.5).
  * Exposes `run() -> Path` returning the new artifact path (R13.3).

Reserved key: the output DB carries ONE reserved, non-concept top-level key
`"__meta__"` (double-underscore — never a real ML concept). Downstream stages
(S11) MUST skip it when iterating concepts.
"""

import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import List

from pydantic import BaseModel

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s11_formalize_properties"

# Reserved, non-concept top-level key carrying S10's run metadata (R23).
META_KEY = "__meta__"

# Port constants (UNCHANGED from the original master pipeline).
MAPPING_BATCH_SIZE = 20        # original property batch_size
SENTENCE_WORD_LIMIT = 4        # demote targets with MORE than 4 words (R10.1)

# The 13 core object properties — single source of truth in common (R6.1).
CORE_PROPERTIES = list(C.CORE_PROPERTIES)

# R23.5: if MORE than this fraction of mined verbs cannot be confidently mapped,
# the sub-property layer is omitted for the run (the 13 core still apply).
UNCERTAIN_OMIT_THRESHOLD = 0.5


# ==========================================
# 1. SCHEMA (Port — the original's structured mapping response)
# ==========================================
class PropertyMapping(BaseModel):
    raw_verb: str
    core_property: str


class BatchMappingResponse(BaseModel):
    mappings: List[PropertyMapping]


# ==========================================
# 2. PROMPT (Port — wording unchanged from the original)
# ==========================================
def _build_mapping_prompt(batch):
    import json as _json
    return f"""You are an expert Machine Learning Ontologist. 
Below is a batch of {len(batch)} raw verb phrases extracted from scientific definitions. 
Map each verb to EXACTLY ONE of these 13 core properties:
{CORE_PROPERTIES}

Definitions of the 13 properties:
- hasComponent: Structural composition (use, consist of, contain, include, build)
- processesData: Ingestion and handling (process, handle, parse, read, feed)
- transforms: Mathematical/representational changes (transform, map, encode, compress, embed)
- learnsFrom: Training and adaptation (learn, train, fit, tune, adapt, update)
- optimizes: Objective function manipulation (optimize, minimize, maximize, regularize)
- producesOutput: Generation and inference (generate, predict, estimate, classify, detect, output)
- integrates: Combining multiple sources (combine, integrate, merge, fuse, blend)
- organizes: Structuring and grouping (cluster, group, sort, order, rank, arrange)
- selects: Filtering and extraction (select, choose, filter, sample, extract, prune)
- modifies: Altering state or data (modify, change, alter, perturb, inject, add, remove)
- evaluates: Measurement and assessment (evaluate, assess, measure, quantify, compute)
- hasPurpose: High-level goals (design, aim, intend, target, specialize)
- hasCharacteristic: FALLBACK for noisy, complex, or sentence-like phrases (make transparent, account for)

Rules:
- Map EVERY raw verb to EXACTLY ONE of the 13 core properties.
- If a phrase is a complex sentence or doesn't represent a direct action, map it to 'hasCharacteristic'.
- Output a JSON array of objects. Each object must have "raw_verb" and "core_property".

Raw verbs:
{_json.dumps(batch)}
"""


# ==========================================
# 3. VERB→CORE MAPPING (LLM, guarded + resumable)
# ==========================================
def _map_verbs(all_verbs):
    """Map every raw mined verb to one of the 13 core properties (R10.1, R23).

    Splits ``all_verbs`` into batches processed exactly once and checkpointed
    under ``caches/s10_formalize_properties/`` via :func:`common.resumable_map`
    (an interrupted run resumes without repeating completed batches — R19.5).
    Each batch is guarded by :func:`common.call_llm` with the
    :class:`BatchMappingResponse` schema (temperature 0, reject-and-retry on
    malformed output, `QuotaExhausted` on daily quota).

    Returns:
        (final_map, uncertain_verbs):
          * final_map: ``{raw_verb: core_property}`` for EVERY verb. Verbs the
            LLM did not confidently return fall back to ``'hasCharacteristic'``
            exactly as the original script did.
          * uncertain_verbs: the verbs that hit that fallback (surfaced for
            review / the R23.5 omit decision).
    """
    batches = [(i // MAPPING_BATCH_SIZE, all_verbs[i:i + MAPPING_BATCH_SIZE])
               for i in range(0, len(all_verbs), MAPPING_BATCH_SIZE)]

    def _fn(item):
        idx, batch = item
        prompt = _build_mapping_prompt(batch)
        try:
            parsed = C.call_llm(prompt, cache_key=f"map_{idx}",
                                schema=BatchMappingResponse, stage=STAGE)
        except C.MalformedResponse:
            parsed = None
        mapping = {}
        if parsed and parsed.mappings:
            for m in parsed.mappings:
                core = m.core_property if m.core_property in CORE_PROPERTIES \
                    else 'hasCharacteristic'
                mapping[m.raw_verb] = core
        return {"batch": batch, "mapping": mapping}

    results = C.resumable_map(STAGE, batches, _fn, key=lambda it: f"map_{it[0]}")

    final_map = {}
    uncertain_verbs = []
    for r in results:
        parsed_map = r["mapping"]
        for verb in r["batch"]:
            if verb in parsed_map:
                final_map[verb] = parsed_map[verb]
            else:
                # Parse failure / verb not returned → same fallback the original
                # applied, and flag it as uncertain (R23.4).
                final_map[verb] = 'hasCharacteristic'
                uncertain_verbs.append(verb)
    return final_map, uncertain_verbs


# ==========================================
# 4. APPLY MAPPING: re-key props + demote sentence-like targets (Port)
#    (NO taxonomy assignment, NO regex superclass, NO OWL — R10.)
# ==========================================
def _apply_mapping(db, property_mapping):
    """Re-key each concept's ``props`` to the 13 core properties and demote
    sentence-like targets to ``literal_annotations`` (R10.1). Mutates ``db`` in
    place. ``taxonomy_parent`` and every other field are left untouched (R10.2/3).

    Returns the number of demoted (sentence-like) targets.
    """
    demoted = 0
    for concept, data in db.items():
        if concept == META_KEY:
            continue
        props = data.get('props') or {}
        if not props:
            continue

        # Re-key raw-verb → core-property, folding target frequencies together.
        # NOTE (Port): the re-keyed `v` field now holds {raw_verb: freq} so S11
        # can reify the originating verbs — this matches the original S10.
        new_props = defaultdict(lambda: defaultdict(lambda: {'f': 0, 'v': {}, 'e': ''}))
        for raw_verb, targets in props.items():
            core_prop = property_mapping.get(raw_verb, 'hasCharacteristic')
            for target, t_data in targets.items():
                entry = new_props[core_prop][target]
                entry['f'] += t_data.get('f', 0)
                entry['v'][raw_verb] = entry['v'].get(raw_verb, 0) + t_data.get('f', 0)
                if not entry['e'] and t_data.get('e'):
                    entry['e'] = t_data['e']
                # R20.1: carry S06's merged surface forms onto the re-keyed edge
                # (multiple raw verbs can fold into one core-property edge) so
                # S11 can still emit skos:altLabel on the target. Previously this
                # rebuild dropped `sf`, leaving altLabel coverage at 0.
                sf = t_data.get('sf')
                if sf:
                    entry['sf'] = sorted(set(entry.get('sf', [])) | set(sf))
        rekeyed = {p: dict(t) for p, t in new_props.items()}

        # Demote sentence-like targets (>4 words) to literal_annotations, using
        # the S07/S09 contract dict rather than the original's free-text string.
        annotations = data.get('literal_annotations') or []
        for core_prop in list(rekeyed.keys()):
            for target in list(rekeyed[core_prop].keys()):
                if len(str(target).split()) > SENTENCE_WORD_LIMIT:
                    t_data = rekeyed[core_prop][target]
                    raw_verbs = list(t_data['v'].keys())
                    annotations.append({
                        'prop': core_prop,
                        'value': target,
                        'weight': t_data['f'],
                        'raw_verbs': raw_verbs,
                    })
                    del rekeyed[core_prop][target]
                    demoted += 1
            if not rekeyed[core_prop]:
                del rekeyed[core_prop]

        data['props'] = rekeyed
        data['literal_annotations'] = annotations
    return demoted


# ==========================================
# 5. FORMALIZE PASS (raises QuotaExhausted to pause; NO taxonomy/OWL)
# ==========================================
def _formalize(db):
    """Run the properties-only formalization over ``db`` in memory (R10, R23).

    Collects every raw mined verb, maps them to the 13 core properties (LLM,
    resumable), applies the re-key + sentence-demotion, and records the
    verb→core mapping under the reserved ``__meta__`` key for S11's sub-property
    layer. Returns the manifest counts. Raises :class:`common.QuotaExhausted`
    (propagated from the guarded LLM step) so :func:`run` can pause without
    writing the primary artifact.
    """
    # 1. Gather every raw verb across the DB (skip the reserved meta key).
    all_verbs = set()
    for concept, data in db.items():
        if concept == META_KEY:
            continue
        all_verbs.update((data.get('props') or {}).keys())
    all_verbs = sorted(all_verbs)
    print(f"🧠 S10: mapping {len(all_verbs)} raw verbs → {len(CORE_PROPERTIES)} core properties...")

    # 2. LLM verb→core mapping (guarded, resumable).
    property_mapping, uncertain_verbs = _map_verbs(all_verbs)

    # 3. R23.5: decide whether the sub-property layer is trustworthy enough.
    total = len(all_verbs)
    uncertain_ratio = (len(uncertain_verbs) / total) if total else 0.0
    omit_layer = total > 0 and uncertain_ratio > UNCERTAIN_OMIT_THRESHOLD
    if omit_layer:
        print(f"   ⚠️ Sub-property layer OMITTED for this run: "
              f"{len(uncertain_verbs)}/{total} verbs uncertain "
              f"(ratio {uncertain_ratio:.2f} > {UNCERTAIN_OMIT_THRESHOLD}). "
              f"The 13 core properties still apply (R23.5).")

    # 4. Apply the mapping to the DB (re-key + demote). The 13 core properties
    #    ALWAYS apply, regardless of the omit decision.
    demoted = _apply_mapping(db, property_mapping)

    # 5. Record the sub-property layer (or omit it) under the reserved key.
    db[META_KEY] = {
        "stage": STAGE,
        # When omitted, S11 sees an empty mapping and declares NO sub-properties.
        "property_mapping": {} if omit_layer else property_mapping,
        "sub_property_layer_omitted": omit_layer,
        "uncertain_verbs": uncertain_verbs,
    }

    core_dist = Counter(
        property_mapping.get(v, 'hasCharacteristic') for v in all_verbs
    )
    counts = {
        "concepts_total": sum(1 for k in db if k != META_KEY),
        "verbs_total": total,
        "verbs_uncertain": len(uncertain_verbs),
        "uncertain_ratio": round(uncertain_ratio, 4),
        "sub_property_layer_omitted": omit_layer,
        "core_properties_used": len(core_dist),
        "targets_demoted_to_literal": demoted,
    }
    print(f"   ✅ Mapped verbs across {len(core_dist)} core properties; "
          f"demoted {demoted} sentence-like target(s) to literal_annotations.")
    return counts


# ==========================================
# 6. MAIN (promote-on-complete; pause cleanly on quota exhaustion)
# ==========================================
def run() -> Path:
    print("🚀 S10: formalizing properties (properties-only; taxonomy & OWL untouched)...")

    # Prefer the re-homed taxonomy (S09a); fall back to S09 if S09a hasn't run.
    in_path = C.latest_output("s10_taxonomy_rehome", ext="json") or C.latest_output("s09a_taxonomy_rehome", ext="json") \
        or C.require_latest("s09_qa_repair", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)   # in-memory copy; the input file is never mutated.

    try:
        counts = _formalize(db)
    except C.QuotaExhausted as e:
        # Paused, not failed: no primary artifact, caches left intact (R19.4/6).
        print(f"[{STAGE}] paused — resume later (daily LLM quota exhausted). "
              f"Progress is checkpointed in {C.CACHES / STAGE}; re-run this stage "
              f"to continue where it left off. ({e})")
        sys.exit(0)

    # Promote-on-complete: only NOW write the ONE versioned primary artifact.
    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, db)
    C.write_manifest(STAGE, __file__, in_path=in_path, out_path=out_path,
                     counts=counts,
                     extra={"sub_property_layer_omitted": counts["sub_property_layer_omitted"],
                            "verbs_uncertain": counts["verbs_uncertain"]})
    print(f"[{STAGE}] formalization complete -> {out_path} "
          f"(verbs={counts['verbs_total']}, "
          f"demoted={counts['targets_demoted_to_literal']}, "
          f"sub_property_layer_omitted={counts['sub_property_layer_omitted']})")
    return out_path


if __name__ == "__main__":
    run()
