# """
# s09_qa_repair.py — Stage 9: taxonomy QA & repair (New: merge of 9 scripts).

# Input : latest artifacts/s08_build_taxonomy/*.json  (the taxonomized property DB
#         with a `taxonomy_parent` on every concept, injected skeleton /
#         intermediary nodes, and S08's `non_subsumption_flag` markers).
# Output: artifacts/s09_qa_repair/<RUN_ID>__<codehash>.json  (`s09_taxonomy_qa.json`
#         — the same DB after nine QA operations run in memory in a fixed order).
#         Never overwritten; promoted ONLY on completion.
#         PLUS two READ-ONLY audits under reports/:
#           reports/<RUN_ID>__<codehash>.redundancy.json
#           reports/<RUN_ID>__<codehash>.validation.json
# LLM   : yes (guarded via common.call_llm — deterministic, cached; resumable via
#         common.resumable_map over each LLM sub-step's batches).

# New build (R11): this ONE script REPLACES the nine in-place Gen-2 QA scripts that
# each re-read and rewrote `data/taxonomized_ontology_db.json`. The nine scripts
# live verbatim under ``stages/_s09_qa_sources/`` for reference. Here their
# analytical logic is preserved but merged into a SINGLE non-mutating pass: S09
# reads the latest S08 once, runs the nine operations against ONE in-memory DB in
# the fixed dependency order below, and writes ONE new versioned artifact. It never
# mutates its input and never loops internally — one pass per invocation; a re-run
# produces a NEW versioned file (R11.1, R11.4).

# Fixed order (R11.2 — the dependency order the nine scripts implied):
#   1. fix broken parent chains        (routing_targets)               — mutate
#   2. promote/route orphan targets    (assign_parents_to_targets)     — mutate
#   3. rescue floating concepts        (rescue_floating_concepts)      — mutate
#   4. resubdivide promoted targets    (resubdivide_promoted_targets)  — mutate
#   5. refine overloaded >15 nodes     (onto_health_refinement)        — mutate
#   6. fix hierarchy/URI collisions +  (fix_db_hierarchy, uses shared  — mutate
#      enforce skeleton                 get_uri)
#   7. structural redundancy audit     (structural_redundancy_checker) — READ-ONLY
#        -> reports/<...>.redundancy.json
#   8. node validation audit           (llm_node_validator)            — READ-ONLY
#        -> reports/<...>.validation.json
#   9. apply audit fixes               (llm_issue_fixer)               — mutate

# Steps 1–6 and 9 mutate the in-memory DB; steps 7–8 emit read-only audits to
# ``reports/`` and are NOT the stage's primary artifact (R11.3).

# Changes from the nine originals (allowed port categories only — R13.1 — plus the
# mandated merge/dedup):
#   * Secrets — the hardcoded `GEMINI_API_KEY` fallback and module-level
#     `genai.Client(...)` in every source script are GONE. Every LLM decision goes
#     through `common.call_llm` (key from `.env`, temperature 0 + fixed seed,
#     reject-and-retry on malformed output, wait-and-retry on 429, `QuotaExhausted`
#     on daily-quota so the stage pauses cleanly).
#   * Dedup (R6.1) — the SKELETON / ML_LEAVES / TOP_LEVEL_DOMAINS constants, the
#     per-script `safe_parse_json`, and the bespoke `call_llm_with_retry` are
#     replaced by the shared `common` versions (`C.SKELETON`, `C.ML_LEAVES`,
#     `C.TOP_LEVEL_DOMAINS`, `C.safe_parse_json`, `C.call_llm`). `fix_db_hierarchy`'s
#     private `get_uri_name` is replaced by the shared `C.get_uri` / `C.get_uri_name`
#     (single source shared with S11 so URIs cannot disagree — R6.2).
#   * Cache relocation — the nine `data/*_cache.json` sidecars are gone; each LLM
#     sub-step runs through `common.resumable_map` (checkpoint under
#     `caches/s09_qa_repair/`) and `call_llm`'s own per-stage cache, so an
#     interrupted run resumes without repeating completed batches (R19.5).
#   * Mutation removal + promote-on-complete — the originals overwrote the shared DB
#     in place; this reads a versioned S08 input, mutates ONLY the in-memory copy,
#     and writes a NEW versioned artifact ONLY after the whole pass completes
#     (R1.1, R2.4, R19.6). A `QuotaExhausted` pause writes NO primary artifact.
#   * No internal loop (R11.4) — `onto_health_refinement`'s "run again for the next
#     layer" advice is dropped: S09 does exactly one pass; re-run for another pass.
#   * Guard (R11.5) — a concept carrying only `literal_annotations` and no `props`
#     is NEVER soft-deleted (`is_noise`) during chain/ghost cleanup. See
#     `_is_literal_only`.
#   * Extend (R18.2/R18.3) — the node-validation audit flags likely non-subsumption
#     edges (a method placed under an artifact, etc.) for repair or demotion to an
#     object property, and it also re-surfaces S08's `non_subsumption_flag` markers.
#   * Exposes `run() -> Path` returning the new artifact path (R13.3).
# """

# import os
# import sys
# from collections import defaultdict
# from difflib import SequenceMatcher
# from pathlib import Path

# # Make the package importable whether run from pipeline_v2/ or its parent.
# sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# import common as C

# STAGE = "s09_qa_repair"

# # Shared constants (from common — single source of truth, R6.1).
# VALID_ROOTS = list(C.TOP_LEVEL_DOMAINS)          # the 5 foundational domains
# ML_LEAVES = list(C.ML_LEAVES)                    # the 10 ML leaves

# # The skeleton fix_db_hierarchy (step 6) enforces: the CS→AI→ML spine plus the
# # ten ML leaves under Machine_Learning. Derived from the shared C.SKELETON so it
# # can never drift from S08/S11 (Port — same nodes the original hardcoded).
# CORRECT_SKELETON = {
#     node: parent for node, parent in C.SKELETON.items()
#     if node == "Computer_Science" or parent != "owl:Thing"
# }

# # Nodes to skip during node validation (step 8) — the fixed backbone (Port).
# SKIP_NODES = set(C.SKELETON.keys())

# # Port thresholds / batch sizes (UNCHANGED from the source scripts).
# CHAIN_FIX_BATCH = 30          # routing_targets
# ORPHAN_BATCH = 30             # assign_parents_to_targets
# RESCUE_BATCH = 15             # rescue_floating_concepts
# RESUBDIV_BATCH = 15           # resubdivide_promoted_targets
# BROKEN_CHAIN_BATCH = 5       # onto_health_refinement
# MAX_CHILDREN_THRESHOLD = 5   # onto_health_refinement overloaded threshold
# SEMANTIC_SIM_THRESHOLD = 0.85 # structural_redundancy_checker
# SEMANTIC_FIX_BATCH = 10       # llm_issue_fixer semantic-duplicate batch

# # Fail-fast per-call timeout + output cap for S09's LLM sub-steps, so a slow/hung
# # Gemma response aborts in seconds instead of the global 200s × retries. A
# # healthy routing/refinement reply returns in a few seconds; anything longer is a
# # degeneration hang we abort early and recover from (deferred to a later pass).
# S09_TIMEOUT = float(os.getenv("S09_TIMEOUT", "45"))
# S09_MAX_TOKENS = int(os.getenv("S09_MAX_TOKENS", "2048"))


# # ==========================================
# # SHARED HELPERS
# # ==========================================
# def _intermediary_node(parent_name: str, **flags) -> dict:
#     """A fresh intermediary node body (Port — same default shape the sources used)."""
#     node = {
#         'f': 0, 'td': 0, 'cov': 1.0, 'props': {},
#         'literal_annotations': [], 'taxonomy_parent': parent_name,
#         'is_intermediary': True,
#     }
#     node.update(flags)
#     return node


# def _is_literal_only(data: dict) -> bool:
#     """R11.5 guard: a concept carrying literal_annotations but NO props.

#     Such a concept holds demoted (grounded) knowledge that has nowhere else to
#     live, so chain/ghost cleanup must never soft-delete it.
#     """
#     return bool(data.get('literal_annotations')) and not data.get('props')


# def _is_protected_skeleton(concept: str) -> bool:
#     """True for the CS→AI→ML spine, the 5 domains, and the 10 ML leaves.

#     These structural anchors must never be deleted or merged away: every concept
#     is rooted through them, so removing one orphans its whole subtree from the
#     top-level domains (the S12 orphan_ratio warning). Guards OP6/OP9 cleanup.
#     """
#     return (concept in CORRECT_SKELETON
#             or concept in VALID_ROOTS
#             or concept in ML_LEAVES)


# def _mark_noise(db: dict, concept: str) -> bool:
#     """Soft-delete ``concept`` (set is_noise) UNLESS it is literal-annotation-only.

#     Returns True if the concept was marked, False if a guard protected it.
#     """
#     data = db.get(concept)
#     if data is None:
#         return False
#     if _is_protected_skeleton(concept):
#         print(f"      🦴 keeping skeleton/leaf anchor '{concept}' (never deleted).")
#         return False
#     if _is_literal_only(data):
#         print(f"      🛡️ R11.5: keeping literal-annotation-only concept '{concept}' "
#               f"(not deleting in cleanup).")
#         return False
#     data['is_noise'] = True
#     return True


# def _children_map(db: dict) -> dict:
#     """parent -> [child, ...] for every non-owl:Thing edge (Port helper)."""
#     cm = defaultdict(list)
#     for key, data in db.items():
#         parent = data.get('taxonomy_parent')
#         if parent and parent != 'owl:Thing':
#             cm[parent].append(key)
#     return cm

# # Sentinel stored in memory when an LLM batch ultimately fails. It is NEVER
# # written into a result consumed downstream, and its checkpoint file is purged
# # so a later run retries it (a failed batch must never be cached as `{}` —
# # that poisons the resume cache and makes the overload recur every run).
# _FAILED_BATCH = "__S09_FAILED_BATCH__"


# def _purge_failed_cache(substep: str) -> int:
#     """Delete cached checkpoints for ``substep`` that hold a poisoned empty
#     result (``{}``), i.e. results produced by an earlier version that cached
#     failures as success. Returns the number of purged entries."""
#     import json as _json
#     purged = 0
#     cache_dir = C.CACHES / STAGE
#     if not cache_dir.exists():
#         return 0
#     for f in sorted(cache_dir.glob(f"{substep}_*.json")):
#         try:
#             val = _json.loads(f.read_text())
#         except Exception:
#             continue
#         if val == {} or val == _FAILED_BATCH:
#             f.unlink()
#             purged += 1
#     return purged

# def _llm_route_batches(items, batch_size, prompt_builder, substep,
#                        *, retry_failed=True):
#     """Run an LLM routing sub-step over ``items`` in resumable batches.

#     Same contract as before: returns list of ``{"batch": [...], "parsed": {..}}``
#     in batch order. Two behavioural hardenings:

#     * A batch whose LLM call fails persistently yields ``parsed = _FAILED_BATCH``
#       in-memory AND has its checkpoint purged, so the NEXT run re-attempts it
#       (failures are never cached as success).
#     * Within one run, failed batches are retried once more at the end
#       (``retry_failed=True``) before being surfaced as failures.

#     Callers that need the old "silently skip failures" behaviour can filter:
#     ``r["parsed"] is C-style {}`` still means "no assignments".
#     """
#     batches = [(i // batch_size, items[i:i + batch_size])
#                for i in range(0, len(items), batch_size)]

#     def _fn(item):
#         idx, batch = item
#         prompt = prompt_builder(batch)
#         try:
#             parsed = C.call_llm(prompt, cache_key=f"{substep}_{idx}",
#                                 schema=C.safe_parse_json, stage=STAGE,
#                                 request_timeout=S09_TIMEOUT,
#                                 max_output_tokens=S09_MAX_TOKENS)
#         except C.QuotaExhausted:
#             raise  # pause cleanly — never swallow a daily-quota signal
#         except (C.MalformedResponse, RuntimeError):
#             # Persistent timeout/5xx/malformed after all retries: purge this
#             # batch's checkpoint so a later run retries it, and signal failure
#             # in-memory (never cache a failure as `{}`).
#             _purge_failed_cache(f"{substep}_{idx}")
#             return {"batch": batch, "parsed": _FAILED_BATCH}
#         if parsed == _FAILED_BATCH:          # defensive: sentinel leaked in
#             _purge_failed_cache(f"{substep}_{idx}")
#             return {"batch": batch, "parsed": _FAILED_BATCH}
#         if not isinstance(parsed, dict):
#             parsed = {}
#         return {"batch": batch, "parsed": parsed}

#     results = C.resumable_map(STAGE, batches, _fn,
#                               key=lambda it: f"{substep}_{it[0]}")

#     if retry_failed:
#         # One in-run second chance for transiently failing batches.
#         failed = [it for r, it in zip(results, batches)
#                   if r["parsed"] == _FAILED_BATCH]
#         if failed:
#             print(f"      ↻ retrying {len(failed)} failed "
#                   f"'{substep}' batch(es) once more...")
#             retried = C.resumable_map(STAGE, failed, _fn,
#                                       key=lambda it: f"{substep}_{it[0]}")
#             by_idx = {it[0]: r for it, r in zip(failed, retried)}
#             results = [by_idx[it[0]] if r["parsed"] == _FAILED_BATCH else r
#                        for r, it in zip(results, batches)]
#     return results

# # def _llm_route_batches(items, batch_size, prompt_builder, substep):
# #     """Run an LLM routing sub-step over ``items`` in resumable batches.

# #     Shared engine for the batched LLM operations (steps 1–5). Splits ``items``
# #     into ``batch_size`` chunks; each chunk is processed exactly once and cached
# #     under ``caches/s09_qa_repair/`` via :func:`common.resumable_map` (so an
# #     interrupted run resumes without repeating completed batches — R19.5). Every
# #     per-batch LLM call is guarded by :func:`common.call_llm` with
# #     :func:`common.safe_parse_json` as the validator; a persistently malformed
# #     response falls back to an empty mapping (``{}``) exactly as the source
# #     scripts' parse-failure branch did, rather than crashing the pass.

# #     Args:
# #         items: list of concept names to route.
# #         batch_size: source-script batch size for this sub-step.
# #         prompt_builder: ``prompt_builder(batch) -> str``.
# #         substep: unique cache-key prefix for this sub-step.

# #     Returns:
# #         list of ``{"batch": [...], "parsed": {..}}`` in batch order.
# #     """
# #     batches = [(i // batch_size, items[i:i + batch_size])
# #                for i in range(0, len(items), batch_size)]

# #     def _fn(item):
# #         idx, batch = item
# #         prompt = prompt_builder(batch)
# #         try:
# #             parsed = C.call_llm(prompt, cache_key=f"{substep}_{idx}",
# #                                 schema=C.safe_parse_json, stage=STAGE,
# #                                 request_timeout=S09_TIMEOUT,
# #                                 max_output_tokens=S09_MAX_TOKENS)
# #         except C.QuotaExhausted:
# #             raise  # pause cleanly — never swallow a daily-quota signal
# #         except (C.MalformedResponse, RuntimeError):
# #             # Unparseable OR a persistent timeout/5xx after all retries: fall back
# #             # to an empty mapping so this sub-step is a no-op for the batch rather
# #             # than crashing the whole pass (the source scripts' parse-failure
# #             # behaviour). Concepts simply keep their current placement.
# #             parsed = {}
# #         if not isinstance(parsed, dict):
# #             parsed = {}
# #         return {"batch": batch, "parsed": parsed}

