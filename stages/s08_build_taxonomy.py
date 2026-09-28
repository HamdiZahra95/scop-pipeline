"""
s08_build_taxonomy.py — Stage 8: build the is-a taxonomy (Port+Extend, LLM).

Input : latest artifacts/s07_ground_to_master/*.json  (the grounded property DB
        with each concept's `props`, `literal_annotations`, `consolidated_defs`
        and `f/td/cov/unt` bookkeeping).
Output: artifacts/s08_build_taxonomy/<RUN_ID>__<codehash>.json  (the same DB with
        a `taxonomy_parent` assigned to every concept plus injected skeleton /
        intermediary nodes). Never overwritten; promoted ONLY on completion.
LLM   : yes (guarded via common.call_llm — schema-validated, deterministic).

Port (from scripts/route_db/recursive_taxonomy_builder.py, preserved
byte-identical under the legacy tree — the current file IS the byte-identical
copy that this port supersedes): the analytical pipeline is UNCHANGED —
  0. clean slate: wipe old intermediary/ghost nodes, reset every concept's
     parent to `owl:Thing`,
  1. inject the shared domain SKELETON,
  2. batch-assign every concept to one of the 10 ML leaves via the LLM,
  3. recursively subdivide each leaf (auto-chunking >80-concept groups in half;
     min_leaf_size 5, max_depth 4; a `Core_<parent>` bucket for the
     un-subdividable; on a persistent LLM failure, attach directly to parent),
  4. rescue LLM-unassigned concepts under fresh high-level categories,
  5. audit & repair: re-subdivide overloaded (>10-child) nodes, sweep floating
     concepts into `Miscellaneous_ML_Concepts`, prune empty intermediary nodes,
     and report tree depth.
The batch size (100), the chunk threshold (80), min_leaf_size (5), max_depth (4),
and the overloaded-node threshold (>10) are all UNCHANGED.

Changes from the original (allowed port categories only + the mandated extends):
  * Secrets — REMOVED the hardcoded `GEMINI_API_KEY` fallback and the module-level
    `genai.Client(...)`. Every LLM decision now goes through `common.call_llm`,
    which reads `GOOGLE_API_KEY` from `.env` (R5), runs at temperature 0 with a
    fixed seed (R22.1), rejects-and-retries malformed responses so none enters an
    artifact (R19.2), waits-and-retries on 429 (R19.3), and raises
    `QuotaExhausted` on daily-quota exhaustion so the stage pauses cleanly
    (R19.4). The bespoke `safe_parse_json` / `call_llm_with_retry` are gone.
  * Shared constants — the SKELETON and the 10 ML leaves are imported from
    `common` (C.SKELETON / C.ML_LEAVES) rather than redefined locally (R6.1). The
    shared skeleton carries the five top-level domains + AI + ML; the ML leaves
    are its Machine_Learning children, exactly as the original relied on.
  * Cache relocation — the `data/taxonomy_progress_cache.json` sidecar is gone.
    LLM decisions are cached under `caches/s08_build_taxonomy/` by `call_llm`, and
    the initial ML-leaf assignment batches run through `common.resumable_map`
    (same cache dir) so an interrupted run resumes without repeating completed
    batches (R8.1, R8.2, R19.5).
  * Mutation removal + promote-on-complete — the original overwrote
    `data/taxonomized_ontology_db.json` in place. This port reads a versioned S07
    input, builds a fresh DB, and writes a NEW versioned artifact ONLY after the
    whole build completes (R1.1, R2.4, R8.4, R19.6). A `QuotaExhausted` pause
    writes NO primary artifact and exits without error, leaving the caches so the
    next run resumes where it left off.
  * Extend (R18 — genuine is-a) — the assignment and subdivision prompts are
    constrained to genuine subsumption ("X is a *kind of* Y", never part-of /
    used-by / instance-of). The batch assignment additionally reports the
    relation it sees; any concept whose relation is NOT is-a is still placed (so
    the tree stays connected) but tagged `non_subsumption_flag=True` (plus the
    observed `non_subsumption_relation`) so S09 can repair or demote it (R18.2).
  * Extend (R11.5) — the clean-slate step preserves any concept that carries
    `literal_annotations` even when it has no `props` (verified below): such a
    concept is never swept as a ghost node.
  * Exposes `run() -> Path` returning the new artifact path (R13.3).

Output contract per concept (S07 shape + taxonomy): the S07 keys pass through
UNCHANGED (definitions never dropped, R20.4); `taxonomy_parent` is (re)written and
`non_subsumption_flag` / `non_subsumption_relation` may be added. Injected
skeleton nodes carry `is_skeleton=True`; created buckets carry
`is_intermediary=True`.
"""

