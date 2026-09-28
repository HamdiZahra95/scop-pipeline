"""
s04_extract_properties.py — Stage 4: mine (verb, object) properties (Port).

Input : the `freq_gt_10` bin of the latest artifacts/s03_frequency_gate/<run>/
        directory (the single source of truth for the frequency gate — the
        trusted, high-frequency core produced by S03).
Output: artifacts/s04_extract_properties/<RUN_ID>__<codehash>.json  (never overwritten)
LLM   : no

Port (from scripts/route_db/build_ontology_db.py, preserved byte-identical under
legacy): for every high-frequency concept, regex-mine `(verb, object)` actions
from its `consolidated_definitions`, lemmatize the verbs, semantically cluster
the mined objects into canonical targets, and record coverage plus the untreated
definitions. The analytical logic (the four regex patterns, the verb-lemma map,
the agglomerative object clustering at cosine distance 0.35, the coverage/`unt`
bookkeeping) is UNCHANGED.

Changes from the original (allowed port categories only):
  * I/O — read only the `freq_gt_10` bin from the LATEST S03 versioned directory
    (via `require_latest_dir` below) rather than scanning a hardcoded
    `frequency_bins/` folder and re-filtering by `corpus_frequency > 10`
    internally. S03 already applied the gate, so the gate lives in exactly one
    place (R21.1). Write a new versioned artifact via `common.output_path(...)`
    instead of overwriting `canonical_ontology_db.json` (R1.1, R2.3).
  * Manifest — one line per run reporting concept count, mean coverage, and the
    total distinct mined-verb count (R4.1, R4.2).
  * Lazy model load — the SentenceTransformer is loaded on first use inside
    `run()` rather than at import, so importing the module (e.g. in tests) does
    not force a model download. The clustering itself is unchanged.
  * Exposes `run() -> Path` returning the new artifact path (R13.3).

R23 note: the raw mined verbs recorded here under `props[verb]...` are the SOLE
source of the later sub-property enrichment layer (S10 maps them to the 13 core
properties, S11 declares them `subPropertyOf`). Nothing from prior runs is reused.

Output contract per concept (R23 source):
  {f, td, cov, props:{verb:{target:{f, v, e}}}, unt:[],
   consolidated_definitions:[...]}
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

from sklearn.cluster import AgglomerativeClustering
from tqdm import tqdm

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s04_extract_properties"

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
# 2. EXTRACTION ENGINE (WITH TRACKING) (Port — unchanged)
# ==========================================
def extract_unified_actions_with_tracking(definitions):
    """Extracts actions and tracks which definitions were successfully parsed."""
    actions = []
    treated_indices = set()

    for idx, defn in enumerate(definitions):
        defn_lower = defn.lower()
        matched = False

        # P1: that/which + verb + obj
        for m in re.finditer(r'(?:that|which)\s+(use|uses|used|utilize|utilizes|utilized|employ|employs|employed|apply|applies|applied|extract|extracts|extracted|process|processes|processed|perform|performs|performed|contain|contains|contained|include|includes|included)\s+([a-zA-Z\s\-]+?)(?:\s+to\s+|\s+for\s+|\s+in\s+|\s+from\s+|\.|$)', defn_lower):
            actions.append((VERB_LEMMAS.get(m.group(1), m.group(1)), m.group(2).strip(), defn))
            matched = True

        # P2: utilizing/using/employing + obj
        for m in re.finditer(r'\b(utilizing|using|employing)\s+([a-zA-Z\s\-]+?)(?:\s+to\s+|\s+for\s+|\s+in\s+|\.|$)', defn_lower):
            actions.append((VERB_LEMMAS.get(m.group(1), m.group(1)), m.group(2).strip(), defn))
            matched = True

        # P3: used/designed/applied/specialized + for/to + obj
        for m in re.finditer(r'\b(used|designed|applied|specialized)\s+(?:for|to)\s+([a-zA-Z\s\-]+?)(?:\.|$|,)', defn_lower):
            actions.append((VERB_LEMMAS.get(m.group(1), m.group(1)), m.group(2).strip(), defn))
            matched = True

        # P4: to + verb + obj
        for m in re.finditer(r'\bto\s+(extract|extracts|extracted|process|processes|processed|transform|transforms|transformed|detect|detects|detected|classify|classifies|classified|segment|segments|segmented|generate|generates|generated|perform|performs|performed)\s+([a-zA-Z\s\-]+?)(?:\.|$|,)', defn_lower):
            actions.append((VERB_LEMMAS.get(m.group(1), m.group(1)), m.group(2).strip(), defn))
            matched = True

        if matched:
            treated_indices.add(idx)

    untreated = [defn for i, defn in enumerate(definitions) if i not in treated_indices]
    return actions, untreated


def cluster_objects_semantically(unique_objects, threshold=0.35):
    """Clusters objects semantically (Port — unchanged; lazy model load)."""
    if len(unique_objects) <= 1:
        return {obj: obj for obj in unique_objects}

    embeddings = _get_model().encode(list(unique_objects))
    clusterer = AgglomerativeClustering(n_clusters=None, distance_threshold=threshold, metric='cosine', linkage='average')
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
# 3. INPUT: latest S03 freq_gt_10 bin (single gate source) (I/O rewire)
# ==========================================
def require_latest_s03_dir() -> Path:
    """Return the newest S03 versioned output DIRECTORY.

    S03 emits a versioned directory (`<RUN_ID>__<codehash8>/`) rather than a
    single file, so `require_latest` (which globs files) does not apply. The
    directory names share S03's sortable `<RUN_ID>__<codehash8>` convention, so
    the lexicographically greatest sub-directory is the most recent run.
    """
    stage_dir = C.ARTIFACTS / "s03_frequency_gate"
    if not stage_dir.exists():
        raise FileNotFoundError(
            f"No output found for stage 's03_frequency_gate' (looked in "
            f"{stage_dir}). Run that stage first."
        )
    candidates = sorted(p for p in stage_dir.iterdir() if p.is_dir())
    if not candidates:
        raise FileNotFoundError(
            f"No versioned bin directory found for stage 's03_frequency_gate' "
            f"(looked in {stage_dir}). Run that stage first."
        )
    return candidates[-1]


# ==========================================
# 4. MAIN DATABASE BUILDER (Port — logic unchanged, I/O rewired)
# ==========================================
def run() -> Path:
    print("🚀 S04: mining (verb, object) properties from high-frequency concepts...")

    # ── 1. LOAD only the freq_gt_10 bin from the LATEST S03 directory ─────
    run_dir = require_latest_s03_dir()
    gate_bin = run_dir / "freq_gt_10.jsonl"
    if not gate_bin.is_file():
        raise FileNotFoundError(
            f"S03 run directory {run_dir} has no 'freq_gt_10.jsonl' bin; the "
            f"frequency gate produced no high-frequency concepts."
        )
    print(f"📂 Loading gate bin {gate_bin} ...")
    high_freq_concepts = {
        item["target_concept"]: item for item in C.load_jsonl(gate_bin)
    }
    print(f"📊 Found {len(high_freq_concepts)} high-frequency concepts to process.")

    ontology_db = {}

    for concept, data in tqdm(high_freq_concepts.items(), desc="Building Ontology DB"):
        definitions = data.get('consolidated_definitions', [])
        if not definitions:
            continue

        # 1. Extract & Track
        actions, untreated = extract_unified_actions_with_tracking(definitions)
        if not actions:
            continue

        # 2. Cluster Objects
        unique_objects = list(set([obj for _, obj, _ in actions]))
        canonical_map = cluster_objects_semantically(unique_objects, threshold=0.35)

        # 3. Build Canonical Structure
        props = defaultdict(lambda: defaultdict(lambda: {'f': 0, 'v': defaultdict(int), 'e': ''}))
        for verb, raw_obj, example in actions:
            canonical_target = canonical_map.get(raw_obj, raw_obj)
            entry = props[verb][canonical_target]
            entry['f'] += 1
            entry['v'][raw_obj] += 1
            if not entry['e']:
                entry['e'] = example

        # Convert defaultdicts to standard dicts for JSON serialization
        props_clean = {v: {t: {'f': d['f'], 'v': dict(d['v']), 'e': d['e']} for t, d in targets.items()} for v, targets in props.items()}

        # 4. Store in DB
        coverage = len(definitions) - len(untreated) / len(definitions) if definitions else 0
        ontology_db[concept] = {
            'f': data['corpus_frequency'],
            'td': len(definitions),
            'cov': round(coverage, 2),
            'props': props_clean,
            'unt': untreated[:20],  # Cap untreated at 20 to save space
            # R20.3: carry the consolidated definitions through so S11 can emit
            # skos:definition + rdfs:comment. They are read above (line ~200) but
            # were previously dropped here, leaving definition coverage at 0.
            'consolidated_definitions': definitions,
        }

    # ── 5. SAVE new versioned artifact + manifest ─────────────────────────
    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, ontology_db)

    # Manifest metrics: concept count, mean coverage, distinct mined-verb count.
    concept_count = len(ontology_db)
    mean_cov = (
        round(sum(d["cov"] for d in ontology_db.values()) / concept_count, 4)
        if concept_count else 0
    )
    distinct_verbs = {
        verb for d in ontology_db.values() for verb in d["props"].keys()
    }
    C.write_manifest(
        STAGE, __file__, in_path=gate_bin, out_path=out_path,
        counts={
            "high_freq_concepts_in": len(high_freq_concepts),
            "concepts_out": concept_count,
            "mean_coverage": mean_cov,
            "distinct_verbs": len(distinct_verbs),
        },
    )
    print(f"[{STAGE}] indexed {concept_count} concepts "
          f"(mean cov {mean_cov}, {len(distinct_verbs)} distinct verbs) -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