# #     return C.resumable_map(STAGE, batches, _fn,
# #                            key=lambda it: f"{substep}_{it[0]}")


# # ==========================================
# # OP 1 — fix broken parent chains (routing_targets)  [MUTATE]
# # ==========================================
# def op1_fix_broken_chains(db: dict) -> dict:
#     print("\n🔗 OP1: validating & fixing broken parent chains...")

#     def is_chain_valid(node, visited=None):
#         if visited is None:
#             visited = set()
#         if node in visited:
#             return False            # cycle detected
#         visited.add(node)
#         if node in VALID_ROOTS:
#             return True
#         if node not in db:
#             return False            # parent missing from DB
#         parent = db[node].get('taxonomy_parent')
#         if not parent or parent == 'owl:Thing':
#             return False            # chain leads to owl:Thing prematurely
#         return is_chain_valid(parent, visited)

#     concepts_to_fix = []
#     for key, data in db.items():
#         if key in VALID_ROOTS:
#             continue
#         if data.get('is_noise'):
#             continue
#         if not is_chain_valid(key):
#             concepts_to_fix.append(key)

#     print(f"   Found {len(concepts_to_fix)} concepts with broken parent chains.")
#     if not concepts_to_fix:
#         return {"broken_chains_fixed": 0}

#     def _prompt(batch):
#         concepts_text = "\n".join(f"- {c}" for c in batch)
#         return f"""You are an expert ML ontologist. We have {len(batch)} concepts with broken hierarchy chains. You MUST assign each one to a valid parent from the list below.

# VALID PARENTS (Choose ONLY from these):
# Top-Level Domains:
# - Computer_Science, Mathematics, Physics, Biology, Engineering

# ML-Specific Categories:
# - Artificial_Intelligence, Machine_Learning
# - ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation
# - ML_Objective_and_Constraint, ML_Workflow_and_Protocol
# - ML_Foundations_and_Theory, ML_Infrastructure_and_Environment
# - ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance

# ROUTING RULES:
# 1. If it's a specific ML model (e.g., "Classification Model", "Neural Network"), assign to "ML_Model".
# 2. If it's a specific ML algorithm, assign to "ML_Algorithm".
# 3. If it's an ML task (e.g., "Image Segmentation"), assign to "ML_Task".
# 4. If it's pure Math/Physics/Biology, assign to that domain.
# 5. If it's a general CS concept, assign to "Computer_Science".

# CONCEPTS TO FIX:
# {concepts_text}

# Output strictly as a flat JSON dictionary mapping each concept to its parent from the valid list above.
# """

#     results = _llm_route_batches(concepts_to_fix, CHAIN_FIX_BATCH, _prompt, "chain_fix")
#     fixed = 0
#     for r in results:
#         parsed = r["parsed"]
#         for concept in r["batch"]:
#             parent = parsed.get(concept)
#             if not parent:  # keyword fallback (Port — same rules)
#                 cl = concept.lower()
#                 if 'model' in cl or 'network' in cl:
#                     parent = "ML_Model"
#                 elif 'algorithm' in cl or 'optimization' in cl:
#                     parent = "ML_Algorithm"
#                 elif 'task' in cl or 'segmentation' in cl:
#                     parent = "ML_Task"
#                 else:
#                     parent = "Computer_Science"
#             db[concept]['taxonomy_parent'] = parent
#             fixed += 1
#     print(f"   ✅ Routed {fixed} concepts to valid parents.")
#     return {"broken_chains_fixed": fixed}


# # ==========================================
# # OP 2 — promote/route orphan targets (assign_parents_to_targets)  [MUTATE]
# # ==========================================
# def op2_promote_orphan_targets(db: dict) -> dict:
#     print("\n📈 OP2: promoting & routing orphan targets...")

#     orphan_targets = set()
#     for data in db.values():
#         for _prop, targets in data.get('props', {}).items():
#             for target in targets.keys():
#                 if target not in db:
#                     orphan_targets.add(target)

#     print(f"   Found {len(orphan_targets)} orphan targets.")
#     if not orphan_targets:
#         return {"orphan_targets_promoted": 0}

#     orphan_list = list(orphan_targets)
#     # Promote them to top-level keys (empty shells, flagged for op4).
#     for target in orphan_list:
#         if target not in db:
#             db[target] = _intermediary_node('owl:Thing', is_intermediary=False,
#                                             is_promoted_target=True)

#     def _prompt(batch):
#         import json as _json
#         concepts_text = "\n".join(f"- {c}" for c in batch)
#         return f"""You are an expert ML ontologist. We have {len(batch)} concepts that were extracted as targets from definitions. They need to be placed in our ontology hierarchy.

# THE HIERARCHY STRUCTURE:
# - Computer_Science -> Artificial_Intelligence -> Machine_Learning -> [10 ML Leaves]
# - Mathematics (direct child of owl:Thing)
# - Physics (direct child of owl:Thing)
# - Biology (direct child of owl:Thing)
# - Engineering (direct child of owl:Thing)

# THE 10 ML LEAVES:
# {_json.dumps(ML_LEAVES)}

# ROUTING RULES:
# 1. If it's a core ML concept (model, algorithm, task, etc.), assign it to one of the 10 ML leaves.
# 2. If it's pure Math/Physics/Biology/Engineering, assign it to that top-level domain.
# 3. If it's an applied ML domain, assign it to "ML_Task" or "Computer_Science".
# 4. If it's a general CS concept, assign it to "Computer_Science".

# Concepts to route:
# {concepts_text}

# Output strictly as a flat JSON dictionary mapping each concept to its parent.
# """

#     results = _llm_route_batches(orphan_list, ORPHAN_BATCH, _prompt, "orphan")
#     for r in results:
#         parsed = r["parsed"]
#         for concept in r["batch"]:
#             parent = parsed.get(concept)
#             db[concept]['taxonomy_parent'] = parent if parent else "ML_Model"
#     print(f"   ✅ Promoted & routed {len(orphan_list)} orphan targets.")
#     return {"orphan_targets_promoted": len(orphan_list)}


# # ==========================================
# # OP 3 — rescue floating concepts (rescue_floating_concepts)  [MUTATE]
# # ==========================================
# def op3_rescue_floating(db: dict) -> dict:
#     print("\n🏝️ OP3: rescuing concepts floating under owl:Thing...")

#     floating = [k for k, v in db.items()
#                 if v.get('taxonomy_parent') == 'owl:Thing'
#                 and k not in VALID_ROOTS and not v.get('is_noise')]
#     print(f"   Found {len(floating)} floating concepts.")

#     deleted = 0
#     if floating:
#         def _prompt(batch):
#             import json as _json
#             concepts_text = "\n".join(f"- {c}" for c in batch)
#             return f"""You are an expert ontologist. We have {len(batch)} unassigned concepts. Route them to maintain a strict, scientifically accurate hierarchy.

# THE 5 FOUNDATIONAL DOMAINS (Top-Level):
# 1. Computer_Science (Includes AI, Software, Algorithms)
# 2. Mathematics (Includes Calculus, Linear Algebra, Probability, Statistics, Optimization)
# 3. Physics (Includes Quantum Mechanics, Thermodynamics, Statistical Mechanics)
# 4. Biology (Includes Neuroscience, Genetics, Bioinformatics, Ecology)
# 5. Engineering (Includes Hardware, Robotics, Electrical Engineering, Materials Science)

# ROUTING RULES:
# - If the concept belongs to pure Math, Physics, Biology, or Engineering, assign it to that exact Top-Level Domain name (e.g., "Mathematics").
# - If the concept is a core Machine Learning concept, assign it to one of these 10 ML leaves: {_json.dumps(ML_LEAVES)}.
# - If the concept is an applied ML domain (e.g., Medical Imaging), assign it to "Computer_Science".
# - If the concept is pure noise/garbage, assign it to "DELETE".

# Concepts to route:
# {concepts_text}

# Output strictly as a flat JSON dictionary mapping each concept to its destination.
# """

#         results = _llm_route_batches(floating, RESCUE_BATCH, _prompt, "rescue")
#         for r in results:
#             parsed = r["parsed"]
#             for concept in r["batch"]:
#                 destination = parsed.get(concept)
#                 if not destination:
#                     continue
#                 if destination == "DELETE":
#                     # R11.5 guard: never delete a literal-annotation-only concept.
#                     if _mark_noise(db, concept):
#                         deleted += 1
#                 elif destination in VALID_ROOTS or destination in ML_LEAVES:
#                     db[concept]['taxonomy_parent'] = destination
#                 else:
#                     # LLM hallucinated a category → fall back to Computer_Science.
#                     db[concept]['taxonomy_parent'] = "Computer_Science"

#     # Ensure the 5 foundational domains exist and are anchored at owl:Thing (Port).
#     for domain in VALID_ROOTS:
#         if domain not in db:
#             db[domain] = _intermediary_node('owl:Thing', is_skeleton=True)
#         else:
#             db[domain]['taxonomy_parent'] = 'owl:Thing'
#             db[domain]['is_skeleton'] = True

#     print(f"   ✅ Rescued {len(floating)} floating concepts "
#           f"({deleted} marked noise).")
#     return {"floating_rescued": len(floating), "floating_marked_noise": deleted}


# # ==========================================
# # OP 4 — resubdivide promoted targets (resubdivide_promoted_targets)  [MUTATE]
# # ==========================================
# def op4_resubdivide_promoted(db: dict) -> dict:
#     print("\n📦 OP4: re-subdividing promoted targets into subcategories...")
#     created = 0

#     for leaf in ML_LEAVES:
#         direct_children = [k for k, v in db.items() if v.get('taxonomy_parent') == leaf]
#         existing_subcats = [k for k in direct_children if db[k].get('is_intermediary')]
#         promoted_targets = [k for k in direct_children if db[k].get('is_promoted_target')]
#         original_concepts = [k for k in direct_children
#                              if not db[k].get('is_intermediary')
#                              and not db[k].get('is_promoted_target')]

#         if not promoted_targets:
#             continue

#         # No existing subcategories → create an initial subdivision (Port).
#         if not existing_subcats:
#             all_children = promoted_targets + original_concepts
#             if len(all_children) <= 5:
#                 continue

#             def _prompt_initial(batch, _leaf=leaf):
#                 concepts_text = "\n".join(f"- {c}" for c in batch)
#                 return f"""You are an expert ML ontologist. The category "{_leaf}" has {len(batch)} concepts that need to be organized into subcategories.

# Task:
# 1. Invent 3 to 5 NEW, mutually exclusive subcategory names.
# 2. Assign EVERY concept to EXACTLY ONE subcategory.

# Concepts:
# {concepts_text}

# Output strictly as a flat JSON dictionary mapping each concept to its subcategory name."""

#             results = _llm_route_batches(all_children, len(all_children) or 1,
#                                          _prompt_initial, f"initial_subdiv_{leaf}")
#             parsed = results[0]["parsed"] if results else {}
#             groups = defaultdict(list)
#             for concept, subcat_name in parsed.items():
#                 groups[subcat_name].append(concept)
#             for subcat_name, concepts in groups.items():
#                 if subcat_name not in db:
#                     db[subcat_name] = _intermediary_node(leaf)
#                     created += 1
#                 for c in concepts:
#                     if c in db:
#                         db[c]['taxonomy_parent'] = subcat_name
#             continue

#         # Existing subcategories → slot promoted targets + originals into them (Port).
#         concepts_to_place = promoted_targets + original_concepts
#         if not concepts_to_place:
#             continue

#         def _prompt_slot(batch, _leaf=leaf, _subcats=tuple(existing_subcats)):
#             concepts_text = "\n".join(f"- {c}" for c in batch)
#             subcats_text = "\n".join(f"- {s}" for s in _subcats)
#             return f"""You are an expert ML ontologist. We need to place {len(batch)} concepts into existing subcategories under "{_leaf}".

# EXISTING SUBCATEGORIES (choose from these):
# {subcats_text}

# You may also invent NEW subcategory names if a concept doesn't fit any existing one. Prefix new names with "[NEW]_".

# CONCEPTS TO PLACE:
# {concepts_text}

# Task: Assign EVERY concept to EXACTLY ONE subcategory (existing or new).

# Output strictly as a flat JSON dictionary mapping each concept to its subcategory name."""

#         results = _llm_route_batches(concepts_to_place, RESUBDIV_BATCH,
#                                      _prompt_slot, f"resubdiv_{leaf}")
#         for r in results:
#             parsed = r["parsed"]
#             for concept in r["batch"]:
#                 subcat_name = parsed.get(concept)
#                 if subcat_name:
#                     if subcat_name not in db:
#                         db[subcat_name] = _intermediary_node(leaf)
#                         created += 1
#                     db[concept]['taxonomy_parent'] = subcat_name

#     # Top-level domains (Computer_Science skips the AI/ML spine) (Port).
#     for domain in VALID_ROOTS:
#         if domain == "Computer_Science":
#             direct_children = [k for k, v in db.items()
#                                if v.get('taxonomy_parent') == domain
#                                and k not in ["Artificial_Intelligence"]
#                                and not v.get('is_skeleton')]
#         else:
#             direct_children = [k for k, v in db.items()
#                                if v.get('taxonomy_parent') == domain
#                                and not v.get('is_skeleton')]
#         promoted = [k for k in direct_children if db[k].get('is_promoted_target')]
#         originals = [k for k in direct_children
#                      if not db[k].get('is_promoted_target')
#                      and not db[k].get('is_intermediary')]
#         concepts_to_place = promoted + originals
#         if len(concepts_to_place) <= 5:
#             continue

#         def _prompt_domain(batch, _domain=domain):
#             concepts_text = "\n".join(f"- {c}" for c in batch)
#             return f"""You are an expert ontologist. The domain "{_domain}" has {len(batch)} concepts that need to be organized.

# Task:
# 1. Invent 3 to 5 NEW subcategory names for "{_domain}".
# 2. Assign EVERY concept to EXACTLY ONE subcategory.

# Concepts:
# {concepts_text}

# Output strictly as a flat JSON dictionary mapping each concept to its subcategory name."""

#         results = _llm_route_batches(concepts_to_place, len(concepts_to_place) or 1,
#                                      _prompt_domain, f"domain_subdiv_{domain}")
#         parsed = results[0]["parsed"] if results else {}
#         for concept, subcat_name in parsed.items():
#             if subcat_name not in db:
#                 db[subcat_name] = _intermediary_node(domain)
#                 created += 1
#             if concept in db:
#                 db[concept]['taxonomy_parent'] = subcat_name

#     print(f"   ✅ Created {created} new subcategories.")
#     return {"resubdivision_subcats_created": created}


# # ==========================================
# # OP 5 — refine overloaded >15-child nodes (onto_health_refinement)  [MUTATE]
# # ==========================================

# def op5_refine_overloaded(db: dict) -> dict:
#     print("\n🌳 OP5: refining overloaded nodes "
#           f"(>{MAX_CHILDREN_THRESHOLD} children)...")