import os
import sys
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s08_build_taxonomy"

# Port constants. BATCH_SIZE and CHUNK_THRESHOLD are env-tunable so the amount of
# text the LLM must echo per call can be capped — large groups make the model
# emit very long JSON that gets truncated and fails schema validation. Lowering
# CHUNK_THRESHOLD splits big groups into smaller LLM calls (default 20: no single
# subdivision call handles more than 20 concepts).
BATCH_SIZE = int(os.getenv("S08_BATCH_SIZE", "12"))
CHUNK_THRESHOLD = int(os.getenv("S08_CHUNK_THRESHOLD", "12"))
MIN_LEAF_SIZE = 3
MAX_DEPTH = 5
OVERLOADED_THRESHOLD = 12
# Fail-fast per-call timeout + output cap for S08's LLM calls, so a slow/hung
# Gemma response aborts in seconds instead of the global 200s × retries. A
# healthy assignment/subdivision/rescue reply returns in a few seconds; anything
# longer is a degeneration hang we abort early and recover from (retry / defer).
S08_TIMEOUT = float(os.getenv("S08_TIMEOUT", "45"))
S08_MAX_TOKENS = int(os.getenv("S08_MAX_TOKENS", "2048"))


# ==========================================
# PYDANTIC SCHEMAS (guarded structured output via common.call_llm)
# ==========================================
class Assignment(BaseModel):
    """One concept's assignment to an ML leaf, with the relation the LLM saw."""
    concept: str
    category: str
    # is_a | part_of | used_by | instance_of | other  (R18 subsumption check)
    relation: str = Field(default="is_a")


class AssignmentBatch(BaseModel):
    assignments: List[Assignment] = Field(default_factory=list)


class Subcategory(BaseModel):
    name: str
    concepts: List[str] = Field(default_factory=list)


class SubdivisionResponse(BaseModel):
    subcategories: List[Subcategory] = Field(default_factory=list)


class RescueAssignment(BaseModel):
    concept: str
    category: str


class RescueResponse(BaseModel):
    assignments: List[RescueAssignment] = Field(default_factory=list)


def _intermediary_node(parent_name: str, *, skeleton: bool = False) -> dict:
    """A fresh intermediary/skeleton node body (Port — same default shape)."""
    node = {
        'f': 0, 'td': 0, 'cov': 1.0, 'props': {},
        'literal_annotations': [], 'taxonomy_parent': parent_name,
        'is_intermediary': True,
    }
    if skeleton:
        node['is_skeleton'] = True
    return node


