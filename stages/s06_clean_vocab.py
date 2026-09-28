"""
s06_clean_vocab.py — Stage 6: clean/normalize the property vocabulary (Port).

Input : latest artifacts/s05_rescue_untreated/*.json  (the S05 rescued property
        DB). S05 preserves the same `{f, td, cov, props, unt}` contract as S04 but
        with `props` enriched by the LLM rescue of untreated definitions. (Task 5
        temporarily wired S06 to read S04 so it was testable before S05 existed;
        task 8.1 re-pointed it here now that S05 lands.)
Output: artifacts/s06_clean_vocab/<RUN_ID>__<codehash>.json  (never overwritten)
LLM   : no

Port (from scripts/route_db/clean_onto_db.py, preserved byte-identical under the
legacy tree): the three-pass vocabulary cleanup is UNCHANGED in behavior —
  Pass 1  string cleanup (lowercase, strip leading articles + trailing
          punctuation) and verb-synonym merge (utilize/employ/apply → use,
          perform → execute).
  Pass 2  plural → singular merge (a plural target folds into its singular when
          the singular already exists in the vocabulary).
  Pass 3  strict semantic target clustering — agglomerative, cosine distance
          threshold 0.15 (≈ cosine similarity ≥ 0.85) — mapping each target to
          the shortest surface string in its cluster.

R20 synonym note: this stage's semantic target clustering IS the pipeline's true
synonym-consolidation step (semantic judgement beyond the case/whitespace
normalization S02 does — R20.2). It is kept HERE, deliberately, and never folded
into S02. Every surface form that gets merged into a canonical target is recorded
on that target as `sf` (see below) so S11 can emit them as `skos:altLabel`
(R20.1) on the canonical class.

Changes from the original (allowed port categories only):
  * I/O — read the LATEST S04 artifact via `common.require_latest` instead of a
    hardcoded `canonical_ontology_db.json`; write a NEW versioned artifact via
    `common.output_path(...)` instead of overwriting `cleaned_ontology_db.json`
    (R1.1, R2.3, R13.3). Removed the stale
    "Re-run build_ontology_graphs.py …" print at the end (dead cross-script
    instruction that has no place in the staged pipeline).
  * Surface-form recording — each canonical target entry gains an `sf` list: the
    sorted distinct surface strings (raw variants + article/plural/semantic
    variants) that were folded into it across the three passes. This is the sole
    source for S11's `skos:altLabel` (R20.1). The `{f, td, cov, props, unt}`
    per-concept schema is otherwise unchanged; each target's inner dict goes from
    `{f, v, e}` to `{f, v, e, sf}`.
  * Lazy model load + extractable clustering — the SentenceTransformer is loaded
    on first use inside `_semantic_target_map` (not at import), so importing the
    module in tests never forces a model download. The clustering parameters
    (cosine, distance_threshold=0.15, average linkage, shortest-string canonical)
    are UNCHANGED.
  * Manifest — one line per run reporting concept count, vocabulary size before
    and after (verbs + targets), and the alt-label surface-form counts (R4.2).
  * Exposes `run() -> Path` returning the new artifact path (R13.3).

Output contract per concept (S04 shape + `sf`):
  {f, td, cov, props:{verb:{target:{f, v, e, sf:[...]}}}, unt:[],
   consolidated_definitions:[...]}
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

from sklearn.cluster import AgglomerativeClustering

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s06_clean_vocab"

# ==========================================
# 1. STRONGER VERB NORMALIZATION (Port — unchanged)
# ==========================================
VERB_MERGE = {
    'utilize': 'use', 'utilizes': 'use', 'utilizing': 'use', 'utilized': 'use',
    'employ': 'use', 'employs': 'use', 'employing': 'use', 'employed': 'use',
    'apply': 'use', 'applies': 'use', 'applying': 'use', 'applied': 'use',
    'perform': 'execute', 'performs': 'execute', 'performing': 'execute', 'performed': 'execute',
}

# The SentenceTransformer is loaded lazily on first use (see _get_model) so that
# importing this module never forces a model download.
_embedding_model = None


def _get_model():
    """Load the SentenceTransformer once, on first use (Port — same model)."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        print("🧠 Loading SentenceTransformer model (one time)...")
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model


# ==========================================
# 2. TARGET CLEANUP FUNCTIONS (Port — unchanged)
# ==========================================
def clean_target_string(t):
    t = t.lower().strip()
    # Remove leading articles (a, an, the)
    t = re.sub(r'^(a |an |the )', '', t)
    # Remove trailing punctuation
    t = t.rstrip('.,;:')
    return t