#     children_map = _children_map(db)

#     # ---- Phase A: fix broken chains whose parent is missing from the DB (Port).
#     broken_chains = []
#     for key, data in db.items():
#         if key in VALID_ROOTS or data.get('is_noise'):
#             continue
#         parent = data.get('taxonomy_parent')
#         if (parent and parent != 'owl:Thing'
#                 and parent not in db and parent not in VALID_ROOTS):
#             broken_chains.append(key)

#     if broken_chains:
#         def _prompt_broken(batch):
#             concepts_text = "\n".join(f"- {c}" for c in batch)
#             return f"""These {len(batch)} concepts have missing parents. Assign each to a valid parent.
# Valid Parents: Computer_Science, Mathematics, Physics, Biology, Engineering, Artificial_Intelligence, Machine_Learning, ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation, ML_Objective_and_Constraint, ML_Workflow_and_Protocol, ML_Foundations_and_Theory, ML_Infrastructure_and_Environment, ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance.
# Concepts: {concepts_text}
# Output JSON mapping concept -> parent."""

#         results = _llm_route_batches(broken_chains, BROKEN_CHAIN_BATCH,
#                                      _prompt_broken, "onto_broken_chain")
#         for r in results:
#             if r["parsed"] == _FAILED_BATCH:
#                 continue   # left for a future pass; do NOT poison anything
#             parsed = r["parsed"]
#             for concept in r["batch"]:
#                 parent = parsed.get(concept)
#                 db[concept]['taxonomy_parent'] = parent if (parent and parent in db) else "ML_Model"

#     # ---- Phase B: refine overloaded nodes (> MAX_CHILDREN_THRESHOLD children).
#     children_map = _children_map(db)
#     overloaded = {node: kids for node, kids in children_map.items()
#                   if len(kids) > MAX_CHILDREN_THRESHOLD and node not in VALID_ROOTS}
#     print(f"   Found {len(overloaded)} overloaded nodes "
#           f"(>{MAX_CHILDREN_THRESHOLD} children).")

#     refined_subcats = 0
#     unresolved = []          # nodes still > threshold after this pass
#     total_leftover = 0       # children rescued by the deterministic sweep

#     for node, children in overloaded.items():

#         def _prompt_refine(batch, _node=node):
#             concepts_text = "\n".join(f"- {c}" for c in batch)
#             return f"""You are an expert ML ontologist. The category "{_node}" currently has {len(batch)} direct children, which makes the hierarchy too flat and messy.
# Task: Invent 3 to 5 NEW, mutually exclusive subcategory names to logically group these children.
# Assign EVERY child to EXACTLY ONE of your invented subcategories.

# Children to group:
# {concepts_text}

# Output strictly as a flat JSON dictionary mapping each child to its new subcategory name.
# Example: {{"child A": "Subcategory_1", "child B": "Subcategory_1", "child C": "Subcategory_2"}}"""

#         # Chunk the children so no single call must echo a huge list back.
#         results = _llm_route_batches(children, MAX_CHILDREN_THRESHOLD,
#                                      _prompt_refine, f"refine_{node}")

#         # Merge per-chunk assignments; chunks may invent their own bucket names
#         # (they simply become sibling subcategories — same as before).
#         parsed = {}
#         had_failure = False
#         for r in results:
#             if r["parsed"] == _FAILED_BATCH:
#                 had_failure = True
#                 continue
#             if isinstance(r["parsed"], dict):
#                 parsed.update(r["parsed"])

#         subcat_groups = defaultdict(list)
#         for child, subcat_name in parsed.items():
#             if child in children:
#                 subcat_groups[str(subcat_name)].append(child)

#         # --- Deterministic convergence sweep (NEW): every child MUST leave the
#         # overloaded node this pass, regardless of LLM omissions/truncation/
#         # failures. Anything unassigned goes into a deterministic "_Misc"
#         # bucket under the node. This is what makes OP5 converge instead of
#         # re-flagging the same node on every subsequent run.
#         assigned = {c for kids in subcat_groups.values() for c in kids}
#         leftover = [c for c in children if c not in assigned]
#         if leftover:
#             misc_name = f"{node}_Misc"
#             subcat_groups[misc_name].extend(leftover)
#             total_leftover += len(leftover)
#             tag = "LLM-failed chunk" if had_failure else "omitted by LLM"
#             print(f"      🧹 '{node}': swept {len(leftover)} unassigned "
#                   f"children ({tag}) into '{misc_name}'.")

#         for subcat_name, sub_children in subcat_groups.items():
#             if not sub_children:
#                 continue
#             if subcat_name not in db:
#                 db[subcat_name] = _intermediary_node(node, is_refined=True)
#                 refined_subcats += 1
#             elif db[subcat_name].get('taxonomy_parent') != node \
#                     and not db[subcat_name].get('is_skeleton'):
#                 # Bucket name already exists elsewhere; reparent it here so the
#                 # grouping stays coherent (data preserved, just relocated).
#                 db[subcat_name]['taxonomy_parent'] = node
#                 refined_subcats += 1
#             for child in sub_children:
#                 if child in db:
#                     db[child]['taxonomy_parent'] = subcat_name

#         # --- Post-refinement verification: did this node actually shrink?
#         remaining = sum(1 for k, v in db.items()
#                         if v.get('taxonomy_parent') == node and k != node)
#         if remaining > MAX_CHILDREN_THRESHOLD:
#             unresolved.append((node, remaining))

#     if total_leftover:
#         print(f"   🧹 Convergence sweep placed {total_leftover} unassigned "
#               f"child(ren) into '_Misc' buckets.")

#     if unresolved:
#         print(f"   ⚠️ {len(unresolved)} node(s) remain overloaded after OP5 "
#               f"(will be flagged again next pass):")
#         for n, rem in sorted(unresolved, key=lambda x: -x[1])[:10]:
#             print(f"      • {n}: {rem} children")

#     print(f"   ✅ Created {refined_subcats} subcategories under overloaded nodes.")
#     return {"overloaded_nodes": len(overloaded),
#             "refinement_subcats_created": refined_subcats,
#             "onto_broken_chains_fixed": len(broken_chains),
#             "refinement_leftover_swept": total_leftover,
#             "refinement_unresolved_nodes": len(unresolved)}


# # def op5_refine_overloaded(db: dict) -> dict:
# #     print("\n🌳 OP5: refining overloaded nodes (>15 children)...")

# #     children_map = _children_map(db)

# #     # Fix any remaining broken chains whose parent is missing from the DB (Port).
# #     broken_chains = []
# #     for key, data in db.items():
# #         if key in VALID_ROOTS or data.get('is_noise'):
# #             continue
# #         parent = data.get('taxonomy_parent')
# #         if (parent and parent != 'owl:Thing'
# #                 and parent not in db and parent not in VALID_ROOTS):
# #             broken_chains.append(key)

# #     if broken_chains:
# #         def _prompt_broken(batch):
# #             concepts_text = "\n".join(f"- {c}" for c in batch)
# #             return f"""These {len(batch)} concepts have missing parents. Assign each to a valid parent.
# # Valid Parents: Computer_Science, Mathematics, Physics, Biology, Engineering, Artificial_Intelligence, Machine_Learning, ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation, ML_Objective_and_Constraint, ML_Workflow_and_Protocol, ML_Foundations_and_Theory, ML_Infrastructure_and_Environment, ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance.
# # Concepts: {concepts_text}
# # Output JSON mapping concept -> parent."""

# #         results = _llm_route_batches(broken_chains, BROKEN_CHAIN_BATCH,
# #                                      _prompt_broken, "onto_broken_chain")
# #         for r in results:
# #             parsed = r["parsed"]
# #             for concept in r["batch"]:
# #                 parent = parsed.get(concept)
# #                 db[concept]['taxonomy_parent'] = parent if (parent and parent in db) else "ML_Model"

# #     # Refine overloaded nodes (> MAX_CHILDREN_THRESHOLD children) (Port).
# #     children_map = _children_map(db)
# #     overloaded = {node: kids for node, kids in children_map.items()
# #                   if len(kids) > MAX_CHILDREN_THRESHOLD and node not in VALID_ROOTS}
# #     print(f"   Found {len(overloaded)} overloaded nodes "
# #           f"(>{MAX_CHILDREN_THRESHOLD} children).")

# #     refined_subcats = 0
# #     for node, children in overloaded.items():
# #         def _prompt_refine(batch, _node=node):
# #             concepts_text = "\n".join(f"- {c}" for c in batch)
# #             return f"""You are an expert ML ontologist. The category "{_node}" currently has {len(batch)} direct children, which makes the hierarchy too flat and messy.
# # Task: Invent 3 to 5 NEW, mutually exclusive subcategory names to logically group these children.
# # Assign EVERY child to EXACTLY ONE of your invented subcategories.

# # Children to group:
# # {concepts_text}

# # Output strictly as a flat JSON dictionary mapping each child to its new subcategory name.
# # Example: {{"child A": "Subcategory_1", "child B": "Subcategory_1", "child C": "Subcategory_2"}}"""

# #         # Chunk the children so no single call must echo a huge list back (a
# #         # giant one-shot prompt is exactly what makes the model hang/time out).
# #         # Merge the per-chunk subcategory assignments (each chunk may invent its
# #         # own subcategory names; that is fine — they become sibling buckets).
# #         results = _llm_route_batches(children, MAX_CHILDREN_THRESHOLD,
# #                                      _prompt_refine, f"refine_{node}")
# #         parsed = {}
# #         for r in results:
# #             if isinstance(r["parsed"], dict):
# #                 parsed.update(r["parsed"])
# #         if not parsed:
# #             continue
# #         subcat_groups = defaultdict(list)
# #         for child, subcat_name in parsed.items():
# #             if child in children:
# #                 subcat_groups[subcat_name].append(child)
# #         for subcat_name, sub_children in subcat_groups.items():
# #             if subcat_name not in db:
# #                 db[subcat_name] = _intermediary_node(node, is_refined=True)
# #                 refined_subcats += 1
# #             for child in sub_children:
# #                 db[child]['taxonomy_parent'] = subcat_name

# #     print(f"   ✅ Created {refined_subcats} subcategories under overloaded nodes.")
# #     return {"overloaded_nodes": len(overloaded),
# #             "refinement_subcats_created": refined_subcats,
# #             "onto_broken_chains_fixed": len(broken_chains)}


# # ==========================================
# # OP 6 — fix hierarchy/URI collisions + enforce skeleton (fix_db_hierarchy) [MUTATE]
# #        Uses the shared C.get_uri_name so URIs cannot disagree with S11 (R6.2).
# # ==========================================
# def op6_fix_hierarchy(db: dict) -> dict:
#     print("\n🧩 OP6: fixing URI collisions & enforcing skeleton...")

#     # 1. Group keys by their URI slug to find collisions (shared C.get_uri_name).
#     uri_groups = defaultdict(list)
#     for key in db.keys():
#         uri_groups[C.get_uri_name(key)].append(key)

#     canonical_map = {}
#     keys_to_delete = []
#     for uri_name, keys in uri_groups.items():
#         if len(keys) == 1:
#             canonical_map[uri_name] = keys[0]
#             continue
#         # Prefer a skeleton node; else the one with the most data (Port).
#         best_key = None
#         for k in keys:
#             if k in CORRECT_SKELETON:
#                 best_key = k
#                 break
#         if not best_key:
#             best_key = max(keys, key=lambda k: db[k].get('f', 0) + len(db[k].get('props', {})))
#         canonical_map[uri_name] = best_key
#         for k in keys:
#             if k != best_key:
#                 print(f"   🔄 Merging URI collision: '{k}' -> '{best_key}'")
#                 keys_to_delete.append(k)
#                 # Merge preserves data into the survivor (annotations never lost).
#                 for ann in db[k].get('literal_annotations', []):
#                     if ann not in db[best_key].get('literal_annotations', []):
#                         db[best_key].setdefault('literal_annotations', []).append(ann)
#                 for prop, targets in db[k].get('props', {}).items():
#                     for target, tdata in targets.items():
#                         db[best_key].setdefault('props', {}).setdefault(prop, {})[target] = tdata

#     for key in keys_to_delete:
#         del db[key]

#     # 2. Fix parent references via the URI canonical map (Port).
#     for _key, data in db.items():
#         parent = data.get('taxonomy_parent')
#         if parent and parent != 'owl:Thing':
#             parent_uri = C.get_uri_name(parent)
#             if parent_uri in canonical_map:
#                 data['taxonomy_parent'] = canonical_map[parent_uri]

#     # 3. Enforce the skeleton hierarchy (Port + repair). Re-create any skeleton
#     #    node that a prior op deleted, so no concept can point at a missing
#     #    parent (which would orphan it from every top-level domain).
#     recreated = 0
#     for node, correct_parent in CORRECT_SKELETON.items():
#         if node not in db:
#             db[node] = _intermediary_node(correct_parent, is_skeleton=True)
#             recreated += 1
#         else:
#             db[node]['taxonomy_parent'] = correct_parent
#             db[node]['is_skeleton'] = True
#     if recreated:
#         print(f"   🦴 Re-created {recreated} missing skeleton node(s).")

#     # 4. Resolve owl:Thing orphans using a same-URI sibling with a real parent (Port).
#     for k, v in db.items():
#         if v.get('taxonomy_parent') == 'owl:Thing' and k not in CORRECT_SKELETON:
#             k_uri = C.get_uri_name(k)
#             for other_k, other_v in db.items():
#                 if (other_k != k and C.get_uri_name(other_k) == k_uri
#                         and other_v.get('taxonomy_parent') != 'owl:Thing'):
#                     v['taxonomy_parent'] = other_v['taxonomy_parent']
#                     print(f"   ✅ Fixed orphan '{k}' using parent from '{other_k}'")
#                     break

#     print(f"   ✅ Merged {len(keys_to_delete)} URI collisions; skeleton enforced.")
#     return {"uri_collisions_merged": len(keys_to_delete)}


# # ==========================================
# # OP 7 — structural redundancy audit (structural_redundancy_checker)  [READ-ONLY]
# # ==========================================
# def _normalize_name(name: str) -> str:
#     """Comparison slug for redundancy checks (Port — strip non-alnum, lower)."""
#     import re
#     return re.sub(r'[^a-z0-9]', '', str(name).lower())


# def op7_redundancy_audit(db: dict) -> dict:
#     print("\n🔍 OP7: structural redundancy audit (read-only)...")
#     issues = {
#         "exact_duplicates": [],
#         "semantic_duplicates": [],
#         "multi_level_repetitions": [],
#         "parent_child_name_conflicts": [],
#     }
#     children_map = _children_map(db)

#     # 1. Exact duplicate names under different parents.
#     name_to_locations = defaultdict(list)
#     for parent, children in children_map.items():
#         for child in children:
#             name_to_locations[_normalize_name(child)].append((child, parent))
#     for _norm, locations in name_to_locations.items():
#         if len(locations) > 1 and len({loc[1] for loc in locations}) > 1:
#             issues["exact_duplicates"].append({
#                 "concept": locations[0][0],
#                 "appears_under": [{"name": n, "parent": p} for n, p in locations],
#             })