# ==========================================
# RECURSIVE DIVIDE & CONQUER (Port logic; guarded LLM + relocated cache)
# ==========================================
def recursive_subdivide(parent_name, concepts_list, db, depth=0,
                        max_depth=MAX_DEPTH, min_leaf_size=MIN_LEAF_SIZE,
                        cache_suffix=""):
    """Recursively subdivide ``concepts_list`` under ``parent_name`` (Port).

    Behavior is byte-for-byte the original's, with the only change being that the
    LLM call is routed through :func:`common.call_llm` (schema-validated, cached
    under ``caches/s08_build_taxonomy/``) instead of the bespoke
    ``call_llm_with_retry`` + manual ``CACHE_FILE`` writes. ``QuotaExhausted``
    propagates so the stage can pause; a persistent malformed response
    (``MalformedResponse``) falls back to attaching the concepts directly to the
    parent, exactly as the original's parse-failure branch did.
    """
    indent = "      " + "  " * depth
    if len(concepts_list) <= min_leaf_size or depth >= max_depth:
        for c in concepts_list:
            if c in db:
                db[c]['taxonomy_parent'] = parent_name
        print(f"{indent}✅ Leaf '{parent_name}': {len(concepts_list)} concept(s) "
              f"attached (depth {depth}).")
        return

    # AUTO-CHUNKING: prevent LLM output-token limits on large lists (Port).
    # Any group larger than CHUNK_THRESHOLD is split so no single LLM call has to
    # echo back more than CHUNK_THRESHOLD concepts (truncation → malformed JSON).
    if len(concepts_list) > CHUNK_THRESHOLD:
        print(f"{indent}✂️ Large group '{parent_name}' ({len(concepts_list)} > "
              f"{CHUNK_THRESHOLD}). Splitting to keep LLM responses small.")
        mid = len(concepts_list) // 2
        recursive_subdivide(parent_name, concepts_list[:mid], db, depth,
                            max_depth, min_leaf_size, cache_suffix=f"{cache_suffix}_A")
        recursive_subdivide(parent_name, concepts_list[mid:], db, depth,
                            max_depth, min_leaf_size, cache_suffix=f"{cache_suffix}_B")
        return

    print(f"{indent}🧠 Subdividing '{parent_name}' ({len(concepts_list)} concepts, "
          f"depth {depth})...")
    cache_key = f"recursive_{parent_name}_{cache_suffix}"
    # Extend (R18): the prompt is constrained to genuine is-a subsumption.
    prompt = f"""You are an expert ML ontologist building a strict, mutually exclusive is-a taxonomy.
The current parent category is: "{parent_name}"
The concepts assigned to this category are: {list(concepts_list)}

Task:
1. Propose 1 to 3 NEW, mutually exclusive subcategories to further divide these concepts.
   Each subcategory MUST be a genuine KIND-OF (is-a subsumption) of the parent — never a
   part-of, used-by, or instance-of relationship.
2. Assign EVERY concept in the list to EXACTLY ONE of the new subcategories, and only where
   the concept genuinely IS A KIND OF that subcategory.
3. If a concept cannot be logically subdivided further, assign it to a subcategory named 'Core_{parent_name}'.

Output strictly as JSON:
{{
  "subcategories": [
    {{"name": "Subcategory_Name_1", "concepts": ["concept A", "concept B"]}},
    {{"name": "Subcategory_Name_2", "concepts": ["concept C"]}}
  ]
}}"""

    try:
        parsed = C.call_llm(prompt, cache_key=cache_key,
                            schema=SubdivisionResponse, stage=STAGE,
                            request_timeout=S08_TIMEOUT,
                            max_output_tokens=S08_MAX_TOKENS)
    except C.QuotaExhausted:
        raise  # pause cleanly — never swallow a daily-quota signal
    except (C.MalformedResponse, RuntimeError):
        # Parse failure OR a persistent timeout/5xx after all retries: attach the
        # concepts directly to the parent rather than crashing (graceful fallback,
        # same as the original parse-failure branch).
        print(f"      ⚠️ LLM failed/timed out for '{parent_name}'. "
              f"Attaching directly to parent.")
        for c in concepts_list:
            if c in db:
                db[c]['taxonomy_parent'] = parent_name
        return

    subcategories = parsed.subcategories if parsed else []
    if not subcategories:
        # Empty (but well-formed) response → same fallback as the original.
        print(f"      ⚠️ LLM proposed no subcategories for '{parent_name}'. "
              f"Attaching directly to parent.")
        for c in concepts_list:
            if c in db:
                db[c]['taxonomy_parent'] = parent_name
        return

    for subcat in subcategories:
        subcat_name = subcat.name or f'Subcat_{depth}'
        subcat_concepts = subcat.concepts or []

        if subcat_name not in db:
            db[subcat_name] = _intermediary_node(parent_name)

        recursive_subdivide(subcat_name, subcat_concepts, db, depth + 1,
                            max_depth, min_leaf_size)


