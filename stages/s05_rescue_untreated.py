"""
s05_rescue_untreated.py — Stage 5: LLM-rescue untreated definitions (Port+Extend).

Input : latest artifacts/s04_extract_properties/*.json  (the S04 property DB with
        each concept's regex-mined `props` plus the `unt` list of definitions the
        regex engine failed to parse).
Output: artifacts/s05_rescue_untreated/<RUN_ID>__<codehash>.json  (the property DB
        with additional `props` recovered from the untreated definitions and a
        recomputed coverage). Never overwritten; promoted ONLY on completion.
LLM   : yes (guarded via common.call_llm — schema-validated, deterministic).

Port (from the original rescue_untreated script, preserved byte-identical under
the legacy tree): for each concept that still has untreated definitions, batch
them, ask the LLM for the core (verb, target) of each, lemmatize the verbs,
semantically cluster the recovered targets, append them to the concept's `props`,
drop the rescued definitions from `unt`, and recompute coverage. The analytical
logic (batch size 10, the extraction/dedup prompt, the verb-lemma map, the
agglomerative object clustering at cosine distance 0.35, the coverage formula) is
UNCHANGED.

Changes from the original (allowed port categories only):
  * Secrets — REMOVED the hardcoded `GEMINI_API_KEY` fallback and the module-level
    `genai.Client(...)`. Every LLM call now goes through `common.call_llm(...)`,
    which reads `GOOGLE_API_KEY` from `.env` (R5) and runs at temperature 0 with a
    fixed seed (R22.1). A malformed response is rejected-and-retried and never
    enters an artifact (R19.2); a 429 waits-and-retries (R19.3); daily-quota
    exhaustion raises `QuotaExhausted` so the stage pauses cleanly (R19.4).
  * Mutation — REMOVED the in-place rewrite of `canonical_ontology_db.json` and
    the `rescue_progress.txt` sidecar. The stage now reads a versioned S04 input
    and writes a NEW versioned artifact (R2.4, R1.1). The input file is never
    opened for writing.
  * Resume — per-concept work is wrapped in `common.resumable_map` with its cache
    under `caches/s05_rescue_untreated/` (R8.1). An interrupted run resumes from
    the checkpoint and never repeats a completed concept's LLM calls (R8.2,
    R19.5). The artifact is promoted (written) ONLY after every concept completes
    (`run_resumable_stage`, R8.4, R19.6); a pause leaves the checkpoint but no
    partial primary artifact.
  * Lazy model load — the SentenceTransformer is loaded on first use inside the
    per-concept worker rather than at import, so importing this module (e.g. in
    tests) never forces a model download. The clustering itself is unchanged.
  * Exposes `run() -> Path` returning the new artifact path (R13.3).

Output contract per concept (unchanged from S04):
  {f, td, cov, props:{verb:{target:{f, v, e}}}, unt:[]}
"""

import re
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field
from sklearn.cluster import AgglomerativeClustering
from tqdm import tqdm

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s05_rescue_untreated"
BATCH_SIZE = 10

# ==========================================
# 1. VERB NORMALIZATION MAP (Port — unchanged)
# ==========================================
VERB_LEMMAS = {
    'use': 'use', 'uses': 'use', 'using': 'use', 'used': 'use',
    'utilize': 'utilize', 'utilizes': 'utilize', 'utilizing': 'utilize', 'utilized': 'utilize',
    'employ': 'employ', 'employs': 'employ', 'employing': 'employ', 'employed': 'employ',
    'apply': 'apply', 'applies': 'apply', 'applying': 'apply', 'applied': 'apply',
    'extract': 'extract', 'extracts': 'extract', 'extracting': 'extract', 'extracted': 'extract',
    'process': 'process', 'processes': 'process', 'processing': 'process', 'processed': 'process',
    'design': 'design', 'designs': 'design', 'designing': 'design', 'designed': 'design',
    'detect': 'detect', 'detects': 'detect', 'detecting': 'detect', 'detected': 'detect',
    'classify': 'classify', 'classifies': 'classify', 'classifying': 'classify', 'classified': 'classify',
    'segment': 'segment', 'segments': 'segment', 'segmenting': 'segment', 'segmented': 'segment',
    'generate': 'generate', 'generates': 'generate', 'generating': 'generate', 'generated': 'generate',
    'transform': 'transform', 'transforms': 'transform', 'transforming': 'transform', 'transformed': 'transform',
    'contain': 'contain', 'contains': 'contain', 'containing': 'contain', 'contained': 'contain',
    'include': 'include', 'includes': 'include', 'including': 'include', 'included': 'include',
    'perform': 'perform', 'performs': 'perform', 'performing': 'perform', 'performed': 'perform',
    'capture': 'capture', 'captures': 'capture', 'capturing': 'capture', 'captured': 'capture',
    'learn': 'learn', 'learns': 'learn', 'learning': 'learn', 'learned': 'learn',
    'predict': 'predict', 'predicts': 'predict', 'predicting': 'predict', 'predicted': 'predict',
    'identify': 'identify', 'identifies': 'identify', 'identifying': 'identify', 'identified': 'identify',
    'recognize': 'recognize', 'recognizes': 'recognize', 'recognizing': 'recognize', 'recognized': 'recognize',
    'analyze': 'analyze', 'analyzes': 'analyze', 'analyzing': 'analyze', 'analyzed': 'analyze',
    'produce': 'produce', 'produces': 'produce', 'producing': 'produce', 'produced': 'produce',
    'optimize': 'optimize', 'optimizes': 'optimize', 'optimizing': 'optimize', 'optimized': 'optimize',
    'approximate': 'approximate', 'approximates': 'approximate', 'approximating': 'approximate',
    'encode': 'encode', 'encodes': 'encode', 'encoding': 'encode', 'encoded': 'encode',
    'decode': 'decode', 'decodes': 'decode', 'decoding': 'decode', 'decoded': 'decode',
    'filter': 'filter', 'filters': 'filter', 'filtering': 'filter', 'filtered': 'filter',
    'map': 'map', 'maps': 'map', 'mapping': 'map', 'mapped': 'map',
    'reduce': 'reduce', 'reduces': 'reduce', 'reducing': 'reduce', 'reduced': 'reduce',
    'improve': 'improve', 'improves': 'improve', 'improving': 'improve', 'improved': 'improve',
    'reconstruct': 'reconstruct', 'reconstructs': 'reconstruct', 'reconstructing': 'reconstruct',
    'estimate': 'estimate', 'estimates': 'estimate', 'estimating': 'estimate', 'estimated': 'estimate',
}