#     # 2. Semantic duplicates (similar names under different parents).
#     all_concepts = list(db.keys())
#     checked_pairs = set()
#     for i, c1 in enumerate(all_concepts):
#         norm1 = _normalize_name(c1)
#         for j, c2 in enumerate(all_concepts):
#             if i >= j:
#                 continue
#             norm2 = _normalize_name(c2)
#             pair_key = tuple(sorted([norm1, norm2]))
#             if pair_key in checked_pairs:
#                 continue
#             checked_pairs.add(pair_key)
#             if len(norm1) < 5 or len(norm2) < 5:
#                 continue
#             similarity = SequenceMatcher(None, norm1, norm2).ratio()
#             if similarity > SEMANTIC_SIM_THRESHOLD and norm1 != norm2:
#                 p1 = db[c1].get('taxonomy_parent', 'unknown')
#                 p2 = db[c2].get('taxonomy_parent', 'unknown')
#                 if p1 != p2:
#                     issues["semantic_duplicates"].append({
#                         "concept1": c1, "concept2": c2,
#                         "similarity": round(similarity, 2),
#                         "parent1": p1, "parent2": p2,
#                     })

#     # 3. Multi-level repetitions (a grandchild also a direct child of the parent).
#     for parent, children in children_map.items():
#         child_set = set(children)
#         for child in children:
#             for grandchild in children_map.get(child, []):
#                 if grandchild in child_set:
#                     issues["multi_level_repetitions"].append({
#                         "parent": parent, "child": child,
#                         "grandchild_also_direct_child": grandchild,
#                     })

#     # 4. Parent-child name containment conflicts.
#     for parent, children in children_map.items():
#         norm_parent = _normalize_name(parent)
#         for child in children:
#             norm_child = _normalize_name(child)
#             if norm_parent in norm_child and len(norm_child) > len(norm_parent) + 3:
#                 issues["parent_child_name_conflicts"].append({
#                     "parent": parent, "child": child,
#                     "issue": "Child name contains parent name",
#                 })
#             elif norm_child in norm_parent and len(norm_parent) > len(norm_child) + 3:
#                 issues["parent_child_name_conflicts"].append({
#                     "parent": parent, "child": child,
#                     "issue": "Parent name contains child name",
#                 })

#     out = C.report_path("redundancy", __file__, ext="json")
#     C.save_json(out, issues)
#     counts = {k: len(v) for k, v in issues.items()}
#     print(f"   ✅ Redundancy audit -> {out}  {counts}")
#     return {"redundancy_report": str(out), "redundancy": counts, "_issues": issues}


# # ==========================================
# # OP 8 — node validation audit (llm_node_validator)  [READ-ONLY, LLM]
# #        Extend (R18.2): flags likely non-subsumption edges for repair/demotion.
# # ==========================================
# def op8_node_validation_audit(db: dict) -> dict:
#     print("\n🧠 OP8: node validation audit (read-only)...")
#     children_map = _children_map(db)
#     nodes_to_validate = [n for n in children_map.keys()
#                          if n not in SKIP_NODES and n in db]
#     print(f"   Validating {len(nodes_to_validate)} nodes...")

#     def _validate(node):
#         children = children_map[node]
#         if not children:
#             return {"has_issues": False}
#         children_text = "\n".join(f"- {c}" for c in children)
#         prompt = f"""You are an expert ML ontologist performing quality assurance on an ontology node.

# PARENT NODE: "{node}"

# CHILDREN (currently assigned as subclasses of the parent):
# {children_text}

# TASK: Analyze this parent-child relationship and identify any issues. Check for:

# 1. TAXONOMIC VALIDITY: Are the children truly subclasses of the parent? (e.g., "Image Segmentation" should NOT be a child of "ML_Algorithm"). Flag any child whose real relationship to the parent is part-of, used-by, or instance-of rather than genuine is-a subsumption.
# 2. CONCEPT VALIDITY: Are all children real, established ML/CS concepts? Flag any that look like noise, overly specific phrases, or non-concepts.
# 3. GROUPING NEED: If there are many children (>10), suggest if they should be grouped into subcategories.
# 4. RELEVANCE: Are all children relevant to a Machine Learning ontology? Flag any that belong to other domains.
# 5. NAMING ISSUES: Flag any children with poor naming (too long, sentence-like, unclear).

# Output strictly as JSON:
# {{
#   "has_issues": true/false,
#   "invalid_children": ["child1", "child2"],
#   "non_subsumption_children": ["child1"],
#   "needs_grouping": true/false,
#   "suggested_groups": ["Group1", "Group2"],
#   "drop_concepts": ["concept1"],
#   "naming_issues": {{"bad_name": "suggested_fix"}},
#   "other_issues": "description"
# }}
# """
#         try:
#             parsed = C.call_llm(prompt, cache_key=f"validate_{node}",
#                                 schema=C.safe_parse_json, stage=STAGE,
#                                 request_timeout=S09_TIMEOUT,
#                                 max_output_tokens=S09_MAX_TOKENS)
#         except C.QuotaExhausted:
#             raise
#         except (C.MalformedResponse, RuntimeError):
#             parsed = {}
#         return parsed if isinstance(parsed, dict) else {}

#     results = C.resumable_map(STAGE, nodes_to_validate, _validate,
#                               key=lambda n: f"validate_{n}")

#     all_issues = {}
#     for node, parsed in zip(nodes_to_validate, results):
#         if parsed and parsed.get("has_issues"):
#             all_issues[node] = parsed

#     # Extend (R18.2): re-surface S08's own non-subsumption flags in the audit so
#     # they are recorded for downstream repair/demotion even if the LLM missed them.
#     flagged_by_s08 = {c: d.get('non_subsumption_relation')
#                       for c, d in db.items() if d.get('non_subsumption_flag')}
#     if flagged_by_s08:
#         all_issues.setdefault("_s08_non_subsumption_flags", {}).update(flagged_by_s08)

#     out = C.report_path("validation", __file__, ext="json")
#     C.save_json(out, all_issues)
#     print(f"   ✅ Validation audit -> {out}  "
#           f"({len(nodes_to_validate)} nodes, {len(all_issues)} with issues)")
#     return {"validation_report": str(out),
#             "nodes_validated": len(nodes_to_validate),
#             "nodes_with_issues": len(all_issues),
#             "s08_non_subsumption_flags": len(flagged_by_s08),
#             "_issues": all_issues}


# # ==========================================
# # OP 9 — apply audit fixes (llm_issue_fixer)  [MUTATE]
# # ==========================================
# def _rename_concept(db, old_name, new_name):
#     if old_name not in db or new_name in db:
#         return
#     renamed = db.pop(old_name)
#     db[new_name] = renamed
#     for _k, v in db.items():
#         if v.get('taxonomy_parent') == old_name:
#             v['taxonomy_parent'] = new_name
#     # Guard: if the renamed node pointed at old_name (now new_name), it would be
#     # its own parent. Lift it to old_name's former parent instead (self-loop fix).
#     if renamed.get('taxonomy_parent') == new_name:
#         renamed['taxonomy_parent'] = 'owl:Thing'
#     print(f"      🔄 Renamed '{old_name}' -> '{new_name}'")


# def _merge_concepts(db, keep_name, discard_name):
#     if keep_name not in db or discard_name not in db:
#         return
#     # Never delete a structural anchor by merging it into something else — that
#     # would orphan every concept rooted through it (S12 orphan_ratio warning).
#     if _is_protected_skeleton(discard_name):
#         print(f"      🦴 refusing to merge skeleton/leaf anchor "
#               f"'{discard_name}' into '{keep_name}'.")
#         return
#     # If the survivor's own parent is the node being discarded, remember the
#     # discarded node's parent so the survivor doesn't end up pointing at itself.
#     discard_parent = db[discard_name].get('taxonomy_parent')
#     for ann in db[discard_name].get('literal_annotations', []):
#         if ann not in db[keep_name].get('literal_annotations', []):
#             db[keep_name].setdefault('literal_annotations', []).append(ann)
#     for prop, targets in db[discard_name].get('props', {}).items():
#         for target, tdata in targets.items():
#             db[keep_name].setdefault('props', {}).setdefault(prop, {})[target] = tdata
#     for _k, v in db.items():
#         if v.get('taxonomy_parent') == discard_name:
#             v['taxonomy_parent'] = keep_name
#     del db[discard_name]
#     # Guard: never let the survivor be its own parent (it was a child of the
#     # discarded node). Reattach it to the discarded node's former parent.
#     if db[keep_name].get('taxonomy_parent') == keep_name:
#         new_parent = discard_parent if discard_parent and discard_parent != keep_name else 'owl:Thing'
#         db[keep_name]['taxonomy_parent'] = new_parent
#     print(f"      🤝 Merged '{discard_name}' into '{keep_name}'")


# def op9_apply_audit_fixes(db: dict, red_issues: dict, val_issues: dict) -> dict:
#     print("\n🛠️ OP9: applying audit fixes...")
#     stats = {"exact_merges": 0, "semantic_merges": 0,
#              "dropped": 0, "renamed": 0, "reparented": 0, "grouped": 0}

#     # PHASE 1 — exact duplicates.
#     for dup in red_issues.get("exact_duplicates", []):
#         locations = dup.get("appears_under", [])
#         if len(locations) < 2:
#             continue
#         keep_name = locations[0]["name"]
#         for loc in locations[1:]:
#             before = len(db)
#             _merge_concepts(db, keep_name, loc["name"])
#             if len(db) < before:
#                 stats["exact_merges"] += 1

#     # PHASE 2 — semantic duplicates (LLM decides discard->keep per batch).
#     semantic_dups = red_issues.get("semantic_duplicates", [])
#     for i in range(0, len(semantic_dups), SEMANTIC_FIX_BATCH):
#         batch = semantic_dups[i:i + SEMANTIC_FIX_BATCH]
#         pairs_text = "\n".join(
#             f"{idx + 1}. '{d['concept1']}' vs '{d['concept2']}'"
#             for idx, d in enumerate(batch))
#         prompt = f"""You are an ontology expert. Below are pairs of highly similar concepts.
# For each pair, decide if they are true duplicates. If they are, output the concept to DISCARD as the key, and the concept to KEEP as the value.
# If they are distinct concepts, do not include them in the output.

# Pairs:
# {pairs_text}

# Output strictly as a flat JSON dictionary where Key = Concept to Discard, Value = Concept to Keep.
# Example: {{"concept_to_discard": "concept_to_keep"}}
# """
#         try:
#             decisions = C.call_llm(prompt, cache_key=f"semantic_fix_{i}",
#                                    schema=C.safe_parse_json, stage=STAGE,
#                                    request_timeout=S09_TIMEOUT,
#                                    max_output_tokens=S09_MAX_TOKENS)
#         except C.QuotaExhausted:
#             raise
#         except (C.MalformedResponse, RuntimeError):
#             decisions = {}
#         if isinstance(decisions, dict):
#             for discard, keep in decisions.items():
#                 discard = str(discard).strip().strip('"')
#                 keep = str(keep).strip().strip('"')
#                 if keep in db and discard in db:
#                     before = len(db)
#                     _merge_concepts(db, keep, discard)
#                     if len(db) < before:
#                         stats["semantic_merges"] += 1

#     # PHASE 3 — validation issues (skip the audit-only meta keys).
#     for node, issues in val_issues.items():
#         if node.startswith("_") or node not in db or not isinstance(issues, dict):
#             continue

#         # A. Drop concepts (R11.5 guard: never drop literal-annotation-only).
#         for drop_concept in issues.get("drop_concepts", []) or []:
#             if drop_concept in db and _mark_noise(db, drop_concept):
#                 stats["dropped"] += 1

#         # B. Naming fixes.
#         for bad_name, good_name in (issues.get("naming_issues", {}) or {}).items():
#             if bad_name in db and good_name not in db:
#                 _rename_concept(db, bad_name, good_name)
#                 stats["renamed"] += 1

#         # C. Invalid / non-subsumption children -> re-parent to a valid parent.
#         invalid_children = list(issues.get("invalid_children", []) or [])
#         for c in issues.get("non_subsumption_children", []) or []:
#             if c not in invalid_children:
#                 invalid_children.append(c)
#         if invalid_children:
#             children_text = "\n".join(f"- {c}" for c in invalid_children)
#             prompt = f"""These children are incorrectly placed under "{node}". Assign each to a valid parent.
# Valid Parents: Computer_Science, Mathematics, Physics, Biology, Engineering, Artificial_Intelligence, Machine_Learning, ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation, ML_Objective_and_Constraint, ML_Workflow_and_Protocol, ML_Foundations_and_Theory, ML_Infrastructure_and_Environment, ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance.
# Children: {children_text}
# Output JSON mapping child -> parent."""
#             try:
#                 new_parents = C.call_llm(prompt, cache_key=f"reparent_{node}",
#                                          schema=C.safe_parse_json, stage=STAGE,
#                                          request_timeout=S09_TIMEOUT,
#                                          max_output_tokens=S09_MAX_TOKENS)
#             except C.QuotaExhausted:
#                 raise
#             except (C.MalformedResponse, RuntimeError):
#                 new_parents = {}
#             if isinstance(new_parents, dict):
#                 for child in invalid_children:
#                     if child in db:
#                         db[child]['taxonomy_parent'] = new_parents.get(child, "ML_Model")
#                         stats["reparented"] += 1

#         # D. Grouping (create suggested subcategories).
#         if issues.get("needs_grouping") and issues.get("suggested_groups"):
#             children = [k for k, v in db.items() if v.get('taxonomy_parent') == node]
#             children_text = "\n".join(f"- {c}" for c in children)
#             groups_text = "\n".join(f"- {g}" for g in issues["suggested_groups"])
#             prompt = f"""Assign each child of "{node}" to one of these new subcategories.
# Subcategories: {groups_text}
# Children: {children_text}
# Output JSON mapping child -> subcategory."""
#             try:
#                 assignments = C.call_llm(prompt, cache_key=f"group_{node}",
#                                          schema=C.safe_parse_json, stage=STAGE,
#                                          request_timeout=S09_TIMEOUT,
#                                          max_output_tokens=S09_MAX_TOKENS)
#             except C.QuotaExhausted:
#                 raise
#             except (C.MalformedResponse, RuntimeError):
#                 assignments = {}
#             if isinstance(assignments, dict):
#                 for child, group in assignments.items():
#                     if child in db:
#                         if group not in db:
#                             db[group] = _intermediary_node(node)
#                         db[child]['taxonomy_parent'] = group
#                         stats["grouped"] += 1

#     print(f"   ✅ Applied audit fixes: {stats}")
#     return {f"applied_{k}": v for k, v in stats.items()}


# # ==========================================
# # PASS ORCHESTRATION (one pass, fixed order; raises QuotaExhausted to pause)
# # ==========================================
# def _qa_pass(db: dict) -> dict:
#     """Run the nine QA operations over ``db`` in memory, in the fixed R11.2 order.

#     Steps 1–6 and 9 mutate ``db``; steps 7–8 emit read-only audits to reports/.
#     Returns the merged manifest counts. Raises :class:`common.QuotaExhausted`
#     (propagated from the guarded LLM sub-steps) so :func:`run` can pause without
#     writing the primary artifact.
#     """
#     counts = {}
#     counts.update(op1_fix_broken_chains(db))          # 1  mutate
#     counts.update(op2_promote_orphan_targets(db))     # 2  mutate
#     counts.update(op3_rescue_floating(db))            # 3  mutate
#     counts.update(op4_resubdivide_promoted(db))       # 4  mutate