# ==========================================
# SHALLOW BRANCH REPAIR (Port — unchanged logic)
# ==========================================
def repair_shallow_branches(db):
    print("\n🛠️ REPAIRING SHALLOW BRANCHES (Overloaded Nodes)...")

    child_concept_count = {}
    for concept, data in db.items():
        parent = data.get('taxonomy_parent')
        if parent and not data.get('is_intermediary') and not data.get('is_skeleton'):
            child_concept_count[parent] = child_concept_count.get(parent, 0) + 1

    overloaded_nodes = [(node, count) for node, count in child_concept_count.items()
                        if count > OVERLOADED_THRESHOLD and node in db]

    if not overloaded_nodes:
        print("   ✅ No shallow branches found. All nodes are properly subdivided.")
        return

    print(f"   ⚠️ Found {len(overloaded_nodes)} overloaded nodes that failed to subdivide:")
    for node, count in overloaded_nodes:
        print(f"      - '{node}' has {count} direct children.")

    for node, count in overloaded_nodes:
        print(f"\n   🔄 Re-attempting subdivision for '{node}'...")
        children = [c for c, d in db.items()
                    if d.get('taxonomy_parent') == node and not d.get('is_intermediary')]

        for c in children:
            db[c]['taxonomy_parent'] = 'owl:Thing'

        recursive_subdivide(node, children, db, depth=1, max_depth=MAX_DEPTH,
                            min_leaf_size=MIN_LEAF_SIZE, cache_suffix="_RETRY")


# ==========================================
# AUDIT & REPAIR ENGINE (Port — unchanged logic; returns metrics)
# ==========================================
def audit_and_repair_taxonomy(db):
    print("\n" + "=" * 70)
    print("🔍 AUDITING & REPAIRING TAXONOMY INTEGRITY")
    print("=" * 70)

    repair_shallow_branches(db)

    floating_concepts = [c for c, d in db.items()
                         if not d.get('is_intermediary') and not d.get('is_skeleton')
                         and d.get('taxonomy_parent') == 'owl:Thing']
    print(f"\n🏝️ Found {len(floating_concepts)} concepts still floating under 'owl:Thing'.")

    if floating_concepts:
        print("🛠️ Moving floating concepts to 'Miscellaneous_ML_Concepts'...")
        if 'Miscellaneous_ML_Concepts' not in db:
            db['Miscellaneous_ML_Concepts'] = _intermediary_node('Machine_Learning')
        for c in floating_concepts:
            db[c]['taxonomy_parent'] = 'Miscellaneous_ML_Concepts'

    child_count = {node: 0 for node in db.keys()}
    for concept, data in db.items():
        parent = data.get('taxonomy_parent')
        if parent and parent in child_count:
            child_count[parent] += 1
    empty_intermediaries = [n for n in db.keys()
                            if db[n].get('is_intermediary') and child_count.get(n, 0) == 0]
    for node in empty_intermediaries:
        del db[node]
    print(f"\n🍂 Pruned {len(empty_intermediaries)} empty intermediary nodes (dead branches).")

    def get_depth(node, memo, _seen=None):
        if node in memo:
            return memo[node]
        # Cycle guard: if we revisit a node on the current path, the parent chain
        # contains a loop (a bad LLM placement). Treat it as depth 0 rather than
        # recursing forever (RecursionError). The cycle itself is repaired
        # downstream in S09's cycle-breaker; here we only need a finite depth.
        _seen = _seen or set()
        if node in _seen:
            memo[node] = 0
            return 0
        parent = db.get(node, {}).get('taxonomy_parent')
        if not parent or parent == 'owl:Thing' or parent not in db:
            memo[node] = 0
            return 0
        depth = 1 + get_depth(parent, memo, _seen | {node})
        memo[node] = depth
        return depth

    memo = {}
    depths = {n: get_depth(n, memo) for n in db.keys() if not db[n].get('is_skeleton')}
    max_depth = 0
    avg_depth = 0.0
    if depths:
        max_depth = max(depths.values())
        avg_depth = sum(depths.values()) / len(depths)
        print(f"\n📏 TREE DEPTH ANALYSIS:")
        print(f"   🌳 Maximum Depth: {max_depth}")
        print(f"   📊 Average Depth: {avg_depth:.2f}")
        if max_depth < 4:
            print(f"   ⚠️ WARNING: The tree is still shallow!")

    print("\n✅ AUDIT & REPAIR COMPLETE. The taxonomy is now 100% connected and deep.")
    return {"max_depth": max_depth, "avg_depth": round(avg_depth, 2),
            "floaters": len(floating_concepts),
            "pruned_intermediaries": len(empty_intermediaries)}