# ==========================================
# 2. PYDANTIC SCHEMAS (Port — unchanged; now validated by common.call_llm)
# ==========================================
class Extraction(BaseModel):
    verb: str = Field(description="The base action verb (e.g., 'use', 'extract', 'process')")
    target: str = Field(description="The core target/object noun phrase (e.g., 'spatial features', 'grid-like data')")
    indices: List[int] = Field(description="List of definition indices (0-based) from the batch that share this exact verb and target")


class BatchExtractionResponse(BaseModel):
    extractions: List[Extraction] = Field(default_factory=list)


# The SentenceTransformer is loaded lazily on first use (see _get_model) so that
# importing this module never forces a model download.
_embedding_model = None


def _get_model():
    """Load the SentenceTransformer once, on first use (Port — same model)."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        print("🧠 Loading SentenceTransformer for target clustering...")
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model


# ==========================================
# 3. SEMANTIC CLUSTERING (Port — unchanged; lazy model load)
# ==========================================
def cluster_objects_semantically(unique_objects, threshold=0.35):
    if len(unique_objects) <= 1:
        return {obj: obj for obj in unique_objects}
    embeddings = _get_model().encode(list(unique_objects))
    clusterer = AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric='cosine', linkage='average'
    )
    labels = clusterer.fit_predict(embeddings)
    clusters = defaultdict(list)
    for obj, label in zip(unique_objects, labels):
        clusters[label].append(obj)
    canonical_map = {}
    for label, objs in clusters.items():
        objs.sort(key=len)
        canonical_name = objs[0]
        for obj in objs:
            canonical_map[obj] = canonical_name
    return canonical_map


# ==========================================
# 4. PROMPT (Port — unchanged wording)
# ==========================================
def _build_prompt(batch):
    formatted_batch = "\n".join([f"[{idx}] {defn}" for idx, defn in enumerate(batch)])
    return f"""You are an expert linguistic data extractor.
Below is a batch of {len(batch)} scientific definitions that our regex engine failed to parse.

Your task: Identify the core ACTION (verb) and TARGET (object/noun phrase) for each definition.

DEDUPLICATION RULE: If multiple definitions share the same core action and target (even with different surrounding words), group them and list all their indices. Do NOT output the same (verb, target) pair multiple times.

Definitions:
{formatted_batch}