#     for st in ("refine_", "onto_broken_chain"):
#         n = _purge_failed_cache(st)

#     counts.update(op5_refine_overloaded(db))          # 5  mutate
#     counts.update(op6_fix_hierarchy(db))              # 6  mutate

#     red = op7_redundancy_audit(db)                    # 7  read-only audit
#     red_issues = red.pop("_issues")
#     counts.update(red)

#     val = op8_node_validation_audit(db)               # 8  read-only audit
#     val_issues = val.pop("_issues")
#     counts.update(val)

#     counts.update(op9_apply_audit_fixes(db, red_issues, val_issues))  # 9 mutate

#     counts["nodes_total"] = len(db)
#     counts["noise_marked_total"] = sum(1 for d in db.values() if d.get('is_noise'))
#     return counts


# def _break_subclass_cycles(db: dict) -> dict:
#     """Final guarantee: the taxonomy S09 emits is acyclic (R11/R18).

#     Detaches any node that is its own ancestor (self-loop or longer cycle) by
#     re-anchoring it to ``owl:Thing``, so no ``subClassOf`` cycle can reach S11/S12.
#     Returns counts for the manifest. Deterministic (iterates in dict order).
#     """
#     self_loops = 0
#     cycles_broken = 0
#     for node, data in db.items():
#         if not isinstance(data, dict):
#             continue
#         parent = data.get('taxonomy_parent')
#         if parent == node:                       # direct self-loop
#             data['taxonomy_parent'] = 'owl:Thing'
#             self_loops += 1
#             continue
#         # Walk the parent chain; if we return to `node`, we're in a cycle.
#         seen = set()
#         cur = parent
#         while cur and cur != 'owl:Thing' and cur in db:
#             if cur == node:                      # node is its own ancestor
#                 data['taxonomy_parent'] = 'owl:Thing'
#                 cycles_broken += 1
#                 break
#             if cur in seen:                      # cycle not involving `node`
#                 break
#             seen.add(cur)
#             cur = db[cur].get('taxonomy_parent')
#     if self_loops or cycles_broken:
#         print(f"   ✅ Cycle guard: reattached {self_loops} self-loop(s) and "
#               f"{cycles_broken} longer cycle member(s) to owl:Thing.")
#     else:
#         print("   ✅ Cycle guard: taxonomy already acyclic.")

#     # Root-reachability sweep: every non-skeleton node must reach a top-level
#     # domain via its parent chain. A node whose chain dies at owl:Thing or a
#     # missing parent (e.g. a bucket the cycle-guard just detached, or an
#     # intermediary whose parent was pruned) is re-anchored under Machine_Learning
#     # so its whole subtree reconnects to the roots (fixes S12 orphan_ratio).
#     roots = set(VALID_ROOTS)

#     def reaches_root(node):
#         seen = set()
#         cur = node
#         while cur and cur != 'owl:Thing':
#             if cur in roots:
#                 return True
#             if cur in seen or cur not in db:
#                 return False
#             seen.add(cur)
#             cur = db[cur].get('taxonomy_parent')
#         return False

#     reanchored = 0
#     fallback = "Machine_Learning" if "Machine_Learning" in db else next(iter(roots))
#     for node, data in db.items():
#         if not isinstance(data, dict) or node == "__meta__":
#             continue
#         if node in roots or data.get('is_skeleton'):
#             continue
#         if not reaches_root(node):
#             data['taxonomy_parent'] = fallback
#             reanchored += 1
#     if reanchored:
#         print(f"   🌱 Root sweep: re-anchored {reanchored} unreachable node(s) "
#               f"under '{fallback}'.")

#     return {"self_loops_fixed": self_loops, "cycles_broken": cycles_broken,
#             "reanchored_to_root": reanchored}


# def run() -> Path:
#     print("🚀 S09: running the nine-operation QA/repair pass (one pass, fixed order)...")

#     in_path = C.require_latest("s08_build_taxonomy", ext="json")
#     print(f"📂 Loading {in_path} ...")
#     db = C.load_json(in_path)   # in-memory copy; the input file is never mutated.

#     try:
#         counts = _qa_pass(db)
#     except C.QuotaExhausted as e:
#         # Paused, not failed: no primary artifact, caches left intact (R19.4/6).
#         print(f"[{STAGE}] paused — resume later (daily LLM quota exhausted). "
#               f"Progress is checkpointed in {C.CACHES / STAGE}; re-run this stage "
#               f"to continue where it left off. ({e})")
#         sys.exit(0)

#     # Final safety net: guarantee an acyclic taxonomy before promotion (R11/R18).
#     counts.update(_break_subclass_cycles(db))

#     # Promote-on-complete: only NOW write the ONE versioned primary artifact.
#     out_path = C.output_path(STAGE, __file__, ext="json")
#     C.save_json(out_path, db)
#     C.write_manifest(STAGE, __file__, in_path=in_path, out_path=out_path,
#                      counts=counts,
#                      extra={"redundancy_report": counts.get("redundancy_report"),
#                             "validation_report": counts.get("validation_report")})
#     print(f"[{STAGE}] QA pass complete -> {out_path}  "
#           f"(nodes={counts['nodes_total']}, "
#           f"noise={counts['noise_marked_total']})")
#     return out_path


# if __name__ == "__main__":
#     run()
"""
s09_qa_repair.py — Stage 9: taxonomy QA & repair (New: merge of 9 scripts).

Input : latest artifacts/s08_build_taxonomy/*.json  (the taxonomized property DB
        with a `taxonomy_parent` on every concept, injected skeleton /
        intermediary nodes, and S08's `non_subsumption_flag` markers).
Output: artifacts/s09_qa_repair/<RUN_ID>__<codehash>.json  (`s09_taxonomy_qa.json`
        — the same DB after nine QA operations run in memory in a fixed order).
        Never overwritten; promoted ONLY on completion.
        PLUS two READ-ONLY audits under reports/:
          reports/<RUN_ID>__<codehash>.redundancy.json
          reports/<RUN_ID>__<codehash>.validation.json
LLM   : yes (guarded via common.call_llm — deterministic, cached; resumable via
        common.resumable_map over each LLM sub-step's batches).

New build (R11): this ONE script REPLACES the nine in-place Gen-2 QA scripts that
each re-read and rewrote `data/taxonomized_ontology_db.json`. The nine scripts
live verbatim under ``stages/_s09_qa_sources/`` for reference. Here their
analytical logic is preserved but merged into a SINGLE non-mutating pass: S09
reads the latest S08 once, runs the nine operations against ONE in-memory DB in
the fixed dependency order below, and writes ONE new versioned artifact. It never
mutates its input and never loops internally — one pass per invocation; a re-run
produces a NEW versioned file (R11.1, R11.4).

Fixed order (R11.2 — the dependency order the nine scripts implied):
  1. fix broken parent chains        (routing_targets)               — mutate
  2. promote/route orphan targets    (assign_parents_to_targets)     — mutate
  3. rescue floating concepts        (rescue_floating_concepts)      — mutate
  4. resubdivide promoted targets    (resubdivide_promoted_targets)  — mutate
  5. refine overloaded >15 nodes     (onto_health_refinement)        — mutate
  6. fix hierarchy/URI collisions +  (fix_db_hierarchy, uses shared  — mutate
     enforce skeleton                 get_uri)
  7. structural redundancy audit     (structural_redundancy_checker) — READ-ONLY
       -> reports/<...>.redundancy.json
  8. node validation audit           (llm_node_validator)            — READ-ONLY
       -> reports/<...>.validation.json
  9. apply audit fixes               (llm_issue_fixer)               — mutate

Steps 1–6 and 9 mutate the in-memory DB; steps 7–8 emit read-only audits to
``reports/`` and are NOT the stage's primary artifact (R11.3).
"""

import os
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime


# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s09_qa_repair"

# Shared constants (from common — single source of truth, R6.1).
VALID_ROOTS = list(C.TOP_LEVEL_DOMAINS)          # the 5 foundational domains
ML_LEAVES = list(C.ML_LEAVES)                    # the 10 ML leaves

# The skeleton fix_db_hierarchy (step 6) enforces: the CS→AI→ML spine plus the
# ten ML leaves under Machine_Learning. Derived from the shared C.SKELETON so it
# can never drift from S08/S11.
CORRECT_SKELETON = {
    node: parent for node, parent in C.SKELETON.items()
    if node == "Computer_Science" or parent != "owl:Thing"
}

# Nodes to skip during node validation (step 8) — the fixed backbone.
SKIP_NODES = set(C.SKELETON.keys())

# Port thresholds / batch sizes (UNCHANGED from the source scripts).
CHAIN_FIX_BATCH = 30          # routing_targets
ORPHAN_BATCH = 30             # assign_parents_to_targets
RESCUE_BATCH = 15             # rescue_floating_concepts
RESUBDIV_BATCH = 15           # resubdivide_promoted_targets
BROKEN_CHAIN_BATCH = 5       # onto_health_refinement
MAX_CHILDREN_THRESHOLD = 5   # onto_health_refinement overloaded threshold
SEMANTIC_SIM_THRESHOLD = 0.85 # structural_redundancy_checker
SEMANTIC_FIX_BATCH = 10       # llm_issue_fixer semantic-duplicate batch

# Fail-fast per-call timeout + output cap for S09's LLM sub-steps.
S09_TIMEOUT = float(os.getenv("S09_TIMEOUT", "45"))
S09_MAX_TOKENS = int(os.getenv("S09_MAX_TOKENS", "2048"))

# ==========================================
# GARBAGE DETECTION — names AND content
# ==========================================
def _is_garbage_name(name: str) -> tuple[bool, str]:
    """Detect corrupted concept names."""
    import re
    if not name or not name.strip():
        return True, "empty_or_whitespace"
    stripped = name.strip()
    words = stripped.split()
    if len(words) >= 3 and len(set(w.lower() for w in words)) == 1:
        return True, f"repeated_word:_{words[0].lower()}_x{len(words)}"
    if re.match(r'^(.)\1{15,}$', stripped):
        return True, f"single_char_repeat:_{stripped[0]}"
    alpha_count = sum(1 for c in stripped if c.isalpha())
    if len(stripped) > 15 and alpha_count / len(stripped) < 0.4:
        return True, f"low_alpha_ratio:_{alpha_count/len(stripped):.2f}"
    if len(stripped) > 80 and ' ' not in stripped:
        return True, f"oversized_single_token:_{len(stripped)}_chars"
    if stripped.isdigit() and len(stripped) > 5:
        return True, f"pure_numeric:_{stripped}"
    return False, ""


def _is_garbage_data(data: dict) -> tuple[bool, str]:
    """Detect corrupted concept DATA (literal_annotations, props, etc.).

    Catches cases like 'causal inference' where the name is fine but the
    payload contains thousands of repetitions of a single word.
    """
    # Serialize everything to one string for analysis
    import json as _json
    blob = _json.dumps(data).lower()

    # Check for any word repeated an absurd number of times.
    # Threshold: a single word appearing >100 times in one concept's data
    # is almost always corruption (legitimate concepts rarely repeat a
    # word that much — even "the" in a long definition tops out ~20-30).
    import re
    from collections import Counter
    words = re.findall(r'[a-z]+', blob)
    if words:
        top_word, top_count = Counter(words).most_common(1)[0]
        if top_count > 100 and top_word not in {'the', 'of', 'and', 'in',
                                                 'to', 'a', 'for', 'is',
                                                 'that', 'are', 'with',
                                                 'as', 'by', 'on', 'an',
                                                 'or', 'from', 'be', 'this',
                                                 'which', 'at', 'its'}:
            return True, f"data_word_spam:_{top_word}_x{top_count}"

    # Total blob size sanity: a single concept's data shouldn't exceed 50KB
    if len(blob) > 50_000:
        return True, f"oversized_data:_{len(blob)}_chars"

    return False, ""


def _detect_and_log_bypassed(db: dict, reports_dir: Path,
                             run_tag: str) -> set[str]:
    """Scan *db* for garbage concept names AND corrupted data, log them,
    return the bypass set.  Source DB is **never mutated**."""
    import json as _json

    bypassed = {}
    for key, data in db.items():
        # Skip skeleton — never bypass structural anchors
        if key in CORRECT_SKELETON or key in VALID_ROOTS:
            continue

        reason = ""
        is_bad, reason = _is_garbage_name(key)
        if not is_bad:
            is_bad, reason = _is_garbage_data(data)
        if is_bad:
            bypassed[key] = {
                "reason": reason,
                "name_length": len(key),
                "parent": data.get("taxonomy_parent"),
                "is_intermediary": data.get("is_intermediary", False),
                "is_skeleton": data.get("is_skeleton", False),
                "prop_count": len(data.get("props", {})),
                "literal_ann_count": len(data.get("literal_annotations", [])),
            }

    bypass_set = set(bypassed.keys())

    log_path = reports_dir / f"{run_tag}.bypassed_concepts.json"
    reports_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(_json.dumps(bypassed, indent=2, ensure_ascii=False))

    if bypassed:
        by_reason: dict[str, list[str]] = {}
        for name, info in bypassed.items():
            by_reason.setdefault(info["reason"], []).append(name)
        print(f"\n🚫 BYPASS CHECK: {len(bypassed)} concept(s) bypassed "
              f"— logged to {log_path.name}")
        for reason, names in sorted(by_reason.items()):
            print(f"      • {reason}: {len(names)} concept(s)")
            for n in names[:3]:
                print(f"          – {n}")
            if len(names) > 3:
                print(f"          – …and {len(names)-3} more")
    else:
        print(f"\n✅ BYPASS CHECK: no garbage concepts  "
              f"(log: {log_path.name})")

    return bypass_set
# ==========================================
# SHARED HELPERS
# ==========================================
def _intermediary_node(parent_name: str, **flags) -> dict:
    """A fresh intermediary node body."""
    node = {
        'f': 0, 'td': 0, 'cov': 1.0, 'props': {},
        'literal_annotations': [], 'taxonomy_parent': parent_name,
        'is_intermediary': True,
    }
    node.update(flags)
    return node


def _is_literal_only(data: dict) -> bool:
    """R11.5 guard: a concept carrying literal_annotations but NO props.

    Such a concept holds demoted (grounded) knowledge that has nowhere else to
    live, so chain/ghost cleanup must never soft-delete it.
    """
    return bool(data.get('literal_annotations')) and not data.get('props')


def _is_protected_skeleton(concept: str) -> bool:
    """True for the CS→AI→ML spine, the 5 domains, and the 10 ML leaves.

    These structural anchors must never be deleted or merged away.
    """
    return (concept in CORRECT_SKELETON
            or concept in VALID_ROOTS
            or concept in ML_LEAVES)


def _mark_noise(db: dict, concept: str) -> bool:
    """Soft-delete ``concept`` (set is_noise) UNLESS it is literal-annotation-only.

    Returns True if the concept was marked, False if a guard protected it.
    """
    data = db.get(concept)
    if data is None:
        return False
    if _is_protected_skeleton(concept):
        print(f"      🦴 keeping skeleton/leaf anchor '{concept}' (never deleted).")
        return False
    if _is_literal_only(data):
        print(f"      🛡️ R11.5: keeping literal-annotation-only concept '{concept}' "
              f"(not deleting in cleanup).")
        return False
    data['is_noise'] = True
    return True