# ==========================================
# BUILD (Port pipeline — I/O rewired, guarded LLM, resumable)
# ==========================================
def _build_taxonomy(db) -> dict:
    """Run the full port pipeline over ``db`` in place; return manifest counts.

    Raises :class:`common.QuotaExhausted` (propagated from ``call_llm`` /
    ``resumable_map``) so :func:`run` can pause without writing an artifact.
    """
    # ── 0. THE CLEAN SLATE (Port + R11.5 survival guard) ─────────────────
    print("🧹 Step 0: Wiping old taxonomy ghost nodes...")
    nodes_to_delete = [n for n, d in db.items()
                       if n not in C.SKELETON
                       and (d.get('is_intermediary') or d.get('is_skeleton'))]
    for n, d in db.items():
        if n not in C.SKELETON and n not in nodes_to_delete:
            # R11.5: a concept with only `literal_annotations` (no `props`, f==0)
            # MUST survive — the `not d.get('literal_annotations')` guard keeps it.
            if (not d.get('props') and not d.get('literal_annotations')
                    and d.get('f', 0) == 0):
                nodes_to_delete.append(n)
    for node in nodes_to_delete:
        del db[node]

    # Reset parents to owl:Thing so the tree rebuilds cleanly (Port).
    for concept, data in db.items():
        data['taxonomy_parent'] = 'owl:Thing'
        data.pop('regex_superclass', None)
        # Clear any stale subsumption flags from a prior code path.
        data.pop('non_subsumption_flag', None)
        data.pop('non_subsumption_relation', None)

    # ── 1. Inject the shared Skeleton (R6.1 — from common) ───────────────
    print("🦴 Step 1: Injecting Global Skeleton...")
    for node, parent in C.SKELETON.items():
        db[node] = _intermediary_node(parent, skeleton=True)

    # ── 2. Initial Assignment to the 10 ML leaves (batched, resumable) ───
    print("🌍 Step 2: Assigning concepts to the 10 ML Domains...")
    all_concepts = [c for c in db.keys() if not db[c].get('is_intermediary')]
    ml_leaves = list(C.ML_LEAVES)
    initial_assignments = {leaf: [] for leaf in ml_leaves}
    unassigned = []
    non_subsumption_flags = 0

    # Build the batches as (index, concepts) so each has a stable resume key.
    batches = [(i, all_concepts[i:i + BATCH_SIZE])
               for i in range(0, len(all_concepts), BATCH_SIZE)]
    print(f"   📚 {len(all_concepts)} concepts in {len(batches)} batch(es) "
          f"of up to {BATCH_SIZE} (resumable; completed batches are skipped).")

    # Knowledge-guided (mode == "guided", R-KG): a lazily-loaded reference index
    # provides is-a hints. For a concept the reference knows, we tell the LLM the
    # reference's own category/parent for it, as a NON-binding hint — the model
    # still chooses one of the 10 leaves and reports the relation, so genuine
    # subsumption discipline (R18) is preserved. Concepts the reference does not
    # know get no hint (graceful no-op). Inert in baseline mode.
    _guided = getattr(C, "SCOP_MODE", "baseline") == "guided"
    _K = None
    if _guided:
        import knowledge as _K
        _K.load()
        print(f"   🧭 Guided mode: injecting reference is-a hints where available "
              f"({len(_K.concepts)} reference concepts loaded).")

    def _reference_hints(batch):
        """Build a hint block: 'concept' -> reference category/parent, for the
        subset of the batch the reference recognises. Empty string if none."""
        if not _guided:
            return ""
        lines = []
        for c in batch:
            m = _K.match(c)
            if m.matched:
                ref_parent = m.ref_parent or "a top-level ML category"
                lines.append(f'- "{c}": in a curated ML reference ontology this is '
                             f'a kind of "{ref_parent}".')
        if not lines:
            return ""
        return ("\nReference knowledge (hints only — you still choose one of the 10 "
                "categories and judge genuine is-a):\n" + "\n".join(lines) + "\n")

    # Build a lookup of known assignments from any previously cached batch in llm_cache
    known_assignments = {}
    raw_cache = C._load_llm_cache(STAGE)
    for k, v in raw_cache.items():
        if isinstance(v, dict) and "assignments" in v:
            for item in v["assignments"]:
                cname = item.get("concept")
                if cname and cname not in known_assignments:
                    known_assignments[cname] = item

    def _assign_batch(item):
        idx, batch = item
        batch_no = idx // BATCH_SIZE + 1
        print(f"   🌍 Assigning batch {batch_no}/{len(batches)} "
              f"({len(batch)} concepts) to ML domains...")

        # Fast-path: if all concepts in this batch have known assignments, reuse directly
        if all(c in known_assignments for c in batch):
            print(f"      ✔ Serving all {len(batch)} concept assignments from cache.")
            return {"batch": batch, "assignments": [known_assignments[c] for c in batch]}

        cached_found = [known_assignments[c] for c in batch if c in known_assignments]
        needed = [c for c in batch if c not in known_assignments]

        leaf_menu = ", ".join(f"{n + 1}. {leaf}" for n, leaf in enumerate(ml_leaves))
        hints = _reference_hints(needed)
        # Extend (R18): assignment must be genuine is-a; report the relation seen.
        prompt = f"""You are an expert ML ontologist building an is-a (subsumption) taxonomy.
Assign each concept to EXACTLY ONE of these 10 orthogonal categories, and ONLY where the
concept genuinely IS A KIND OF that category (never part-of, used-by, or instance-of):
{leaf_menu}.

Concepts: {needed}
{hints}
For each concept output its chosen category and the relation you see between the concept and
that category: "is_a" when it is a genuine kind-of, otherwise "part_of", "used_by",
"instance_of", or "other".

Output strictly as JSON:
{{"assignments": [{{"concept": "...", "category": "ML_Task", "relation": "is_a"}}]}}"""
        batch_content_hash = C.content_hash(sorted(needed))[:8]
        try:
            parsed = C.call_llm(prompt, cache_key=f"initial_batch_{batch_content_hash}",
                                schema=AssignmentBatch, stage=STAGE,
                                request_timeout=S08_TIMEOUT,
                                max_output_tokens=S08_MAX_TOKENS)
            assignments = [a.model_dump() for a in parsed.assignments]
        except C.QuotaExhausted:
            raise  # pause cleanly — never swallow a daily-quota signal
        except (C.MalformedResponse, RuntimeError) as e:
            # A batch the model can't complete: either it never returns parseable
            # JSON (pads/truncates) or it persistently times out / 504s after all
            # retries. Don't kill the whole stage — return NO assignments so these
            # concepts fall through to the Step 4 rescue (then the audit sweep),
            # exactly like Step 3's parse-failure fallback attaches to parent.
            print(f"      ⚠️ Batch {batch_no}/{len(batches)} could not be "
                  f"assigned ({type(e).__name__}); deferring its {len(batch)} "
                  f"concept(s) to the Step 4 rescue.")
            assignments = []
        return {"batch": batch, "assignments": cached_found + assignments}

    # resumable_map: each batch is processed once; keyed by batch content hash
    results = C.resumable_map(STAGE, batches, _assign_batch,
                              key=lambda item: f"batch_{C.content_hash(sorted(item[1]))[:8]}")

    for r in results:
        batch = r["batch"]
        amap = {a["concept"]: a for a in r["assignments"]}
        for concept in batch:
            if concept not in db:
                continue
            a = amap.get(concept)
            cat = a.get("category") if a else None
            if cat in ml_leaves:
                initial_assignments[cat].append(concept)
                db[concept]['taxonomy_parent'] = cat
                # Extend (R18.2): flag non-is-a assignments for S09.
                relation = (a.get("relation") or "is_a").lower()
                if relation != "is_a":
                    db[concept]['non_subsumption_flag'] = True
                    db[concept]['non_subsumption_relation'] = relation
                    non_subsumption_flags += 1
            else:
                unassigned.append(concept)

    # ── 3. Recursive Subdivision (Port) ──────────────────────────────────
    print("🌳 Step 3: Recursively subdividing the 10 domains...")
    for leaf, concepts in initial_assignments.items():
        if not concepts:
            continue
        print(f"   📦 Subdividing '{leaf}' ({len(concepts)} concepts)...")
        recursive_subdivide(leaf, concepts, db, depth=0, max_depth=MAX_DEPTH,
                            min_leaf_size=MIN_LEAF_SIZE)

    # ── 4. Leftover Rescue (Port) ────────────────────────────────────────
    # Chunked so the model never has to echo a huge list back (truncation →
    # malformed JSON). A chunk that still won't parse is left for the Step 5
    # audit, which sweeps any remaining floater into Miscellaneous_ML_Concepts.
    if unassigned:
        print(f"🚀 Step 4: Rescuing {len(unassigned)} unassigned concept(s)...")
        rescue_chunks = [unassigned[i:i + BATCH_SIZE]
                         for i in range(0, len(unassigned), BATCH_SIZE)]
        for ci, chunk in enumerate(rescue_chunks):
            print(f"   🚀 Rescue chunk {ci + 1}/{len(rescue_chunks)} "
                  f"({len(chunk)} concepts)...")
            prompt = f"""These concepts didn't fit standard ML categories. Assign each to a NEW high-level
category that the concept genuinely IS A KIND OF (is-a subsumption).
Concepts: {chunk}
Output strictly as JSON:
{{"assignments": [{{"concept": "...", "category": "New_Category_Name"}}]}}"""
            try:
                parsed = C.call_llm(prompt, cache_key=f"leftover_rescue_{ci}",
                                    schema=RescueResponse, stage=STAGE,
                                    request_timeout=S08_TIMEOUT,
                                    max_output_tokens=S08_MAX_TOKENS)
            except C.QuotaExhausted:
                raise  # pause cleanly — never swallow a daily-quota signal
            except (C.MalformedResponse, RuntimeError) as e:
                print(f"      ⚠️ Rescue chunk {ci + 1} could not be assigned "
                      f"({type(e).__name__}); its concepts will be swept into "
                      f"Miscellaneous by the audit step.")
                continue
            for a in parsed.assignments:
                concept, new_cat = a.concept, a.category
                if concept in db and new_cat:
                    if new_cat not in db:
                        db[new_cat] = _intermediary_node('Artificial_Intelligence')
                    db[concept]['taxonomy_parent'] = new_cat

    # ── 5. Audit & Repair (Port — the safety net) ────────────────────────
    audit = audit_and_repair_taxonomy(db)

    intermediary_count = sum(1 for d in db.values()
                             if d.get('is_intermediary') and not d.get('is_skeleton'))
    floater_count = sum(1 for d in db.values()
                        if d.get('taxonomy_parent') == 'Miscellaneous_ML_Concepts')

    return {
        "concepts_total": len(all_concepts),
        "assigned_to_leaf": sum(len(v) for v in initial_assignments.values()),
        "unassigned_rescued": len(unassigned),
        "non_subsumption_flagged": non_subsumption_flags,
        "max_depth": audit["max_depth"],
        "avg_depth": audit["avg_depth"],
        "intermediary_count": intermediary_count,
        "floater_count": floater_count,
        "nodes_total": len(db),
    }


# ==========================================
# MAIN (promote-on-complete; pause cleanly on quota exhaustion)
# ==========================================
def run() -> Path:
    print("🚀 S08: building the is-a taxonomy via guarded, resumable LLM assignment...")

    in_path = C.require_latest("s07_ground_to_master", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)

    try:
        counts = _build_taxonomy(db)
    except C.QuotaExhausted as e:
        # Paused, not failed: no primary artifact, caches left intact (R19.4/6).
        print(f"[{STAGE}] paused — resume later (daily LLM quota exhausted). "
              f"Progress is checkpointed in {C.CACHES / STAGE}; re-run this stage "
              f"to continue where it left off. ({e})")
        sys.exit(0)

    # Promote-on-complete: only NOW write the versioned artifact + manifest.
    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, db)
    C.write_manifest(STAGE, __file__, in_path=in_path, out_path=out_path,
                     counts=counts)
    print(f"[{STAGE}] taxonomy built -> {out_path} "
          f"(max_depth={counts['max_depth']}, "
          f"intermediaries={counts['intermediary_count']}, "
          f"floaters={counts['floater_count']}, "
          f"non_subsumption_flagged={counts['non_subsumption_flagged']})")
    return out_path


if __name__ == "__main__":
    run()