Output ONLY a JSON object: {{"extractions": [{{"verb": "...", "target": "...", "indices": [0, 2, ...]}}]}}"""


# ==========================================
# 5. PER-CONCEPT WORKER (Port logic; guarded + resumable)
# ==========================================
def _rescue_concept(item):
    """Rescue one concept's untreated definitions.

    ``item`` is ``(concept_name, concept_data)``. Returns a JSON-serializable
    record describing the additions to make to the concept, so the checkpoint can
    resume without repeating LLM calls and ``build_output`` can merge it into the
    output DB. Raises :class:`common.QuotaExhausted` (propagated from
    ``call_llm``) so the stage pauses cleanly.
    """
    concept, data = item
    unt_list = data.get('unt', [])
    resolved_indices = set()
    new_extractions = []  # (norm_verb, raw_target, example)

    for i in range(0, len(unt_list), BATCH_SIZE):
        batch = unt_list[i:i + BATCH_SIZE]
        prompt = _build_prompt(batch)
        # Per-batch cache_key: stable across runs so a resume after a mid-concept
        # pause serves completed batches from the LLM cache (R19.5).
        cache_key = f"{concept}|batch|{i}"
        parsed = C.call_llm(
            prompt, cache_key=cache_key, schema=BatchExtractionResponse,
            stage=STAGE,
        )

        if parsed and parsed.extractions:
            idx_to_def = {idx: defn for idx, defn in enumerate(batch)}
            for ext in parsed.extractions:
                norm_verb = VERB_LEMMAS.get(ext.verb.lower().strip(), ext.verb.lower().strip())
                target = ext.target.strip()
                if not target or len(target) < 2:
                    continue
                for idx in ext.indices:
                    if 0 <= idx < len(batch):
                        resolved_indices.add(i + idx)  # global index in unt_list
                        new_extractions.append((norm_verb, target, idx_to_def[idx]))

    # Build the per-concept props additions (Port — same clustering + bookkeeping).
    new_props = {}
    if new_extractions:
        new_targets = list(set([t for _, t, _ in new_extractions]))
        canonical_map = cluster_objects_semantically(new_targets, threshold=0.35)
        for norm_verb, raw_target, example in new_extractions:
            canonical_target = canonical_map.get(raw_target, raw_target)
            verb_bucket = new_props.setdefault(norm_verb, {})
            entry = verb_bucket.setdefault(canonical_target, {'f': 0, 'v': {}, 'e': ''})
            entry['f'] += 1
            entry['v'][raw_target] = entry['v'].get(raw_target, 0) + 1
            if not entry['e']:
                entry['e'] = example

    # New untreated list = definitions we did NOT resolve.
    new_unt = [defn for j, defn in enumerate(unt_list) if j not in resolved_indices]

    # Recompute coverage (Port — same formula).
    total_defs = data.get('td', 0)
    cov = round((total_defs - len(new_unt)) / total_defs, 2) if total_defs > 0 else 0

    return {
        "concept": concept,
        "new_props": new_props,
        "new_unt": new_unt,
        "cov": cov,
        "n_extractions": len(new_extractions),
    }


def _merge_into_db(db, result):
    """Merge one ``_rescue_concept`` result into ``db`` in place (Port bookkeeping).

    New (verb, target) frequencies are ADDED onto any existing S04 edge exactly as
    the original in-place loop did; ``unt`` and ``cov`` are replaced with the
    recomputed values.
    """
    concept = result["concept"]
    if concept not in db:
        return
    data = db[concept]
    props = data.setdefault('props', {})
    for verb, targets in result["new_props"].items():
        verb_bucket = props.setdefault(verb, {})
        for target, add in targets.items():
            entry = verb_bucket.setdefault(target, {'f': 0, 'v': {}, 'e': ''})
            entry['f'] += add['f']
            for raw_v, cnt in add['v'].items():
                entry['v'][raw_v] = entry['v'].get(raw_v, 0) + cnt
            if not entry['e']:
                entry['e'] = add['e']
    data['unt'] = result["new_unt"]
    data['cov'] = result["cov"]


# ==========================================
# 6. MAIN (Port — logic preserved, I/O rewired, resumable)
# ==========================================
def run() -> Path:
    print("🚀 S05: rescuing untreated definitions via guarded LLM extraction...")

    in_path = C.require_latest("s04_extract_properties", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)

    # Concepts that still have untreated definitions are the ones to rescue.
    to_rescue = [
        (concept, data)
        for concept, data in db.items()
        if data.get('unt') and len(data['unt']) > 0
    ]
    print(f"🚨 {len(to_rescue)} concept(s) with untreated definitions to rescue.")

    # Shared counts dict: `run_resumable_stage` passes this SAME object to
    # `write_manifest` AFTER calling `build_output`, so metrics computed while
    # assembling the output DB below are reflected in the manifest line (R4.3).
    counts = {
        "concepts_total": len(db),
        "concepts_to_rescue": len(to_rescue),
    }

    def build_output(results):
        # Start from a copy of the full input DB (concepts without `unt` pass
        # through unchanged) and merge each rescued concept's additions.
        out_db = deepcopy(db)
        for r in results:
            _merge_into_db(out_db, r)
        counts["extractions_added"] = sum(r["n_extractions"] for r in results)
        counts["remaining_untreated"] = sum(
            len(v.get("unt", [])) for v in out_db.values()
        )
        return out_db

    # resumable_map keys on the concept NAME (stable id) so a re-run skips
    # already-rescued concepts and never repeats their LLM calls (R8.2, R19.5).
    out_path = C.run_resumable_stage(
        STAGE, __file__, to_rescue, _rescue_concept,
        key=lambda item: item[0],
        build_output=build_output,
        ext="json",
        in_path=in_path,
        counts=counts,
    )
    # On a pause, run_resumable_stage has already exited; reaching here means
    # every concept completed and the artifact was promoted.
    if out_path is not None:
        remaining_unt = sum(len(v.get('unt', [])) for v in C.load_json(out_path).values())
        print(f"[{STAGE}] rescue complete -> {out_path} "
              f"(remaining untreated definitions: {remaining_unt})")
    return out_path


if __name__ == "__main__":
    run()