def _children_map(db: dict) -> dict:
    """parent -> [child, ...] for every non-owl:Thing edge."""
    cm = defaultdict(list)
    for key, data in db.items():
        parent = data.get('taxonomy_parent')
        if parent and parent != 'owl:Thing':
            cm[parent].append(key)
    return cm


# Sentinel stored in memory when an LLM batch ultimately fails.
_FAILED_BATCH = "__S09_FAILED_BATCH__"


def _purge_failed_cache(substep: str) -> int:
    """Delete cached checkpoints for ``substep`` that hold a poisoned empty result."""
    import json as _json
    purged = 0
    cache_dir = C.CACHES / STAGE
    if not cache_dir.exists():
        return 0
    for f in sorted(cache_dir.glob(f"{substep}_*.json")):
        try:
            val = _json.loads(f.read_text())
        except Exception:
            continue
        if val == {} or val == _FAILED_BATCH:
            f.unlink()
            purged += 1
    return purged


def _llm_route_batches(items, batch_size, prompt_builder, substep,
                       *, retry_failed=True):
    """Run an LLM routing sub-step over ``items`` in resumable batches."""
    batches = [(i // batch_size, items[i:i + batch_size])
               for i in range(0, len(items), batch_size)]

    def _fn(item):
        idx, batch = item
        prompt = prompt_builder(batch)
        try:
            parsed = C.call_llm(prompt, cache_key=f"{substep}_{idx}",
                                schema=C.safe_parse_json, stage=STAGE,
                                request_timeout=S09_TIMEOUT,
                                max_output_tokens=S09_MAX_TOKENS)
        except C.QuotaExhausted:
            raise
        except (C.MalformedResponse, RuntimeError):
            _purge_failed_cache(f"{substep}_{idx}")
            return {"batch": batch, "parsed": _FAILED_BATCH}
        if parsed == _FAILED_BATCH:
            _purge_failed_cache(f"{substep}_{idx}")
            return {"batch": batch, "parsed": _FAILED_BATCH}
        if not isinstance(parsed, dict):
            parsed = {}
        return {"batch": batch, "parsed": parsed}

    results = C.resumable_map(STAGE, batches, _fn,
                              key=lambda it: f"{substep}_{it[0]}")

    if retry_failed:
        failed = [it for r, it in zip(results, batches)
                  if r["parsed"] == _FAILED_BATCH]
        if failed:
            print(f"      ↻ retrying {len(failed)} failed "
                  f"'{substep}' batch(es) once more...")
            retried = C.resumable_map(STAGE, failed, _fn,
                                      key=lambda it: f"{substep}_{it[0]}")
            by_idx = {it[0]: r for it, r in zip(failed, retried)}
            results = [by_idx[it[0]] if r["parsed"] == _FAILED_BATCH else r
                       for r, it in zip(results, batches)]
    return results


# ==========================================
# OP 1 — fix broken parent chains (routing_targets)  [MUTATE]
# ==========================================
def op1_fix_broken_chains(db: dict, bypass: set[str]) -> dict:
    print("\n🔗 OP1: validating & fixing broken parent chains...")

    def is_chain_valid(node, visited=None):
        if visited is None:
            visited = set()
        if node in visited:
            return False            # cycle detected
        visited.add(node)
        if node in VALID_ROOTS:
            return True
        if node not in db:
            return False            # parent missing from DB
        parent = db[node].get('taxonomy_parent')
        if not parent or parent == 'owl:Thing':
            return False            # chain leads to owl:Thing prematurely
        return is_chain_valid(parent, visited)

    concepts_to_fix = []
    for key, data in db.items():
        if key in VALID_ROOTS:
            continue
        if key in bypass:                     
            continue
        if data.get('is_noise'):
            continue
        if not is_chain_valid(key):
            concepts_to_fix.append(key)

    print(f"   Found {len(concepts_to_fix)} concepts with broken parent chains.")
    if not concepts_to_fix:
        return {"broken_chains_fixed": 0}

    def _prompt(batch):
        concepts_text = "\n".join(f"- {c}" for c in batch)
        return f"""You are an expert ML ontologist. We have {len(batch)} concepts with broken hierarchy chains. You MUST assign each one to a valid parent from the list below.

VALID PARENTS (Choose ONLY from these):
Top-Level Domains:
- Computer_Science, Mathematics, Physics, Biology, Engineering

ML-Specific Categories:
- Artificial_Intelligence, Machine_Learning
- ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation
- ML_Objective_and_Constraint, ML_Workflow_and_Protocol
- ML_Foundations_and_Theory, ML_Infrastructure_and_Environment
- ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance

ROUTING RULES:
1. If it's a specific ML model (e.g., "Classification Model", "Neural Network"), assign to "ML_Model".
2. If it's a specific ML algorithm, assign to "ML_Algorithm".
3. If it's an ML task (e.g., "Image Segmentation"), assign to "ML_Task".
4. If it's pure Math/Physics/Biology, assign to that domain.
5. If it's a general CS concept, assign to "Computer_Science".

CONCEPTS TO FIX:
{concepts_text}

Output strictly as a flat JSON dictionary mapping each concept to its parent from the valid list above.
"""

    results = _llm_route_batches(concepts_to_fix, CHAIN_FIX_BATCH, _prompt, "chain_fix")
    fixed = 0
    for r in results:
        parsed = r["parsed"]
        for concept in r["batch"]:
            parent = parsed.get(concept)
            if not parent:
                cl = concept.lower()
                if 'model' in cl or 'network' in cl:
                    parent = "ML_Model"
                elif 'algorithm' in cl or 'optimization' in cl:
                    parent = "ML_Algorithm"
                elif 'task' in cl or 'segmentation' in cl:
                    parent = "ML_Task"
                else:
                    parent = "Computer_Science"
            db[concept]['taxonomy_parent'] = parent
            fixed += 1
    print(f"   ✅ Routed {fixed} concepts to valid parents.")
    return {"broken_chains_fixed": fixed}


# ==========================================
# OP 2 — promote/route orphan targets (assign_parents_to_targets)  [MUTATE]
# ==========================================
def op2_promote_orphan_targets(db: dict, bypass: set[str]) -> dict:
    print("\n📈 OP2: promoting & routing orphan targets...")

    orphan_targets = set()
    for data in db.values():
        for _prop, targets in data.get('props', {}).items():
            for target in targets.keys():
                if target not in db and not target in bypass:
                    orphan_targets.add(target)

    print(f"   Found {len(orphan_targets)} orphan targets.")
    if not orphan_targets:
        return {"orphan_targets_promoted": 0}

    orphan_list = list(orphan_targets)
    for target in orphan_list:
        if target not in db:
            db[target] = _intermediary_node('owl:Thing', is_intermediary=False,
                                            is_promoted_target=True)

    def _prompt(batch):
        import json as _json
        concepts_text = "\n".join(f"- {c}" for c in batch)
        return f"""You are an expert ML ontologist. We have {len(batch)} concepts that were extracted as targets from definitions. They need to be placed in our ontology hierarchy.

THE HIERARCHY STRUCTURE:
- Computer_Science -> Artificial_Intelligence -> Machine_Learning -> [10 ML Leaves]
- Mathematics (direct child of owl:Thing)
- Physics (direct child of owl:Thing)
- Biology (direct child of owl:Thing)
- Engineering (direct child of owl:Thing)

THE 10 ML LEAVES:
{_json.dumps(ML_LEAVES)}

ROUTING RULES:
1. If it's a core ML concept (model, algorithm, task, etc.), assign it to one of the 10 ML leaves.
2. If it's pure Math/Physics/Biology/Engineering, assign it to that top-level domain.
3. If it's an applied ML domain, assign it to "ML_Task" or "Computer_Science".
4. If it's a general CS concept, assign it to "Computer_Science".

Concepts to route:
{concepts_text}

Output strictly as a flat JSON dictionary mapping each concept to its parent.
"""

    results = _llm_route_batches(orphan_list, ORPHAN_BATCH, _prompt, "orphan")
    for r in results:
        parsed = r["parsed"]
        for concept in r["batch"]:
            parent = parsed.get(concept)
            db[concept]['taxonomy_parent'] = parent if parent else "ML_Model"
    print(f"   ✅ Promoted & routed {len(orphan_list)} orphan targets.")
    return {"orphan_targets_promoted": len(orphan_list)}


# ==========================================
# OP 3 — rescue floating concepts (rescue_floating_concepts)  [MUTATE]
# ==========================================
def op3_rescue_floating(db: dict, bypass: set[str]) -> dict:
    print("\n🏝️ OP3: rescuing concepts floating under owl:Thing...")

    floating = [k for k, v in db.items()
                if v.get('taxonomy_parent') == 'owl:Thing'
                and k not in VALID_ROOTS and not v.get('is_noise') and not k in bypass]
    print(f"   Found {len(floating)} floating concepts.")

    deleted = 0
    if floating:
        def _prompt(batch):
            import json as _json
            concepts_text = "\n".join(f"- {c}" for c in batch)
            return f"""You are an expert ontologist. We have {len(batch)} unassigned concepts. Route them to maintain a strict, scientifically accurate hierarchy.

THE 5 FOUNDATIONAL DOMAINS (Top-Level):
1. Computer_Science (Includes AI, Software, Algorithms)
2. Mathematics (Includes Calculus, Linear Algebra, Probability, Statistics, Optimization)
3. Physics (Includes Quantum Mechanics, Thermodynamics, Statistical Mechanics)
4. Biology (Includes Neuroscience, Genetics, Bioinformatics, Ecology)
5. Engineering (Includes Hardware, Robotics, Electrical Engineering, Materials Science)

ROUTING RULES:
- If the concept belongs to pure Math, Physics, Biology, or Engineering, assign it to that exact Top-Level Domain name (e.g., "Mathematics").
- If the concept is a core Machine Learning concept, assign it to one of these 10 ML leaves: {_json.dumps(ML_LEAVES)}.
- If the concept is an applied ML domain (e.g., Medical Imaging), assign it to "Computer_Science".
- If the concept is pure noise/garbage, assign it to "DELETE".

Concepts to route:
{concepts_text}

Output strictly as a flat JSON dictionary mapping each concept to its destination.
"""

        results = _llm_route_batches(floating, RESCUE_BATCH, _prompt, "rescue")
        for r in results:
            parsed = r["parsed"]
            for concept in r["batch"]:
                destination = parsed.get(concept)
                if not destination:
                    continue
                if destination == "DELETE":
                    if _mark_noise(db, concept):
                        deleted += 1
                elif destination in VALID_ROOTS or destination in ML_LEAVES:
                    db[concept]['taxonomy_parent'] = destination
                else:
                    db[concept]['taxonomy_parent'] = "Computer_Science"

    for domain in VALID_ROOTS:
        if domain not in db:
            db[domain] = _intermediary_node('owl:Thing', is_skeleton=True)
        else:
            db[domain]['taxonomy_parent'] = 'owl:Thing'
            db[domain]['is_skeleton'] = True

    print(f"   ✅ Rescued {len(floating)} floating concepts "
          f"({deleted} marked noise).")
    return {"floating_rescued": len(floating), "floating_marked_noise": deleted}


# ==========================================
# OP 4 — resubdivide promoted targets (resubdivide_promoted_targets)  [MUTATE]
# ==========================================
def op4_resubdivide_promoted(db: dict, bypass: set[str]) -> dict:
    print("\n📦 OP4: re-subdividing promoted targets into subcategories...")
    created = 0

    for leaf in ML_LEAVES:
        direct_children = [k for k, v in db.items()
                           if v.get('taxonomy_parent') == leaf
                           and not k in bypass]  # ← GUARD
        existing_subcats = [k for k in direct_children if db[k].get('is_intermediary')]
        promoted_targets = [k for k in direct_children if db[k].get('is_promoted_target')]
        original_concepts = [k for k in direct_children
                             if not db[k].get('is_intermediary')
                             and not db[k].get('is_promoted_target')]

        if not promoted_targets:
            continue

        if not existing_subcats:
            all_children = promoted_targets + original_concepts
            if len(all_children) <= 5:
                continue

            def _prompt_initial(batch, _leaf=leaf):
                concepts_text = "\n".join(f"- {c}" for c in batch)
                return f"""You are an expert ML ontologist. The category "{_leaf}" has {len(batch)} concepts that need to be organized into subcategories.

Task:
1. Invent 3 to 5 NEW, mutually exclusive subcategory names.
2. Assign EVERY concept to EXACTLY ONE subcategory.

Concepts:
{concepts_text}

Output strictly as a flat JSON dictionary mapping each concept to its subcategory name."""

            results = _llm_route_batches(all_children, len(all_children) or 1,
                                         _prompt_initial, f"initial_subdiv_{leaf}")
            parsed = results[0]["parsed"] if results else {}
            groups = defaultdict(list)
            for concept, subcat_name in parsed.items():
                groups[subcat_name].append(concept)
            for subcat_name, concepts in groups.items():
                if subcat_name not in db:
                    db[subcat_name] = _intermediary_node(leaf)
                    created += 1
                for c in concepts:
                    if c in db:
                        db[c]['taxonomy_parent'] = subcat_name
            continue

        concepts_to_place = promoted_targets + original_concepts
        if not concepts_to_place:
            continue

        def _prompt_slot(batch, _leaf=leaf, _subcats=tuple(existing_subcats)):
            concepts_text = "\n".join(f"- {c}" for c in batch)
            subcats_text = "\n".join(f"- {s}" for s in _subcats)
            return f"""You are an expert ML ontologist. We need to place {len(batch)} concepts into existing subcategories under "{_leaf}".

EXISTING SUBCATEGORIES (choose from these):
{subcats_text}

You may also invent NEW subcategory names if a concept doesn't fit any existing one. Prefix new names with "[NEW]_".

CONCEPTS TO PLACE:
{concepts_text}

Task: Assign EVERY concept to EXACTLY ONE subcategory (existing or new).

Output strictly as a flat JSON dictionary mapping each concept to its subcategory name."""

        results = _llm_route_batches(concepts_to_place, RESUBDIV_BATCH,
                                     _prompt_slot, f"resubdiv_{leaf}")
        for r in results:
            parsed = r["parsed"]
            for concept in r["batch"]:
                subcat_name = parsed.get(concept)
                if subcat_name:
                    if subcat_name not in db:
                        db[subcat_name] = _intermediary_node(leaf)
                        created += 1
                    db[concept]['taxonomy_parent'] = subcat_name

    for domain in VALID_ROOTS:
        if domain == "Computer_Science":
            direct_children = [k for k, v in db.items()
                               if v.get('taxonomy_parent') == domain
                               and k not in ["Artificial_Intelligence"]
                               and not v.get('is_skeleton') and not k in bypass]
        else:
            direct_children = [k for k, v in db.items()
                               if v.get('taxonomy_parent') == domain
                               and not v.get('is_skeleton') and not k in bypass] 
        promoted = [k for k in direct_children if db[k].get('is_promoted_target')]
        originals = [k for k in direct_children
                     if not db[k].get('is_promoted_target')
                     and not db[k].get('is_intermediary')]
        concepts_to_place = promoted + originals
        if len(concepts_to_place) <= 5:
            continue

        def _prompt_domain(batch, _domain=domain):
            concepts_text = "\n".join(f"- {c}" for c in batch)
            return f"""You are an expert ontologist. The domain "{_domain}" has {len(batch)} concepts that need to be organized.

Task:
1. Invent 3 to 5 NEW subcategory names for "{_domain}".
2. Assign EVERY concept to EXACTLY ONE subcategory.

Concepts:
{concepts_text}

Output strictly as a flat JSON dictionary mapping each concept to its subcategory name."""

        results = _llm_route_batches(concepts_to_place, len(concepts_to_place) or 1,
                                     _prompt_domain, f"domain_subdiv_{domain}")
        parsed = results[0]["parsed"] if results else {}
        for concept, subcat_name in parsed.items():
            if subcat_name not in db:
                db[subcat_name] = _intermediary_node(domain)
                created += 1
            if concept in db:
                db[concept]['taxonomy_parent'] = subcat_name

    print(f"   ✅ Created {created} new subcategories.")
    return {"resubdivision_subcats_created": created}


# ==========================================
# OP 5 — refine overloaded >15-child nodes (onto_health_refinement)  [MUTATE]
# ==========================================
def op5_refine_overloaded(db: dict, bypass: set[str]) -> dict:

    print("\n🌳 OP5: refining overloaded nodes "
          f"(>{MAX_CHILDREN_THRESHOLD} children)...")

    children_map = _children_map(db)

    broken_chains = []
    for key, data in db.items():
        if key in VALID_ROOTS or data.get('is_noise'):
            continue
        if key in bypass:                     
            continue
        parent = data.get('taxonomy_parent')
        if (parent and parent != 'owl:Thing'
                and parent not in db and parent not in VALID_ROOTS):
            broken_chains.append(key)

    if broken_chains:
        def _prompt_broken(batch):
            concepts_text = "\n".join(f"- {c}" for c in batch)
            return f"""These {len(batch)} concepts have missing parents. Assign each to a valid parent.
Valid Parents: Computer_Science, Mathematics, Physics, Biology, Engineering, Artificial_Intelligence, Machine_Learning, ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation, ML_Objective_and_Constraint, ML_Workflow_and_Protocol, ML_Foundations_and_Theory, ML_Infrastructure_and_Environment, ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance.
Concepts: {concepts_text}
Output JSON mapping concept -> parent."""

        results = _llm_route_batches(broken_chains, BROKEN_CHAIN_BATCH,
                                     _prompt_broken, "onto_broken_chain")
        for r in results:
            if r["parsed"] == _FAILED_BATCH:
                continue
            parsed = r["parsed"]
            for concept in r["batch"]:
                parent = parsed.get(concept)
                db[concept]['taxonomy_parent'] = parent if (parent and parent in db) else "ML_Model"

    children_map = _children_map(db)
    overloaded = {}
    for node, kids in children_map.items():
        filtered_kids = [k for k in kids if not k in bypass]  
        if len(filtered_kids) > MAX_CHILDREN_THRESHOLD and node not in VALID_ROOTS:
            overloaded[node] = filtered_kids
    print(f"   Found {len(overloaded)} overloaded nodes "
          f"(>{MAX_CHILDREN_THRESHOLD} children).")

    refined_subcats = 0
    unresolved = []
    total_leftover = 0

    for node, children in overloaded.items():

        def _prompt_refine(batch, _node=node):
            concepts_text = "\n".join(f"- {c}" for c in batch)
            return f"""You are an expert ML ontologist. The category "{_node}" currently has {len(batch)} direct children, which makes the hierarchy too flat and messy.
Task: Invent 3 to 5 NEW, mutually exclusive subcategory names to logically group these children.
Assign EVERY child to EXACTLY ONE of your invented subcategories.

Children to group:
{concepts_text}

Output strictly as a flat JSON dictionary mapping each child to its new subcategory name.
Example: {{"child A": "Subcategory_1", "child B": "Subcategory_1", "child C": "Subcategory_2"}}"""

        results = _llm_route_batches(children, MAX_CHILDREN_THRESHOLD,
                                     _prompt_refine, f"refine_{node}")

        parsed = {}
        had_failure = False
        for r in results:
            if r["parsed"] == _FAILED_BATCH:
                had_failure = True
                continue
            if isinstance(r["parsed"], dict):
                parsed.update(r["parsed"])

        subcat_groups = defaultdict(list)
        for child, subcat_name in parsed.items():
            if child in children:
                subcat_groups[str(subcat_name)].append(child)

        assigned = {c for kids in subcat_groups.values() for c in kids}
        leftover = [c for c in children if c not in assigned]
        if leftover:
            misc_name = f"{node}_Misc"
            subcat_groups[misc_name].extend(leftover)
            total_leftover += len(leftover)
            tag = "LLM-failed chunk" if had_failure else "omitted by LLM"
            print(f"      🧹 '{node}': swept {len(leftover)} unassigned "
                  f"children ({tag}) into '{misc_name}'.")

        for subcat_name, sub_children in subcat_groups.items():
            if not sub_children:
                continue
            if subcat_name not in db:
                db[subcat_name] = _intermediary_node(node, is_refined=True)
                refined_subcats += 1
            elif db[subcat_name].get('taxonomy_parent') != node \
                    and not db[subcat_name].get('is_skeleton'):
                db[subcat_name]['taxonomy_parent'] = node
                refined_subcats += 1
            for child in sub_children:
                if child in db:
                    db[child]['taxonomy_parent'] = subcat_name

        remaining = sum(1 for k, v in db.items()
                        if v.get('taxonomy_parent') == node and k != node)
        if remaining > MAX_CHILDREN_THRESHOLD:
            unresolved.append((node, remaining))

    if total_leftover:
        print(f"   🧹 Convergence sweep placed {total_leftover} unassigned "
              f"child(ren) into '_Misc' buckets.")

    if unresolved:
        print(f"   ⚠️ {len(unresolved)} node(s) remain overloaded after OP5 "
              f"(will be flagged again next pass):")
        for n, rem in sorted(unresolved, key=lambda x: -x[1])[:10]:
            print(f"      • {n}: {rem} children")

    print(f"   ✅ Created {refined_subcats} subcategories under overloaded nodes.")
    return {"overloaded_nodes": len(overloaded),
            "refinement_subcats_created": refined_subcats,
            "onto_broken_chains_fixed": len(broken_chains),
            "refinement_leftover_swept": total_leftover,
            "refinement_unresolved_nodes": len(unresolved)}


# ==========================================
# OP 6 — fix hierarchy/URI collisions + enforce skeleton (fix_db_hierarchy) [MUTATE]
# ==========================================
def op6_fix_hierarchy(db: dict, bypass: set[str]) -> dict:

    print("\n🧩 OP6: fixing URI collisions & enforcing skeleton...")

    uri_groups = defaultdict(list)
    for key in db.keys():
        if key in bypass:                 
            continue
        uri_groups[C.get_uri_name(key)].append(key)

    canonical_map = {}
    keys_to_delete = []
    keys_to_bypass_delete = []

    # Check if any bypassed key collides with a non-bypassed one
    for key in list(db.keys()):
        if not key in bypass:
            continue
        uri = C.get_uri_name(key)
        if uri in uri_groups:
            # Non-bypassed version exists — just drop the bypassed one
            keys_to_bypass_delete.append(key)

    for uri_name, keys in uri_groups.items():
        if len(keys) == 1:
            canonical_map[uri_name] = keys[0]
            continue
        best_key = None
        for k in keys:
            if k in CORRECT_SKELETON:
                best_key = k
                break
        if not best_key:
            best_key = max(keys, key=lambda k: db[k].get('f', 0) + len(db[k].get('props', {})))
        canonical_map[uri_name] = best_key
        for k in keys:
            if k != best_key:
                print(f"   🔄 Merging URI collision: '{k}' -> '{best_key}'")
                keys_to_delete.append(k)
                for ann in db[k].get('literal_annotations', []):
                    if ann not in db[best_key].get('literal_annotations', []):
                        db[best_key].setdefault('literal_annotations', []).append(ann)
                for prop, targets in db[k].get('props', {}).items():
                    for target, tdata in targets.items():
                        db[best_key].setdefault('props', {}).setdefault(prop, {})[target] = tdata

    for key in keys_to_delete:
        del db[key]
        
    for key in keys_to_bypass_delete:
        del db[key]    

    for _key, data in db.items():
        parent = data.get('taxonomy_parent')
        if parent and parent != 'owl:Thing':
            parent_uri = C.get_uri_name(parent)
            if parent_uri in canonical_map:
                data['taxonomy_parent'] = canonical_map[parent_uri]

    recreated = 0
    for node, correct_parent in CORRECT_SKELETON.items():
        if node not in db:
            db[node] = _intermediary_node(correct_parent, is_skeleton=True)
            recreated += 1
        else:
            db[node]['taxonomy_parent'] = correct_parent
            db[node]['is_skeleton'] = True
    if recreated:
        print(f"   🦴 Re-created {recreated} missing skeleton node(s).")

    for k, v in db.items():
        if v.get('taxonomy_parent') == 'owl:Thing' and k not in CORRECT_SKELETON:
            k_uri = C.get_uri_name(k)
            for other_k, other_v in db.items():
                if (other_k != k and C.get_uri_name(other_k) == k_uri
                        and other_v.get('taxonomy_parent') != 'owl:Thing'):
                    v['taxonomy_parent'] = other_v['taxonomy_parent']
                    print(f"   ✅ Fixed orphan '{k}' using parent from '{other_k}'")
                    break

    print(f"   ✅ Merged {len(keys_to_delete)} URI collisions; skeleton enforced.")
    return {"uri_collisions_merged": len(keys_to_delete)}


# ==========================================
# OP 7 — structural redundancy audit (structural_redundancy_checker)  [READ-ONLY]
# ==========================================
def _normalize_name(name: str) -> str:
    """Comparison slug for redundancy checks."""
    import re
    return re.sub(r'[^a-z0-9]', '', str(name).lower())


def op7_redundancy_audit(db: dict, bypass: set[str]) -> dict:
    print("\n🔍 OP7: structural redundancy audit (read-only)...")
    issues = {
        "exact_duplicates": [],
        "semantic_duplicates": [],
        "multi_level_repetitions": [],
        "parent_child_name_conflicts": [],
    }
    children_map = _children_map(db)

    name_to_locations = defaultdict(list)
    for parent, children in children_map.items():
        for child in children:
            if child in bypass:              
                continue
            name_to_locations[_normalize_name(child)].append((child, parent))
    for _norm, locations in name_to_locations.items():
        if len(locations) > 1 and len({loc[1] for loc in locations}) > 1:
            issues["exact_duplicates"].append({
                "concept": locations[0][0],
                "appears_under": [{"name": n, "parent": p} for n, p in locations],
            })

    all_concepts = [k for k in db.keys() if not k in bypass]
    checked_pairs = set()
    for i, c1 in enumerate(all_concepts):
        norm1 = _normalize_name(c1)
        for j, c2 in enumerate(all_concepts):
            if i >= j:
                continue
            norm2 = _normalize_name(c2)
            pair_key = tuple(sorted([norm1, norm2]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            if len(norm1) < 5 or len(norm2) < 5:
                continue
            similarity = SequenceMatcher(None, norm1, norm2).ratio()
            if similarity > SEMANTIC_SIM_THRESHOLD and norm1 != norm2:
                p1 = db[c1].get('taxonomy_parent', 'unknown')
                p2 = db[c2].get('taxonomy_parent', 'unknown')
                if p1 != p2:
                    issues["semantic_duplicates"].append({
                        "concept1": c1, "concept2": c2,
                        "similarity": round(similarity, 2),
                        "parent1": p1, "parent2": p2,
                    })

    for parent, children in children_map.items():
        
        child_set = set(children)
        for child in children:
            if child in bypass:             
                continue
            for grandchild in children_map.get(child, []):
                if grandchild in child_set:
                    issues["multi_level_repetitions"].append({
                        "parent": parent, "child": child,
                        "grandchild_also_direct_child": grandchild,
                    })

    for parent, children in children_map.items():
        norm_parent = _normalize_name(parent)
        for child in children:
            if child in bypass:               
                continue
            norm_child = _normalize_name(child)
            if norm_parent in norm_child and len(norm_child) > len(norm_parent) + 3:
                issues["parent_child_name_conflicts"].append({
                    "parent": parent, "child": child,
                    "issue": "Child name contains parent name",
                })
            elif norm_child in norm_parent and len(norm_parent) > len(norm_child) + 3:
                issues["parent_child_name_conflicts"].append({
                    "parent": parent, "child": child,
                    "issue": "Parent name contains child name",
                })

    out = C.report_path("redundancy", __file__, ext="json")
    C.save_json(out, issues)
    counts = {k: len(v) for k, v in issues.items()}
    print(f"   ✅ Redundancy audit -> {out}  {counts}")
    return {"redundancy_report": str(out), "redundancy": counts, "_issues": issues}


# ==========================================
# OP 8 — node validation audit (llm_node_validator)  [READ-ONLY, LLM]
# ==========================================
def op8_node_validation_audit(db: dict, bypass: set[str],
                        reports_dir: Path, run_tag: str) -> dict:
    print("\n🧠 OP8: node validation audit (read-only)...")
    children_map = _children_map(db)
    nodes_to_validate = [k for k in db.keys()
                         if k not in SKIP_NODES
                         and not k in bypass] 
    print(f"   Validating {len(nodes_to_validate)} nodes...")

    def _validate(node):
        children = children_map[node]
        if not children:
            return {"has_issues": False}
        children_text = "\n".join(f"- {c}" for c in children)
        prompt = f"""You are an expert ML ontologist performing quality assurance on an ontology node.

PARENT NODE: "{node}"

CHILDREN (currently assigned as subclasses of the parent):
{children_text}

TASK: Analyze this parent-child relationship and identify any issues. Check for:

1. TAXONOMIC VALIDITY: Are the children truly subclasses of the parent? (e.g., "Image Segmentation" should NOT be a child of "ML_Algorithm"). Flag any child whose real relationship to the parent is part-of, used-by, or instance-of rather than genuine is-a subsumption.
2. CONCEPT VALIDITY: Are all children real, established ML/CS concepts? Flag any that look like noise, overly specific phrases, or non-concepts.
3. GROUPING NEED: If there are many children (>10), suggest if they should be grouped into subcategories.
4. RELEVANCE: Are all children relevant to a Machine Learning ontology? Flag any that belong to other domains.
5. NAMING ISSUES: Flag any children with poor naming (too long, sentence-like, unclear).

Output strictly as JSON:
{{
  "has_issues": true/false,
  "invalid_children": ["child1", "child2"],
  "non_subsumption_children": ["child1"],
  "needs_grouping": true/false,
  "suggested_groups": ["Group1", "Group2"],
  "drop_concepts": ["concept1"],
  "naming_issues": {{"bad_name": "suggested_fix"}},
  "other_issues": "description"
}}
"""
        try:
            parsed = C.call_llm(prompt, cache_key=f"validate_{node}",
                                schema=C.safe_parse_json, stage=STAGE,
                                request_timeout=S09_TIMEOUT,
                                max_output_tokens=S09_MAX_TOKENS)
        except C.QuotaExhausted:
            raise
        except (C.MalformedResponse, RuntimeError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    results = C.resumable_map(STAGE, nodes_to_validate, _validate,
                              key=lambda n: f"validate_{n}")

    all_issues = {}
    for node, parsed in zip(nodes_to_validate, results):
        if parsed and parsed.get("has_issues"):
            all_issues[node] = parsed

    flagged_by_s08 = {c: d.get('non_subsumption_relation')
                      for c, d in db.items() if d.get('non_subsumption_flag')}
    if flagged_by_s08:
        all_issues.setdefault("_s08_non_subsumption_flags", {}).update(flagged_by_s08)

    out = C.report_path("validation", __file__, ext="json")
    C.save_json(out, all_issues)
    print(f"   ✅ Validation audit -> {out}  "
          f"({len(nodes_to_validate)} nodes, {len(all_issues)} with issues)")
    return {"validation_report": str(out),
            "nodes_validated": len(nodes_to_validate),
            "nodes_with_issues": len(all_issues),
            "s08_non_subsumption_flags": len(flagged_by_s08),
            "_issues": all_issues}


# ==========================================
# OP 9 — apply audit fixes (llm_issue_fixer)  [MUTATE]
# ==========================================
def _rename_concept(db, old_name, new_name):
    if old_name not in db or new_name in db:
        return
    renamed = db.pop(old_name)
    db[new_name] = renamed
    for _k, v in db.items():
        if v.get('taxonomy_parent') == old_name:
            v['taxonomy_parent'] = new_name
    if renamed.get('taxonomy_parent') == new_name:
        renamed['taxonomy_parent'] = 'owl:Thing'
    print(f"      🔄 Renamed '{old_name}' -> '{new_name}'")


def _merge_concepts(db, keep_name, discard_name):
    if keep_name not in db or discard_name not in db:
        return
    if _is_protected_skeleton(discard_name):
        print(f"      🦴 refusing to merge skeleton/leaf anchor "
              f"'{discard_name}' into '{keep_name}'.")
        return
    discard_parent = db[discard_name].get('taxonomy_parent')
    for ann in db[discard_name].get('literal_annotations', []):
        if ann not in db[keep_name].get('literal_annotations', []):
            db[keep_name].setdefault('literal_annotations', []).append(ann)
    for prop, targets in db[discard_name].get('props', {}).items():
        for target, tdata in targets.items():
            db[keep_name].setdefault('props', {}).setdefault(prop, {})[target] = tdata
    for _k, v in db.items():
        if v.get('taxonomy_parent') == discard_name:
            v['taxonomy_parent'] = keep_name
    del db[discard_name]
    if db[keep_name].get('taxonomy_parent') == keep_name:
        new_parent = discard_parent if discard_parent and discard_parent != keep_name else 'owl:Thing'
        db[keep_name]['taxonomy_parent'] = new_parent
    print(f"      🤝 Merged '{discard_name}' into '{keep_name}'")


def op9_apply_audit_fixes(db: dict, red_issues: dict, val_issues: dict,
                          bypass: set[str]) -> dict:
    print("\n🛠️ OP9: applying audit fixes...")
    stats = {"exact_merges": 0, "semantic_merges": 0,
             "dropped": 0, "renamed": 0, "reparented": 0, "grouped": 0}

    # --- Exact duplicates ---
    for dup in red_issues.get("exact_duplicates", []):
        locations = dup.get("appears_under", [])
        if len(locations) < 2:
            continue
        keep_name = locations[0]["name"]
        if keep_name in bypass:          # ← GUARD
            continue
        for loc in locations[1:]:
            if loc["name"] in bypass:    # ← GUARD
                continue
            before = len(db)
            _merge_concepts(db, keep_name, loc["name"])
            if len(db) < before:
                stats["exact_merges"] += 1

    # --- Semantic duplicates ---
    semantic_dups = [
        d for d in red_issues.get("semantic_duplicates", [])
        if not d["concept1"] in bypass   # ← GUARD
        and not d["concept2"] in bypass
    ]
    for i in range(0, len(semantic_dups), SEMANTIC_FIX_BATCH):
        batch = semantic_dups[i:i + SEMANTIC_FIX_BATCH]
        if not batch:
            continue
        pairs_text = "\n".join(
            f"{idx + 1}. '{d['concept1']}' vs '{d['concept2']}'"
            for idx, d in enumerate(batch))
        prompt = f"""You are an ontology expert. Below are pairs of highly similar concepts.
For each pair, decide if they are true duplicates. If they are, output the concept to DISCARD as the key, and the concept to KEEP as the value.
If they are distinct concepts, do not include them in the output.

Pairs:
{pairs_text}

Output strictly as a flat JSON dictionary where Key = Concept to Discard, Value = Concept to Keep.
Example: {{"concept_to_discard": "concept_to_keep"}}
"""
        try:
            decisions = C.call_llm(prompt, cache_key=f"semantic_fix_{i}",
                                   schema=C.safe_parse_json, stage=STAGE,
                                   request_timeout=S09_TIMEOUT,
                                   max_output_tokens=S09_MAX_TOKENS)
        except C.QuotaExhausted:
            raise
        except (C.MalformedResponse, RuntimeError):
            decisions = {}
        if isinstance(decisions, dict):
            for discard, keep in decisions.items():
                discard = str(discard).strip().strip('"')
                keep = str(keep).strip().strip('"')
                if discard in bypass:     # ← GUARD
                    continue
                if keep in bypass:        # ← GUARD
                    continue
                if keep in db and discard in db:
                    before = len(db)
                    _merge_concepts(db, keep, discard)
                    if len(db) < before:
                        stats["semantic_merges"] += 1

    # --- Validation issues per node ---
    for node, issues in val_issues.items():
        if node.startswith("_") or node not in db or not isinstance(issues, dict):
            continue
        if node in bypass:                # ← GUARD
            continue

        for drop_concept in issues.get("drop_concepts", []) or []:
            if drop_concept in bypass:    # ← GUARD
                continue
            if drop_concept in db and _mark_noise(db, drop_concept):
                stats["dropped"] += 1

        for bad_name, good_name in (issues.get("naming_issues", {}) or {}).items():
            if bad_name in bypass:        # ← GUARD
                continue
            if good_name in bypass:       # ← GUARD
                continue
            if bad_name in db and good_name not in db:
                _rename_concept(db, bad_name, good_name)
                stats["renamed"] += 1

        invalid_children = [c for c in (issues.get("invalid_children", []) or [])
                            if not c in bypass]          # ← GUARD
        for c in issues.get("non_subsumption_children", []) or []:
            if c not in invalid_children and not c in bypass:  # ← GUARD
                invalid_children.append(c)
        if invalid_children:
            children_text = "\n".join(f"- {c}" for c in invalid_children)
            prompt = f"""These children are incorrectly placed under "{node}". Assign each to a valid parent.
Valid Parents: Computer_Science, Mathematics, Physics, Biology, Engineering, Artificial_Intelligence, Machine_Learning, ML_Task, ML_Model, ML_Algorithm, ML_Data_and_Representation, ML_Objective_and_Constraint, ML_Workflow_and_Protocol, ML_Foundations_and_Theory, ML_Infrastructure_and_Environment, ML_Property_and_Quality_Attribute, ML_Methodology_and_Science_Provenance.
Children: {children_text}
Output JSON mapping child -> parent."""
            try:
                new_parents = C.call_llm(prompt, cache_key=f"reparent_{node}",
                                         schema=C.safe_parse_json, stage=STAGE,
                                         request_timeout=S09_TIMEOUT,
                                         max_output_tokens=S09_MAX_TOKENS)
            except C.QuotaExhausted:
                raise
            except (C.MalformedResponse, RuntimeError):
                new_parents = {}
            if isinstance(new_parents, dict):
                for child in invalid_children:
                    if child in db:
                        db[child]['taxonomy_parent'] = new_parents.get(child, "ML_Model")
                        stats["reparented"] += 1

        if issues.get("needs_grouping") and issues.get("suggested_groups"):
            children = [k for k, v in db.items()
                        if v.get('taxonomy_parent') == node
                        and not k in bypass]             # ← GUARD
            if not children:
                continue
            children_text = "\n".join(f"- {c}" for c in children)
            groups_text = "\n".join(f"- {g}" for g in issues["suggested_groups"])
            prompt = f"""Assign each child of "{node}" to one of these new subcategories.
Subcategories: {groups_text}
Children: {children_text}
Output JSON mapping child -> subcategory."""
            try:
                assignments = C.call_llm(prompt, cache_key=f"group_{node}",
                                         schema=C.safe_parse_json, stage=STAGE,
                                         request_timeout=S09_TIMEOUT,
                                         max_output_tokens=S09_MAX_TOKENS)
            except C.QuotaExhausted:
                raise
            except (C.MalformedResponse, RuntimeError):
                assignments = {}
            if isinstance(assignments, dict):
                for child, group in assignments.items():
                    if child in bypass:     # ← GUARD
                        continue
                    if child in db:
                        if group not in db:
                            db[group] = _intermediary_node(node)
                        db[child]['taxonomy_parent'] = group
                        stats["grouped"] += 1

    print(f"   ✅ Applied audit fixes: {stats}")
    return {f"applied_{k}": v for k, v in stats.items()}

# ==========================================
# PASS ORCHESTRATION
# ==========================================
def _qa_pass(db: dict, bypass: set[str], reports_dir: Path,
             run_tag: str) -> dict:
    """Run the nine QA operations once, preserving audit/fix data flow."""
    counts = {}
    counts.update(op1_fix_broken_chains(db, bypass))          # 1  mutate
    counts.update(op2_promote_orphan_targets(db, bypass))     # 2  mutate
    counts.update(op3_rescue_floating(db, bypass))            # 3  mutate
    counts.update(op4_resubdivide_promoted(db, bypass))       # 4  mutate

    for cache_prefix in ("refine_", "onto_broken_chain"):
        _purge_failed_cache(cache_prefix)

    counts.update(op5_refine_overloaded(db, bypass))          # 5  mutate
    counts.update(op6_fix_hierarchy(db, bypass))              # 6  mutate

    # The audit functions return report metadata plus a private in-memory issue
    # payload. Only the nested payload belongs in OP9; passing the wrappers makes
    # every OP9 lookup miss and silently turns the repair operation into a no-op.
    red = op7_redundancy_audit(db, bypass)                    # 7  read-only
    red_issues = red.pop("_issues")
    counts.update(red)

    val = op8_node_validation_audit(db, bypass, reports_dir, run_tag)  # 8
    val_issues = val.pop("_issues")
    counts.update(val)

    counts.update(op9_apply_audit_fixes(
        db, red_issues, val_issues, bypass))                  # 9  mutate

    counts["nodes_total"] = sum(
        1 for key, value in db.items()
        if key != "__meta__" and isinstance(value, dict))
    counts["noise_marked_total"] = sum(
        1 for value in db.values()
        if isinstance(value, dict) and value.get("is_noise"))
    counts["bypassed_total"] = len(bypass)
    return counts


def _break_subclass_cycles(db: dict) -> dict:
    """Final guarantee: the taxonomy S09 emits is acyclic."""
    self_loops = 0
    cycles_broken = 0
    for node, data in db.items():
        if not isinstance(data, dict):
            continue
        parent = data.get('taxonomy_parent')
        if parent == node:
            data['taxonomy_parent'] = 'owl:Thing'
            self_loops += 1
            continue
        seen = set()
        cur = parent
        while cur and cur != 'owl:Thing' and cur in db:
            if cur == node:
                data['taxonomy_parent'] = 'owl:Thing'
                cycles_broken += 1
                break
            if cur in seen:
                break
            seen.add(cur)
            cur = db[cur].get('taxonomy_parent')
    if self_loops or cycles_broken:
        print(f"   ✅ Cycle guard: reattached {self_loops} self-loop(s) and "
              f"{cycles_broken} longer cycle member(s) to owl:Thing.")
    else:
        print("   ✅ Cycle guard: taxonomy already acyclic.")

    roots = set(VALID_ROOTS)

    def reaches_root(node):
        seen = set()
        cur = node
        while cur and cur != 'owl:Thing':
            if cur in roots:
                return True
            if cur in seen or cur not in db:
                return False
            seen.add(cur)
            cur = db[cur].get('taxonomy_parent')
        return False

    reanchored = 0
    fallback = "Machine_Learning" if "Machine_Learning" in db else next(iter(roots))
    for node, data in db.items():
        if not isinstance(data, dict) or node == "__meta__":
            continue
        if (node in roots or data.get('is_skeleton')
                or data.get("qa_bypassed")):
            continue
        if not reaches_root(node):
            data['taxonomy_parent'] = fallback
            reanchored += 1
    if reanchored:
        print(f"   🌱 Root sweep: re-anchored {reanchored} unreachable node(s) "
              f"under '{fallback}'.")

    return {"self_loops_fixed": self_loops, "cycles_broken": cycles_broken,
            "reanchored_to_root": reanchored}


def run() -> Path:
    """Execute one complete QA pass and promote exactly one S09 artifact."""
    print("🚀 S09: running the nine-operation QA/repair pass "
          "(one pass, fixed order)...")

    in_path = C.require_latest("s08_build_taxonomy", ext="json")
    print(f"📂 Loading {in_path} ...")
    db = C.load_json(in_path)

    run_tag = f"{C.RUN_ID}__{C.code_hash(__file__)}"
    # Bypass diagnostics are operational logs, not the two scholarly read-only
    # audits. Keep them beside the manifest rather than under reports/.
    bypass_dir = Path(C.MANIFEST).parent / "bypass"
    bypass = _detect_and_log_bypassed(db, bypass_dir, run_tag)
    bypass_report = bypass_dir / f"{run_tag}.bypassed_concepts.json"

    # Persist only the exclusion marker. The original concept payload is kept,
    # while downstream S09a can avoid spending tokens on known-corrupt records.
    for concept in bypass:
        if isinstance(db.get(concept), dict):
            db[concept]["qa_bypassed"] = True

    try:
        counts = _qa_pass(db, bypass, C.REPORTS, run_tag)
    except C.QuotaExhausted as exc:
        print(f"[{STAGE}] paused — resume later (daily LLM quota exhausted). "
              f"Progress is checkpointed in {C.CACHES / STAGE}; re-run this "
              f"stage to continue where it left off. ({exc})")
        sys.exit(0)

    counts.update(_break_subclass_cycles(db))

    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, db)
    C.write_manifest(
        STAGE, __file__, in_path=in_path, out_path=out_path, counts=counts,
        extra={
            "redundancy_report": counts.get("redundancy_report"),
            "validation_report": counts.get("validation_report"),
            "bypass_report": str(bypass_report),
        },
    )
    print(f"[{STAGE}] QA pass complete -> {out_path}  "
          f"(nodes={counts['nodes_total']}, "
          f"noise={counts['noise_marked_total']}, "
          f"bypassed={counts['bypassed_total']})")
    return out_path


if __name__ == "__main__":
    run()