def singularize(word):
    # Simple pluralization rules for technical terms
    if word.endswith('ies'):
        return word[:-3] + 'y'
    if word.endswith('ses') or word.endswith('xes') or word.endswith('zes') or word.endswith('ches') or word.endswith('shes'):
        return word[:-2]
    if word.endswith('s') and not word.endswith('ss') and not word.endswith('us') and not word.endswith('is'):
        return word[:-1]
    return word


def _semantic_target_map(unique_targets):
    """Pass-3 semantic clustering (Port — unchanged parameters; lazy model load).

    Agglomerative clustering at cosine distance_threshold 0.15 (≈ similarity
    ≥ 0.85), average linkage; each target maps to the SHORTEST surface string in
    its cluster. Extracted into a helper (from the original inline block) purely
    so it can be exercised offline in tests; the analytical behavior is
    identical.
    """
    if len(unique_targets) <= 1:
        return {t: t for t in unique_targets}

    model = _get_model()
    embeddings = model.encode(unique_targets)

    # Tighter threshold for semantic merging (0.15 distance = ~0.85+ similarity)
    clusterer = AgglomerativeClustering(
        n_clusters=None, distance_threshold=0.15, metric='cosine', linkage='average'
    )
    labels = clusterer.fit_predict(embeddings)

    clusters = defaultdict(list)
    for t, label in zip(unique_targets, labels):
        clusters[label].append(t)

    # Map each target to the shortest string in its cluster
    semantic_map = {}
    for label, group in clusters.items():
        group.sort(key=len)
        canonical = group[0]
        for t in group:
            semantic_map[t] = canonical
    return semantic_map


def run() -> Path:
    print("🚀 S06: cleaning property vocabulary (verb merge, plural, semantic)...")

    # ── LOAD latest S05 artifact (the rescued property DB) ────────────────
    # Re-pointed from S04 to S05 in task 8.1: S05 preserves the same
    # `{f, td, cov, props, unt}` contract but with `props` enriched by the LLM
    # rescue of untreated definitions, so S06 cleans the fuller vocabulary.
    in_path = C.require_latest("s05_rescue_untreated", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)

    # surface_map[target] = set of surface strings that fold into this target.
    # Seeded in Pass 1 and carried forward as targets merge in Passes 2 & 3, so
    # the final canonical target owns every variant string ever merged into it.
    surface_map = defaultdict(set)

    # ==========================================
    # 3. FIRST PASS: STRING CLEANUP & VERB MERGE (Port — unchanged)
    # ==========================================
    print("🧹 Pass 1: Cleaning strings, lowercasing, and merging verbs...")
    cleaned_db = {}
    all_targets_raw = set()

    # Vocabulary size BEFORE cleanup, for the manifest.
    verbs_before = set()
    targets_before = set()

    for concept, data in db.items():
        new_props = defaultdict(lambda: defaultdict(lambda: {'f': 0, 'v': {}, 'e': ''}))

        for verb, targets in data.get('props', {}).items():
            verbs_before.add(verb)
            # Normalize verb
            norm_verb = VERB_MERGE.get(verb, verb)

            for target, t_data in targets.items():
                targets_before.add(target)
                # Clean target string
                clean_t = clean_target_string(target)
                all_targets_raw.add(clean_t)

                # Surface bookkeeping: the original target string and every raw
                # variant recorded by S04 are surface forms of the cleaned target.
                orig = str(target).lower().strip()
                if orig and orig != clean_t:
                    surface_map[clean_t].add(orig)
                for raw_v in t_data.get('v', {}).keys():
                    rv = str(raw_v).lower().strip()
                    if rv and rv != clean_t:
                        surface_map[clean_t].add(rv)

                entry = new_props[norm_verb][clean_t]
                entry['f'] += t_data['f']
                # Merge variations
                for raw_v, count in t_data['v'].items():
                    entry['v'][raw_v] = entry['v'].get(raw_v, 0) + count
                if not entry['e'] and t_data['e']:
                    entry['e'] = t_data['e']

        cleaned_db[concept] = {
            'f': data['f'],
            'td': data['td'],
            'cov': data['cov'],
            'props': {v: dict(t) for v, t in new_props.items()},
            'unt': data.get('unt', []),
            # R20.3: carry definitions through this field-by-field rebuild so
            # they survive to S11 (S07/S08/S09/S09a/S10 preserve concept keys).
            'consolidated_definitions': data.get('consolidated_definitions', []),
        }

    # ==========================================
    # 4. SECOND PASS: PLURAL/SINGULAR MERGE (Port — unchanged)
    # ==========================================
    print("🔤 Pass 2: Merging plurals to singular...")
    target_list = list(all_targets_raw)
    target_set = set(target_list)

    plural_map = {}
    for t in target_list:
        sing = singularize(t)
        if sing != t and sing in target_set:
            plural_map[t] = sing

    # Apply plural map
    for concept, data in cleaned_db.items():
        new_props = defaultdict(lambda: defaultdict(lambda: {'f': 0, 'v': {}, 'e': ''}))
        for verb, targets in data['props'].items():
            for target, t_data in targets.items():
                final_t = plural_map.get(target, target)
                if final_t != target:
                    # 'target' (the plural) is a surface form of its singular.
                    surface_map[final_t].update(surface_map.get(target, set()))
                    surface_map[final_t].add(target)
                entry = new_props[verb][final_t]
                entry['f'] += t_data['f']
                for raw_v, count in t_data['v'].items():
                    entry['v'][raw_v] = entry['v'].get(raw_v, 0) + count
                if not entry['e'] and t_data['e']:
                    entry['e'] = t_data['e']
        data['props'] = {v: dict(t) for v, t in new_props.items()}

    # ==========================================
    # 5. THIRD PASS: SEMANTIC CLUSTERING (STRICT) (Port — unchanged)
    # ==========================================
    print("🧠 Pass 3: Semantic clustering of remaining targets...")
    # Get unique targets after plural merge
    unique_targets = set()
    for concept, data in cleaned_db.items():
        for verb, targets in data['props'].items():
            unique_targets.update(targets.keys())

    unique_targets = list(unique_targets)
    print(f"   Found {len(unique_targets)} unique targets to cluster.")

    if len(unique_targets) > 1:
        semantic_map = _semantic_target_map(unique_targets)

        # Apply semantic map
        print(f"   Merged down to {len(set(semantic_map.values()))} canonical targets.")
        for concept, data in cleaned_db.items():
            new_props = defaultdict(lambda: defaultdict(lambda: {'f': 0, 'v': {}, 'e': ''}))
            for verb, targets in data['props'].items():
                for target, t_data in targets.items():
                    final_t = semantic_map.get(target, target)
                    if final_t != target:
                        # 'target' is a synonym surface form of its canonical.
                        surface_map[final_t].update(surface_map.get(target, set()))
                        surface_map[final_t].add(target)
                    entry = new_props[verb][final_t]
                    entry['f'] += t_data['f']
                    for raw_v, count in t_data['v'].items():
                        entry['v'][raw_v] = entry['v'].get(raw_v, 0) + count
                    if not entry['e'] and t_data['e']:
                        entry['e'] = t_data['e']
            data['props'] = {v: dict(t) for v, t in new_props.items()}

    # ==========================================
    # 6. ATTACH merged surface forms (alt-label source for S11 — R20.1)
    # ==========================================
    # Each canonical target carries the sorted distinct surface strings that were
    # folded into it (excluding the canonical itself). S11 reads these to emit
    # skos:altLabel on the canonical class.
    alt_label_targets = 0
    alt_label_surface_forms = 0
    for concept, data in cleaned_db.items():
        for verb, targets in data['props'].items():
            for target, entry in targets.items():
                sf = sorted(s for s in surface_map.get(target, set()) if s and s != target)
                entry['sf'] = sf
                if sf:
                    alt_label_targets += 1
                    alt_label_surface_forms += len(sf)

    # ==========================================
    # 7. SAVE new versioned artifact + manifest
    # ==========================================
    final_targets = set()
    final_verbs = set()
    for concept, data in cleaned_db.items():
        for verb, targets in data['props'].items():
            final_verbs.add(verb)
            final_targets.update(targets.keys())

    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, cleaned_db)

    C.write_manifest(
        STAGE, __file__, in_path=in_path, out_path=out_path,
        counts={
            "concepts": len(cleaned_db),
            "verbs_before": len(verbs_before),
            "verbs_after": len(final_verbs),
            "targets_before": len(targets_before),
            "targets_after": len(final_targets),
            "alt_label_targets": alt_label_targets,
            "alt_label_surface_forms": alt_label_surface_forms,
        },
    )
    print(f"\n✅ CLEANUP COMPLETE!")
    print(f"📉 Original Unique Targets: {len(all_targets_raw)}")
    print(f"✨ Final Unique Targets: {len(final_targets)}")
    print(f"🔧 Final Unique Verbs: {len(final_verbs)}")
    print(f"🏷️  Recorded {alt_label_surface_forms} alt-label surface form(s) "
          f"across {alt_label_targets} canonical target(s).")
    print(f"[{STAGE}] wrote {len(cleaned_db)} concepts -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
