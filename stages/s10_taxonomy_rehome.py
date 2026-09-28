"""
Stage 9a: semantic taxonomy re-homing and controlled mechanism ablation.

Normal pipeline use
-------------------
``run()`` reads the latest S09 artifact and executes the full semantic re-homing
condition. The result remains a normal versioned S09a artifact with a manifest.

Controlled study use
--------------------
``run_conditions()`` starts every requested condition from one deep-copied,
byte-identified S09 payload:

* ``fallback``: shared preparation + deterministic root completion;
* ``phase1``: shared preparation + semantic floater placement + root completion;
* ``full``: shared preparation + the exact Phase-1 state used above + semantic
  refinement + root completion.

This separation prevents forced orphan elimination from being mistaken for
semantic improvement. Callers can supply a physically isolated cache namespace
for each replicate. Every LLM and map-cache identity includes the frozen input
hash and complete prompt/batch content, preventing offset-only stale-cache reuse.
A movement ledger records original/final parents and all preparation, routing,
refinement, fallback, and node-creation events.

The historical artifacts are never modified. The controlled experiment harness
uses explicit input paths and writes to a separate analysis directory.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, List, Sequence

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s10_taxonomy_rehome"
CONDITIONS = ("fallback", "phase1", "full")

# ── Tunables (environment-overridable) ──────────────────────────────────────
FLOATER_BATCH = int(os.getenv("S09A_FLOATER_BATCH", "12"))
REFINE_BATCH = int(os.getenv("S09A_REFINE_BATCH", "15"))
MAX_PASSES = int(os.getenv("S09A_MAX_PASSES", "5"))
FUZZY_THRESHOLD = float(os.getenv("S09A_FUZZY_THRESHOLD", "0.85"))
MAX_REFINE_LEVEL = int(os.getenv("S09A_MAX_REFINE_LEVEL", "3"))
REFINE_TIMEOUT = float(os.getenv("S09A_REFINE_TIMEOUT", "200"))
REFINE_MAX_TOKENS = int(os.getenv("S09A_REFINE_MAX_TOKENS", "8192"))

DOMAINS = list(C.TOP_LEVEL_DOMAINS)
DOMAIN_ORDER = [d for d in DOMAINS if d != "Computer_Science"] + [
    "Computer_Science"
]
SKELETON_NODES = set(C.SKELETON.keys()) | set(DOMAINS) | set(C.ML_LEAVES)
_SKELETON_SLUGS = {
    C.get_uri_name(name): name for name in SKELETON_NODES if C.get_uri_name(name)
}


def _is_protected(name: str) -> bool:
    """Return whether ``name`` is a fixed skeleton/anchor node."""
    return name in SKELETON_NODES or C.get_uri_name(name) in _SKELETON_SLUGS


def _is_excluded(data: dict | None) -> bool:
    """Records marked by S09's corruption guard are preserved but never routed."""
    return bool(isinstance(data, dict) and data.get("qa_bypassed"))


def _real_nodes(db: dict) -> Iterable[tuple[str, dict]]:
    for name, data in db.items():
        if name != "__meta__" and isinstance(data, dict):
            yield name, data


def _content_key(prefix: str, payload: Any) -> str:
    """Create a stable cache identity from complete semantic work content."""
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:24]}"


def _normalise_cache_namespace(namespace: str | None) -> str:
    """Validate a relative cache namespace before it becomes a directory path."""
    value = (namespace or STAGE).strip().replace("\\", "/")
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(
            "cache_namespace must be a non-empty relative path without '..'"
        )
    return value


# ── Structured LLM responses ────────────────────────────────────────────────
class FloaterPlacement(BaseModel):
    concept: str
    target_domain: str
    proposed_parent: str = Field(default="")


class FloaterBatch(BaseModel):
    placements: List[FloaterPlacement] = Field(default_factory=list)


class RefineDecision(BaseModel):
    concept: str
    decision: str = Field(default="ok")
    proposed_path: str = Field(default="")


class RefineBatch(BaseModel):
    decisions: List[RefineDecision] = Field(default_factory=list)


class TreatmentIncomplete(RuntimeError):
    """Raised when a semantic condition cannot be applied exactly as specified.

    Unlike quota pauses, this marks the replicate as failed. No fallback/no-op
    result from an incomplete LLM batch may be promoted as a completed treatment.
    """


def _complete_floater_validator(expected: Sequence[str],
                                tax: Taxonomy | None = None):
    """Require exact, domain-consistent placements before caching a batch.

    A proposed parent may resolve only inside the selected domain subtree or use
    a globally new label that can be materialized there. Existing same-slug
    nodes outside that subtree—including still-unplaced floaters—make the
    response invalid, so ``call_llm`` retries it instead of checkpointing a
    placement that application would later reject. Every rejection exposes
    bounded, machine-derived diagnostics through ``validation_feedback``; the
    validator never rewrites the response or mutates the taxonomy.
    """
    expected_list = list(expected)
    expected_set = set(expected_list)

    def validate(text: str):
        validate.validation_feedback = None
        try:
            parsed = FloaterBatch.model_validate_json(text)
        except Exception as exc:
            detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            validate.validation_feedback = (
                "The response is not one complete valid JSON object matching "
                "the required placements schema. Return complete JSON from the "
                f"opening brace through the closing brace. Parse error: {detail}"
            )
            return None

        for placement in parsed.placements:
            if placement.concept not in expected_set:
                cleaned = re.sub(r"\s*\[INTERNAL NODE:[^\]]*\]", "", placement.concept).strip()
                if cleaned in expected_set:
                    placement.concept = cleaned

        errors: list[str] = []
        concepts = [placement.concept for placement in parsed.placements]
        concept_set = set(concepts)
        if len(concepts) != len(expected_list):
            errors.append(
                f"Placement count is {len(concepts)}; exactly "
                f"{len(expected_list)} placements are required."
            )
        duplicates = sorted({
            concept for concept in concepts if concepts.count(concept) > 1
        })
        if duplicates:
            errors.append(
                "Duplicate concept placements are forbidden: "
                + json.dumps(duplicates, ensure_ascii=False)
                + "."
            )
        missing = sorted(expected_set - concept_set)
        unexpected = sorted(concept_set - expected_set)
        if missing:
            errors.append(
                "Missing requested concepts: "
                + json.dumps(missing, ensure_ascii=False)
                + "."
            )
        if unexpected:
            errors.append(
                "Unexpected concepts must be removed: "
                + json.dumps(unexpected, ensure_ascii=False)
                + "."
            )

        for placement in parsed.placements:
            domain = placement.target_domain
            proposed = placement.proposed_parent
            valid_domain = domain in DOMAINS
            valid_parent = bool(C.get_uri_name(proposed))
            if not valid_domain:
                errors.append(
                    f"Concept {placement.concept!r} selects invalid "
                    f"target_domain={domain!r}; choose exactly one of {DOMAINS!r}."
                )
            if not valid_parent:
                errors.append(
                    f"Concept {placement.concept!r} has an empty or invalid "
                    "proposed_parent; provide a nonempty class label."
                )
            if tax is None or not valid_domain or not valid_parent:
                continue

            match = _resolve_parent(tax, proposed, domain)
            if match == placement.concept:
                match = None
            collision = _find_by_slug(tax, proposed) if match is None else None
            if collision is None:
                continue
            existing_domain = tax.domain_of(collision)
            existing_path = " → ".join(tax.path_to_root(collision))
            errors.append(
                f"Topology collision for concept {placement.concept!r}: "
                f"selected target_domain={domain!r}, proposed_parent={proposed!r}; "
                f"existing same-slug node={collision!r}, "
                f"existing_domain={existing_domain!r}, "
                f"existing_path={existing_path!r}. Allowed correction: choose "
                "a parent that resolves inside the selected target_domain or a "
                "globally new parent label; change target_domain only when that "
                "domain is semantically correct. Never reuse an out-of-domain "
                "node or create a duplicate of its slug."
            )

        if errors:
            validate.validation_feedback = "\n".join(
                f"- {error}" for error in errors
            )
            return None
        return parsed

    validate.validation_feedback = None
    return validate


def _parse_proposed_path(value: Any) -> list[str] | None:
    """Parse a nonempty ``>`` path without silently dropping empty segments."""
    raw = str(value or "")
    parts = [part.strip() for part in raw.split(">")]
    if not parts or any(not part for part in parts):
        return None
    if any(not C.get_uri_name(part) for part in parts):
        return None
    return parts


def _simulate_refine_path(sim: Taxonomy, domain: str, path: list[str],
                          concept: str):
    """Resolve a proposed move path on ``sim``, mutating it exactly as
    :func:`_resolve_path` would (creating missing in-prefix nodes).

    Returns ``(resolved_parent, None)`` when the path applies cleanly, or
    ``(None, diagnostic)`` on a genuine out-of-prefix collision or cycle. ``sim``
    must be a disposable taxonomy copy so a whole batch can be simulated
    decision-by-decision, letting a later decision see nodes an earlier decision
    moved or created. The real taxonomy is never touched.
    """
    segments = [
        segment for segment in path
        if C.get_uri_name(segment)
        and C.get_uri_name(segment) != C.get_uri_name(concept)
    ]
    if segments and C.get_uri_name(segments[0]) == C.get_uri_name(domain):
        segments = segments[1:]
    running = domain
    for segment in segments:
        match = _resolve_under_prefix(sim, segment, running, exclude=concept)
        if match:
            if sim.is_ancestor(concept, match):
                return None, (
                    f"proposed path segment {segment!r} resolves to existing "
                    f"node {match!r}, a descendant of {concept!r}; applying it "
                    "would create a cycle"
                )
            running = match
            continue
        collision = _find_by_slug(sim, segment)
        if collision is not None:
            existing_domain = sim.domain_of(collision)
            existing_path = " → ".join(sim.path_to_root(collision))
            slug = C.get_uri_name(segment)
            return None, (
                f"path segment {segment!r} does not exist under the required "
                f"prefix {running!r}, but the same label already exists globally "
                f"as {collision!r} (existing_domain={existing_domain!r}, "
                f"existing_path={existing_path!r}, common slug={slug!r}); reusing it would leave the "
                f"audited domain {domain!r}. Allowed correction: keep the whole "
                f"path inside {domain!r} using an in-prefix node or a globally "
                f"new label (note that differences in casing, spaces, and underscores "
                f"produce the same slug {slug!r}; choose a distinct label name), or "
                "return \"ok\" if the current placement is already a genuine is-a. "
                "Never reuse an out-of-domain node or duplicate its slug."
            )
        # Application would create this new node under ``running``; do the same
        # on the disposable copy so later segments and decisions see it.
        sim.add_node(segment, running, action="phase2_sim_created")
        running = segment
    return running, None


def _complete_refine_validator(expected: Sequence[str],
                               expected_domain: str | None = None,
                               tax: Taxonomy | None = None):
    """Require one admissible, domain-rooted, collision-free decision per child.

    Beyond shape/decision/path checks, the move set must survive the same
    prefix-containment, acyclicity, and acceptance rules that application
    enforces. Because application processes the batch in sorted-child order and
    :func:`_resolve_path` mutates the tree as it goes, the validator replays the
    whole batch on a disposable taxonomy copy in that same order, so an earlier
    move that relocates a node is visible to a later decision that targets it.
    This makes validation exactly as permissive as application—no more, no
    less—so no cachable response is later rejected and no valid response is
    falsely refused. Every rejection exposes bounded, machine-derived
    diagnostics through ``validation_feedback``; the validator never rewrites the
    response or mutates the real taxonomy.
    """
    expected_list = list(expected)
    expected_set = set(expected_list)
    domain_slugs = {C.get_uri_name(domain) for domain in DOMAINS}
    required_domain_slug = (
        C.get_uri_name(expected_domain) if expected_domain else None
    )

    def validate(text: str):
        validate.validation_feedback = None
        try:
            parsed = RefineBatch.model_validate_json(text)
        except Exception as exc:
            detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            validate.validation_feedback = (
                "The response is not one complete valid JSON object matching the "
                "required decisions schema. Return complete JSON from the opening "
                f"brace through the closing brace. Parse error: {detail}"
            )
            return None

        for decision in parsed.decisions:
            if decision.concept not in expected_set:
                cleaned = re.sub(r"\s*\[INTERNAL NODE:[^\]]*\]", "", decision.concept).strip()
                if cleaned in expected_set:
                    decision.concept = cleaned

        errors: list[str] = []
        concepts = [decision.concept for decision in parsed.decisions]
        concept_set = set(concepts)
        if len(concepts) != len(expected_list):
            errors.append(
                f"Decision count is {len(concepts)}; exactly "
                f"{len(expected_list)} decisions are required."
            )
        duplicates = sorted({
            concept for concept in concepts if concepts.count(concept) > 1
        })
        if duplicates:
            errors.append(
                "Duplicate concept decisions are forbidden: "
                + json.dumps(duplicates, ensure_ascii=False)
                + "."
            )
        missing = sorted(expected_set - concept_set)
        unexpected = sorted(concept_set - expected_set)
        if missing:
            errors.append(
                "Missing requested concepts: "
                + json.dumps(missing, ensure_ascii=False)
                + "."
            )
        if unexpected:
            errors.append(
                "Unexpected concepts must be removed: "
                + json.dumps(unexpected, ensure_ascii=False)
                + "."
            )

        for decision in parsed.decisions:
            kind = (decision.decision or "").strip().lower()
            if kind not in {"ok", "move"}:
                errors.append(
                    f"Concept {decision.concept!r} has invalid decision "
                    f"{decision.decision!r}; use exactly \"ok\" or \"move\"."
                )
                continue
            if kind != "move":
                continue
            segments = _parse_proposed_path(decision.proposed_path)
            if not segments:
                errors.append(
                    f"Concept {decision.concept!r} is a move but has no valid "
                    "' > '-separated proposed_path with nonempty segments."
                )
                continue
            concept_slug = C.get_uri_name(decision.concept)
            if segments and C.get_uri_name(segments[-1]) == concept_slug:
                segments = segments[:-1]
                decision.proposed_path = " > ".join(segments)

            if not segments:
                errors.append(
                    f"Concept {decision.concept!r} is a move but has no parent "
                    "segments remaining after removing self-reference."
                )
                continue

            first_slug = C.get_uri_name(segments[0])
            if first_slug not in domain_slugs:
                menu = ", ".join(repr(d) for d in DOMAINS)
                errors.append(
                    f"Concept {decision.concept!r} proposed_path must start at a "
                    f"top-level domain ({menu}); got {segments[0]!r}. Non-domains "
                    "are forbidden. Return \"ok\" if the concept cannot be moved "
                    "under one of the valid domains."
                )
                continue
            if required_domain_slug and first_slug != required_domain_slug:
                errors.append(
                    f"Concept {decision.concept!r} proposed_path must start at "
                    f"the audited domain {expected_domain!r}; got {segments[0]!r}. "
                    f"Moves across top-level domains are forbidden in Phase 2. "
                    f"Keep the path inside {expected_domain!r} or return \"ok\"."
                )
                continue
            if concept_slug in {C.get_uri_name(segment) for segment in segments}:
                errors.append(
                    f"Concept {decision.concept!r} must not appear in its own "
                    "proposed_path."
                )
                continue

        # Topology/acceptance is checked only once the batch is shape-valid, by
        # replaying it on a disposable copy in the exact sorted-child order and
        # mutating semantics application uses (fail-fast on the first genuine
        # collision/cycle/unapplicable move, mirroring _refine_children).
        if not errors and tax is not None and expected_domain:
            decision_map = {
                decision.concept: decision for decision in parsed.decisions
            }
            sim = Taxonomy(copy.deepcopy(tax.db))
            for child in expected_list:
                decision = decision_map.get(child)
                if decision is None:
                    continue
                if (decision.decision or "").strip().lower() != "move":
                    continue
                segments = _parse_proposed_path(decision.proposed_path)
                if not segments:
                    continue
                resolved, diagnostic = _simulate_refine_path(
                    sim, expected_domain, segments, child
                )
                if diagnostic:
                    errors.append(
                        f"Topology collision for concept {child!r}: {diagnostic}"
                    )
                    continue
                accepted = bool(
                    resolved
                    and resolved != sim.parent.get(child)
                    and sim.level(resolved) + 1 >= sim.level(child)
                )
                if not accepted:
                    current_p = sim.parent.get(child)
                    if resolved == current_p:
                        errors.append(
                            f"Concept {child!r} proposed move resolves to its current "
                            f"parent {current_p!r}. Set decision=\"ok\" (with proposed_path=\"\")."
                        )
                    elif sim.level(resolved) + 1 < sim.level(child):
                        errors.append(
                            f"Concept {child!r} move to {resolved!r} is too shallow "
                            f"(level {sim.level(resolved) + 1} vs current level {sim.level(child)}). "
                            "Phase 2 refinement only allows moving to an equal or deeper level. "
                            f"You MUST set decision=\"ok\" (with proposed_path=\"\") for {child!r} "
                            f"unless an admissible deeper path under {expected_domain!r} exists."
                        )
                    else:
                        errors.append(
                            f"Concept {child!r} move cannot be applied exactly: "
                            f"current parent={current_p!r}, resolved={resolved!r}. "
                            f"Set decision=\"ok\" (with proposed_path=\"\") if the current placement is sound."
                        )
                    continue
                sim.set_parent(child, resolved, action="phase2_sim_move")

        if errors:
            validate.validation_feedback = "\n".join(
                f"- {error}" for error in errors
            )
            return None
        return parsed

    validate.validation_feedback = None
    return validate


# ── Movement provenance ─────────────────────────────────────────────────────
class MovementRecorder:
    """Collect parent changes and generated-node events for one frozen input."""

    def __init__(self, original_db: dict, *, input_sha: str = "",
                 condition: str = "unassigned",
                 cache_namespace: str = STAGE):
        self.input_sha = input_sha
        self.condition = condition
        self.cache_namespace = cache_namespace
        self.original_parents = {
            name: data.get("taxonomy_parent") for name, data in _real_nodes(original_db)
        }
        self.original_flags = {
            name: {
                "is_skeleton": bool(data.get("is_skeleton")),
                "qa_bypassed": bool(data.get("qa_bypassed")),
            }
            for name, data in _real_nodes(original_db)
        }
        self.events: list[dict] = []

    def fork(self, condition: str) -> "MovementRecorder":
        cloned = copy.deepcopy(self)
        cloned.condition = condition
        return cloned

    def record(self, concept: str, action: str, **details: Any) -> None:
        event = {
            "sequence": len(self.events) + 1,
            "concept": concept,
            "action": action,
        }
        event.update(details)
        self.events.append(event)

    def record_move(self, concept: str, old_parent: str | None,
                    new_parent: str | None, action: str,
                    details: dict | None = None) -> None:
        self.record(
            concept, action, old_parent=old_parent, new_parent=new_parent,
            **(details or {}),
        )

    def rows(self, final_db: dict) -> list[dict]:
        by_concept: dict[str, list[dict]] = {}
        for event in self.events:
            by_concept.setdefault(event["concept"], []).append(event)

        names = set(self.original_parents)
        names.update(name for name, _ in _real_nodes(final_db))
        names.update(by_concept)
        rows = []
        for name in sorted(names, key=lambda value: (C.get_uri_name(value), value)):
            data = final_db.get(name) if isinstance(final_db.get(name), dict) else {}
            original_node = name in self.original_parents
            original_parent = self.original_parents.get(name)
            final_parent = data.get("taxonomy_parent") if data else None
            events = by_concept.get(name, [])
            changed = bool(original_node and original_parent != final_parent)
            if not original_node:
                action = events[-1]["action"] if events else "generated"
            elif changed:
                action = events[-1]["action"] if events else "parent_changed"
            else:
                action = "unchanged"
            rows.append({
                "concept": name,
                "condition": self.condition,
                "input_sha256": self.input_sha,
                "cache_namespace": self.cache_namespace,
                "original_node": original_node,
                "original_parent": original_parent,
                "final_parent": final_parent,
                "changed": changed,
                "action": action,
                "event_count": len(events),
                "events": events,
                "is_skeleton": bool(
                    data.get("is_skeleton")
                    or self.original_flags.get(name, {}).get("is_skeleton")
                ),
                "qa_bypassed": bool(
                    data.get("qa_bypassed")
                    or self.original_flags.get(name, {}).get("qa_bypassed")
                ),
                "is_intermediary": bool(data.get("is_intermediary")),
            })
        return rows


# ── Mutable taxonomy view ───────────────────────────────────────────────────
class Taxonomy:
    """Mutable parent/children view with cycle-safe attachment operations."""

    def __init__(self, db: dict, recorder: MovementRecorder | None = None):
        self.db = db
        self.recorder = recorder
        self.parent: dict[str, str | None] = {}
        self.children: dict[str, list[str]] = {}
        for name, data in _real_nodes(db):
            parent = data.get("taxonomy_parent")
            self.parent[name] = parent
            self.children.setdefault(name, [])
            if parent and parent != "owl:Thing":
                self.children.setdefault(parent, []).append(name)

    def has_children(self, node: str) -> bool:
        return bool(self.children.get(node))

    def path_to_root(self, node: str) -> list[str]:
        path = [node]
        seen = {node}
        current = self.parent.get(node)
        while current and current != "owl:Thing" and current in self.db:
            path.append(current)
            if current in DOMAINS or current in seen:
                break
            seen.add(current)
            current = self.parent.get(current)
        return path

    def reaches_domain(self, node: str) -> bool:
        return any(item in DOMAINS for item in self.path_to_root(node))

    def domain_of(self, node: str) -> str | None:
        for item in self.path_to_root(node):
            if item in DOMAINS:
                return item
        return None

    def descendants(self, root: str) -> set[str]:
        output: set[str] = set()
        stack = list(self.children.get(root, []))
        while stack:
            node = stack.pop()
            if node in output:
                continue
            output.add(node)
            stack.extend(self.children.get(node, []))
        return output

    def is_ancestor(self, ancestor: str, node: str) -> bool:
        current = self.parent.get(node)
        seen: set[str] = set()
        while current and current != "owl:Thing" and current in self.db:
            if current == ancestor:
                return True
            if current in seen:
                break
            seen.add(current)
            current = self.parent.get(current)
        return False

    def level(self, node: str) -> int:
        path = self.path_to_root(node)
        return len(path) - 1 if path and path[-1] in DOMAINS else 10_000

    def set_parent(self, node: str, new_parent: str,
                   *, action: str = "parent_move",
                   details: dict | None = None) -> bool:
        if node == new_parent or new_parent is None:
            return False
        if self.is_ancestor(node, new_parent):
            return False
        old_parent = self.parent.get(node)
        if old_parent == new_parent:
            return True
        if old_parent and node in self.children.get(old_parent, []):
            self.children[old_parent].remove(node)
        self.parent[node] = new_parent
        self.children.setdefault(new_parent, []).append(node)
        self.children.setdefault(node, self.children.get(node, []))
        self.db.setdefault(node, {})["taxonomy_parent"] = new_parent
        if self.recorder:
            self.recorder.record_move(
                node, old_parent, new_parent, action, details=details)
        return True

    def add_node(self, name: str, parent: str, *,
                 action: str = "generated_intermediary",
                 details: dict | None = None,
                 payload: dict | None = None) -> bool:
        if name in self.db:
            return False
        node = copy.deepcopy(payload) if payload is not None else {
            "f": 0,
            "td": 0,
            "cov": 1.0,
            "props": {},
            "literal_annotations": [],
            "is_intermediary": True,
        }
        node["taxonomy_parent"] = parent
        self.db[name] = node
        self.parent[name] = parent
        self.children.setdefault(name, [])
        self.children.setdefault(parent, []).append(name)
        if self.recorder:
            self.recorder.record(
                name, action, old_parent=None, new_parent=parent,
                **(details or {}),
            )
        return True


# ── Parent matching ─────────────────────────────────────────────────────────
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("🧠 Loading SentenceTransformer (all-MiniLM-L6-v2) "
              "for parent matching...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _resolve_from_candidates(proposed: str, candidates: Sequence[str]):
    """Resolve a label only within the caller-supplied admissible candidates."""
    admissible = list(dict.fromkeys(candidates))
    if not proposed or not admissible:
        return None
    proposed_slug = C.get_uri_name(proposed)
    if not proposed_slug:
        return None
    for candidate in admissible:
        if C.get_uri_name(candidate) == proposed_slug:
            return candidate
    try:
        from sentence_transformers import util as st_util
        model = _get_model()
        proposed_embedding = model.encode(proposed, convert_to_tensor=True)
        candidate_embeddings = model.encode(admissible, convert_to_tensor=True)
        scores = st_util.cos_sim(proposed_embedding, candidate_embeddings)[0]
        best_index = int(scores.argmax())
        if float(scores[best_index]) >= FUZZY_THRESHOLD:
            return admissible[best_index]
    except Exception as exc:
        print(f"      ⚠️ fuzzy match skipped ({type(exc).__name__}: {exc}).")
    return None


def _resolve_parent(tax: Taxonomy, proposed: str, domain: str):
    """Resolve a Phase-1 parent strictly within one domain subtree."""
    candidates = [domain] + sorted(tax.descendants(domain))
    candidates = [
        candidate for candidate in candidates
        if not _is_excluded(tax.db.get(candidate))
    ]
    return _resolve_from_candidates(proposed, candidates)


def _resolve_under_prefix(tax: Taxonomy, proposed: str, parent: str,
                          *, exclude: str | None = None):
    """Resolve a path segment only inside the preceding prefix's subtree."""
    candidates = [
        candidate for candidate in sorted(tax.descendants(parent))
        if candidate != exclude and not _is_excluded(tax.db.get(candidate))
    ]
    return _resolve_from_candidates(proposed, candidates)


def _find_by_slug(tax: Taxonomy, name: str):
    """Find a global slug collision; callers must not use it for routing."""
    slug = C.get_uri_name(name)
    if not slug:
        return None
    for candidate, data in _real_nodes(tax.db):
        if not _is_excluded(data) and C.get_uri_name(candidate) == slug:
            return candidate
    return None


# ── Shared preparation ──────────────────────────────────────────────────────
def _merge_slug_duplicates(tax: Taxonomy) -> dict:
    slug_map: dict[str, str] = {}
    merged = 0
    for name in list(tax.db.keys()):
        data = tax.db.get(name)
        if name == "__meta__" or not isinstance(data, dict) or _is_excluded(data):
            continue
        slug = C.get_uri_name(name)
        if not slug:
            continue
        if slug not in slug_map:
            slug_map[slug] = name
            continue
        canonical = slug_map[slug]
        print(f"   🔗 Slug merge: '{name}' → '{canonical}'")
        for child in list(tax.children.get(name, [])):
            tax.set_parent(
                child, canonical, action="slug_merge_child",
                details={"merged_node": name, "canonical": canonical},
            )
        if tax.parent.get(canonical) == name:
            replacement = tax.parent.get(name) or "owl:Thing"
            tax.set_parent(
                canonical, replacement, action="slug_merge_parent_repair",
                details={"merged_node": name},
            )
        canonical_data = tax.db[canonical]
        for annotation in data.get("literal_annotations", []):
            if annotation not in canonical_data.get("literal_annotations", []):
                canonical_data.setdefault("literal_annotations", []).append(annotation)
        for prop, targets in (data.get("props") or {}).items():
            for target, target_data in (targets or {}).items():
                canonical_data.setdefault("props", {}).setdefault(prop, {})[
                    target
                ] = target_data
        if tax.recorder:
            tax.recorder.record(
                name, "slug_merge_removed", old_parent=tax.parent.get(name),
                new_parent=None, canonical=canonical,
            )
        del tax.db[name]
        tax.parent.pop(name, None)
        tax.children.pop(name, None)
        merged += 1
    return {"slug_duplicates_merged": merged}


def _materialize_referenced_only(tax: Taxonomy) -> dict:
    """Create keyed floater records for names referenced only by edges."""
    existing_slugs = {
        C.get_uri_name(name) for name, _ in _real_nodes(tax.db)
        if C.get_uri_name(name)
    }
    referenced: dict[str, str] = {}
    for _, data in _real_nodes(tax.db):
        if _is_excluded(data):
            continue
        parent = data.get("taxonomy_parent")
        if parent and parent != "owl:Thing":
            referenced.setdefault(C.get_uri_name(parent), parent)
        for targets in (data.get("props") or {}).values():
            for target in (targets or {}).keys():
                referenced.setdefault(C.get_uri_name(target), target)

    created = 0
    for slug, name in referenced.items():
        if not slug or slug in existing_slugs:
            continue
        payload = {
            "f": 0,
            "td": 0,
            "cov": 1.0,
            "props": {},
            "literal_annotations": [],
        }
        if tax.add_node(
            name, "owl:Thing", action="materialized_reference",
            details={"reference_slug": slug}, payload=payload,
        ):
            existing_slugs.add(slug)
            created += 1
    print(f"   🧩 Materialized {created} referenced-only class(es) as floaters.")
    return {"referenced_materialized": created}


def _prepare_input(db: dict, recorder: MovementRecorder) -> tuple[Taxonomy, dict]:
    reset = 0
    for _, data in _real_nodes(db):
        if "rehomed" in data:
            data.pop("rehomed", None)
            reset += 1
    tax = Taxonomy(db, recorder)
    counts = {"rehomed_flags_reset": reset}
    counts.update(_merge_slug_duplicates(tax))
    # Rebuild graph maps after deletions before collecting referenced-only names.
    tax = Taxonomy(db, recorder)
    counts.update(_materialize_referenced_only(tax))
    return tax, counts


# ── Phase 1: semantic floater placement ─────────────────────────────────────
def _phase1_floaters(tax: Taxonomy, *, cache_namespace: str | None = None,
                     input_sha: str = "") -> dict:
    cache_stage = _normalise_cache_namespace(cache_namespace)
    print("\n🌊 PHASE 1: placing floaters (concepts not reaching any domain)...")
    floaters = sorted(
        name for name, data in _real_nodes(tax.db)
        if not data.get("is_skeleton")
        and not _is_protected(name)
        and not _is_excluded(data)
        and not tax.reaches_domain(name)
    )
    print(f"   {len(floaters)} floater(s) to place.")
    if not floaters:
        return {
            "floaters_total": 0,
            "floaters_placed": 0,
            "floaters_created_parent": 0,
        }

    batches = [
        (offset, floaters[offset:offset + FLOATER_BATCH])
        for offset in range(0, len(floaters), FLOATER_BATCH)
    ]

    forbidden_parent_labels = json.dumps(
        floaters, ensure_ascii=False, sort_keys=True
    )

    def place_batch(item):
        offset, batch = item
        print(
            f"   🌊 Floater batch {offset // FLOATER_BATCH + 1}/"
            f"{len(batches)} ({len(batch)} concept(s))..."
        )
        menu = ", ".join(DOMAINS)
        prompt = f"""You are an ML ontology expert placing orphaned concepts into an is-a taxonomy.
For EACH concept below, decide which of these five top-level domains it belongs under
(genuine is-a / kind-of): {menu}.
Also propose the most specific DIRECT parent class the concept is a kind of (a short class
name, e.g. "Learning Paradigm", "Clustering Algorithm"); if none is more specific than the
domain itself, repeat the domain name.

The proposed parent MUST already belong inside the selected target domain or be a genuinely
new class label that can be created there. Do NOT use another unplaced/orphan concept as a
parent. These unplaced labels are forbidden as proposed_parent values:
{forbidden_parent_labels}

Concepts: {batch}

Output strictly as JSON:
{{"placements": [{{"concept": "...", "target_domain": "Computer_Science", "proposed_parent": "Learning Paradigm"}}]}}"""
        llm_key = _content_key(
            "floater_llm_v4", {"input_sha": input_sha, "prompt": prompt}
        )
        parsed = C.call_llm(
            prompt, cache_key=llm_key,
            schema=_complete_floater_validator(batch, tax),
            stage=cache_stage, request_timeout=REFINE_TIMEOUT,
            max_output_tokens=REFINE_MAX_TOKENS,
        )
        return {
            "batch": batch,
            "cache_key": llm_key,
            "placements": [placement.model_dump() for placement in parsed.placements],
        }

    def safe_place_batch(item):
        try:
            return place_batch(item)
        except C.QuotaExhausted:
            raise
        except (C.MalformedResponse, RuntimeError) as exc:
            raise TreatmentIncomplete(
                f"Phase-1 batch at offset {item[0]} did not produce one valid "
                f"placement per requested concept"
            ) from exc

    results = C.resumable_map(
        cache_stage, batches, safe_place_batch,
        key=lambda item: _content_key(
            "floater_map_v4",
            {"input_sha": input_sha, "offset": item[0], "batch": item[1]},
        ),
    )

    placed = 0
    created = 0
    for result in results:
        placement_map = {
            placement["concept"]: placement
            for placement in result.get("placements", [])
        }
        batch = result.get("batch", [])
        if (len(placement_map) != len(batch)
                or set(placement_map) != set(batch)):
            raise TreatmentIncomplete(
                "Phase-1 cached batch is incomplete or contains duplicate concepts"
            )
        for concept in batch:
            placement = placement_map[concept]
            domain = placement.get("target_domain")
            if domain not in DOMAINS:
                raise TreatmentIncomplete(
                    f"Phase-1 returned invalid domain {domain!r} for {concept!r}"
                )
            proposed = (placement.get("proposed_parent") or "").strip()
            match = _resolve_parent(tax, proposed, domain)
            created_parent = False
            if match and match != concept:
                new_parent = match
            else:
                collision = _find_by_slug(tax, proposed)
                if collision is not None:
                    disambiguated = f"{domain}_{proposed}"
                    if _find_by_slug(tax, disambiguated) is None:
                        new_parent = disambiguated
                    else:
                        new_parent = domain
                    print(
                        f"   ⚠️  Phase-1 proposed parent {proposed!r} for {concept!r} collides "
                        f"with existing node {collision!r} in {tax.domain_of(collision)!r}. "
                        f"Disambiguating to {new_parent!r} under domain {domain!r}."
                    )
                else:
                    new_parent = proposed

                if new_parent == domain:
                    created_parent = False
                else:
                    created_parent = tax.add_node(
                        new_parent, domain, action="phase1_created_parent",
                        details={
                            "for_concept": concept,
                            "target_domain": domain,
                            "cache_key": result.get("cache_key"),
                        },
                    )
                    if not created_parent:
                        new_parent = domain
                    else:
                        created += 1
            details = {
                "target_domain": domain,
                "proposed_parent": proposed,
                "resolved_parent": new_parent,
                "created_parent": created_parent,
                "cache_key": result.get("cache_key"),
            }
            if not tax.set_parent(
                concept, new_parent, action="phase1_move", details=details
            ):
                if not tax.set_parent(
                    concept, domain, action="phase1_fallback_domain", details=details
                ):
                    raise TreatmentIncomplete(
                        f"Could not attach floater {concept!r} to domain {domain!r}"
                    )
            placed += 1
            tax.db[concept]["rehomed"] = True

    if placed != len(floaters):
        raise TreatmentIncomplete(
            f"Phase 1 applied {placed}/{len(floaters)} required placements"
        )
    print(
        f"   ✅ Phase 1: placed {placed}/{len(floaters)} floater(s); "
        f"created {created} new parent(s)."
    )
    return {
        "floaters_total": len(floaters),
        "floaters_placed": placed,
        "floaters_created_parent": created,
    }


# ── Phase 2: parent refinement ──────────────────────────────────────────────
def _resolve_path(tax: Taxonomy, domain: str, path: list[str], concept: str,
                  *, details: dict | None = None):
    """Resolve a proposed path while preserving every parent-child prefix.

    Existing nodes may be reused only when they are descendants of the preceding
    resolved segment. A same-slug node elsewhere is a hard collision, never an
    invitation to escape the selected domain or branch.
    """
    segments = [
        segment for segment in path
        if C.get_uri_name(segment)
        and C.get_uri_name(segment) != C.get_uri_name(concept)
    ]
    if segments and C.get_uri_name(segments[0]) == C.get_uri_name(domain):
        segments = segments[1:]
    running = domain
    for segment in segments:
        match = _resolve_under_prefix(
            tax, segment, running, exclude=concept
        )
        if match:
            if tax.is_ancestor(concept, match):
                raise TreatmentIncomplete(
                    f"Proposed path for {concept!r} would create a cycle at "
                    f"segment {segment!r}"
                )
            running = match
            continue
        collision = _find_by_slug(tax, segment)
        if collision is not None:
            raise TreatmentIncomplete(
                f"Path segment {segment!r} for {concept!r} exists outside the "
                f"required prefix under {running!r} as {collision!r}"
            )
        created = tax.add_node(
            segment, running, action="phase2_created_parent",
            details={"for_concept": concept, **(details or {})},
        )
        if not created:
            raise TreatmentIncomplete(
                f"Could not create path segment {segment!r} under {running!r}"
            )
        running = segment
    return running


def _refine_children(tax: Taxonomy, domain: str, parent: str,
                     children: list[str], *,
                     cache_namespace: str | None = None,
                     input_sha: str = "") -> int:
    cache_stage = _normalise_cache_namespace(cache_namespace)
    moves = 0
    sub_batches = [
        (offset, children[offset:offset + REFINE_BATCH])
        for offset in range(0, len(children), REFINE_BATCH)
    ]
    for offset, batch in sub_batches:
        lines = []
        for child in batch:
            current_path = " -> ".join(reversed(tax.path_to_root(child)))
            flag = " [INTERNAL NODE: has its own children]" if tax.has_children(child) else ""
            lines.append(f"- {child}{flag}\n    current path: {current_path}")
        context = "\n".join(lines)
        prompt = f"""You are an ML ontology expert auditing is-a (subsumption) placement.
Below are child concepts currently under "{parent}", each with its full current path from a
top-level domain. For EACH concept decide:
  - "ok" if it is already a genuine kind-of its current parent (leave it untouched), or
  - "move" if its current parent is wrong, and give the correct FULL path from a top-level
    domain down to its NEW parent (do not include the concept itself).

CRITICAL CONSTRAINTS:
1. ONLY move a concept if its new parent is at an EQUAL OR DEEPER level than its current level. Moving to a shallower or broader parent is strictly forbidden.
2. If the current placement is sound, or if no valid deeper parent exists, you MUST output decision "ok" with proposed_path "". Prefer "ok" for sound placements.
3. If moving, the path MUST start at the top-level domain "{domain}".

Concepts:
{context}

Output strictly as JSON. Write each proposed_path as a single " > "-separated string:
{{"decisions": [{{"concept": "...", "decision": "ok", "proposed_path": ""}},
               {{"concept": "...", "decision": "move", "proposed_path": "{domain} > ... > New_Parent"}}]}}"""
        cache_key = _content_key(
            "refine_llm_v5", {"input_sha": input_sha, "prompt": prompt}
        )
        try:
            parsed = C.call_llm(
                prompt, cache_key=cache_key,
                schema=_complete_refine_validator(
                    batch, expected_domain=domain, tax=tax
                ),
                stage=cache_stage, request_timeout=REFINE_TIMEOUT,
                max_output_tokens=REFINE_MAX_TOKENS,
            )
        except C.QuotaExhausted:
            raise
        except (C.MalformedResponse, RuntimeError) as exc:
            print(
                f"   ⚠️  Phase-2 refinement exhausted retries for batch under {parent!r} ({exc}). "
                "Retaining current valid placements."
            )
            for child in batch:
                tax.db[child]["rehomed"] = True
                if tax.recorder:
                    tax.recorder.record(
                        child, "phase2_fallback_retained",
                        current_parent=tax.parent.get(child),
                        cache_key=cache_key,
                        error=str(exc),
                    )
            continue

        decision_map = {decision.concept: decision for decision in parsed.decisions}
        for child in batch:
            decision = decision_map.get(child)
            if not decision or (decision.decision or "").lower() == "ok":
                tax.db[child]["rehomed"] = True
                if tax.recorder:
                    tax.recorder.record(
                        child, "phase2_confirmed",
                        current_parent=tax.parent.get(child),
                        cache_key=cache_key,
                    )
                continue

            try:
                path_segments = _parse_proposed_path(decision.proposed_path)
                if not path_segments:
                    raise ValueError(f"Phase-2 move for {child!r} has no valid path segments")
                if C.get_uri_name(path_segments[0]) != C.get_uri_name(domain):
                    raise ValueError(
                        f"Phase-2 move for {child!r} starts outside audited domain "
                        f"{domain!r}: {path_segments[0]!r}"
                    )
                detail = {
                    "proposed_path": path_segments,
                    "cache_key": cache_key,
                    "audited_parent": parent,
                }
                new_parent = _resolve_path(
                    tax, domain, path_segments, child, details=detail
                )
                accepted = bool(
                    new_parent
                    and new_parent != tax.parent.get(child)
                    and tax.level(new_parent) + 1 >= tax.level(child)
                )
                if not accepted:
                    raise ValueError(
                        f"Phase-2 move for {child!r} could not be applied exactly; "
                        f"current={tax.parent.get(child)!r}, resolved={new_parent!r}"
                    )
                if not tax.set_parent(
                    child, new_parent, action="phase2_move",
                    details={**detail, "resolved_parent": new_parent},
                ):
                    raise ValueError(
                        f"Phase-2 move for {child!r} was rejected by cycle safety"
                    )
                moves += 1
                tax.db[child]["rehomed"] = True
            except Exception as move_err:
                print(
                    f"   ⚠️  Phase-2 move could not be applied for {child!r} ({move_err}). "
                    f"Retaining current valid parent {tax.parent.get(child)!r}."
                )
                tax.db[child]["rehomed"] = True
                if tax.recorder:
                    tax.recorder.record(
                        child, "phase2_move_rejected_retained",
                        current_parent=tax.parent.get(child),
                        cache_key=cache_key,
                        error=str(move_err),
                    )
    return moves


def _phase2_refine(tax: Taxonomy, *, cache_namespace: str | None = None,
                   input_sha: str = "") -> dict:
    print(
        "\n🪜 PHASE 2: level-by-level refinement "
        f"(fixpoint or {MAX_PASSES} passes; parent level ≤ {MAX_REFINE_LEVEL})..."
    )
    total_moves = 0
    passes = 0
    for pass_number in range(1, MAX_PASSES + 1):
        passes = pass_number
        moves = 0
        for domain in DOMAIN_ORDER:
            nodes = [domain] + sorted(tax.descendants(domain))
            parents = [
                node for node in nodes
                if tax.has_children(node) and tax.level(node) <= MAX_REFINE_LEVEL
            ]
            parents.sort(key=lambda node: (tax.level(node), node))
            for parent in parents:
                children = [
                    child for child in sorted(tax.children.get(parent, []))
                    if not tax.db.get(child, {}).get("is_skeleton")
                    and not _is_protected(child)
                    and not _is_excluded(tax.db.get(child))
                    and not tax.db.get(child, {}).get("rehomed")
                ]
                if children:
                    moves += _refine_children(
                        tax, domain, parent, children,
                        cache_namespace=cache_namespace, input_sha=input_sha,
                    )
        print(f"   ↻ pass {pass_number}: {moves} move(s).")
        total_moves += moves
        if moves == 0:
            print(f"   ✅ fixpoint reached after {pass_number} pass(es).")
            break
    frozen = sum(
        1 for _, data in _real_nodes(tax.db) if data.get("rehomed")
    )
    return {
        "refine_moves": total_moves,
        "refine_frozen": frozen,
        "refine_passes": passes,
    }


# ── Deterministic structural completion ─────────────────────────────────────
def _root_sweep(tax: Taxonomy) -> dict:
    fallback = "Machine_Learning" if "Machine_Learning" in tax.db else DOMAINS[0]
    swept = 0
    for name, data in list(_real_nodes(tax.db)):
        if (
            name in DOMAINS
            or data.get("is_skeleton")
            or _is_protected(name)
            or _is_excluded(data)
        ):
            continue
        if not tax.reaches_domain(name) and tax.set_parent(
            name, fallback, action="root_fallback",
            details={"fallback_parent": fallback},
        ):
            swept += 1
    if swept:
        print(
            f"   🌱 Root sweep: re-anchored {swept} unreachable node(s) "
            f"under '{fallback}'."
        )
    return {"root_swept": swept}


# ── Controlled branching API ────────────────────────────────────────────────
def _finalize_outcome(condition: str, db: dict, recorder: MovementRecorder,
                      counts: dict) -> dict:
    tax = Taxonomy(db, recorder)
    ledger = recorder.rows(db)
    original_rows = [row for row in ledger if row["original_node"]]
    eligible_rows = [
        row for row in original_rows
        if not row["is_skeleton"] and not row["qa_bypassed"]
    ]
    orphan_count = sum(
        1 for name, data in _real_nodes(db)
        if name not in DOMAINS
        and not data.get("is_skeleton")
        and not _is_protected(name)
        and not _is_excluded(data)
        and not tax.reaches_domain(name)
    )
    final_counts = dict(counts)
    final_counts.update({
        "condition": condition,
        "nodes_total": sum(1 for _ in _real_nodes(db)),
        "original_nodes_total": len(original_rows),
        "eligible_original_nodes": len(eligible_rows),
        "generated_nodes_total": sum(
            1 for row in ledger if not row["original_node"] and row["final_parent"]
        ),
        "changed_original_parents": sum(row["changed"] for row in eligible_rows),
        "bypassed_excluded": sum(row["qa_bypassed"] for row in original_rows),
        "orphan_count_excluding_bypassed": orphan_count,
    })
    return {"db": db, "counts": final_counts, "ledger": ledger}


def run_conditions(input_db: dict, *, conditions: Sequence[str] = CONDITIONS,
                   input_sha: str = "",
                   cache_namespace: str | None = None) -> dict[str, dict]:
    """Execute controlled branches from one immutable in-memory S09 payload.

    Phase 1 is executed once per replicate. ``phase1`` receives a deep copy of
    that exact state before root completion, while ``full`` continues from it
    into Phase 2. This makes the secondary phase comparison genuinely paired.
    """
    requested = tuple(dict.fromkeys(conditions))
    unknown = sorted(set(requested) - set(CONDITIONS))
    if unknown or not requested:
        raise ValueError(
            f"conditions must be a non-empty subset of {CONDITIONS}; got {requested}"
        )
    cache_stage = _normalise_cache_namespace(cache_namespace)

    untouched = copy.deepcopy(input_db)
    base_db = copy.deepcopy(input_db)
    preparation_recorder = MovementRecorder(
        untouched, input_sha=input_sha, condition="prepared",
        cache_namespace=cache_stage,
    )
    _, preparation_counts = _prepare_input(base_db, preparation_recorder)

    outcomes: dict[str, dict] = {}
    if "fallback" in requested:
        fallback_db = copy.deepcopy(base_db)
        fallback_recorder = preparation_recorder.fork("fallback")
        fallback_tax = Taxonomy(fallback_db, fallback_recorder)
        fallback_counts = dict(preparation_counts)
        fallback_counts.update(_root_sweep(fallback_tax))
        outcomes["fallback"] = _finalize_outcome(
            "fallback", fallback_db, fallback_recorder, fallback_counts
        )

    if "phase1" in requested or "full" in requested:
        semantic_db = copy.deepcopy(base_db)
        semantic_recorder = preparation_recorder.fork("shared_phase1")
        semantic_tax = Taxonomy(semantic_db, semantic_recorder)
        semantic_counts = dict(preparation_counts)
        semantic_counts.update(_phase1_floaters(
            semantic_tax, cache_namespace=cache_stage, input_sha=input_sha
        ))

        if "phase1" in requested:
            phase1_db = copy.deepcopy(semantic_db)
            phase1_recorder = semantic_recorder.fork("phase1")
            phase1_tax = Taxonomy(phase1_db, phase1_recorder)
            phase1_counts = dict(semantic_counts)
            phase1_counts.update(_root_sweep(phase1_tax))
            outcomes["phase1"] = _finalize_outcome(
                "phase1", phase1_db, phase1_recorder, phase1_counts
            )

        if "full" in requested:
            semantic_recorder.condition = "full"
            semantic_counts.update(_phase2_refine(
                semantic_tax, cache_namespace=cache_stage, input_sha=input_sha
            ))
            semantic_counts.update(_root_sweep(semantic_tax))
            outcomes["full"] = _finalize_outcome(
                "full", semantic_db, semantic_recorder, semantic_counts
            )

    # Defensive assertion: callers rely on input immutability for causal pairing.
    if input_db != untouched:
        raise RuntimeError("run_conditions mutated its supplied frozen input")
    return {condition: outcomes[condition] for condition in requested}


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def run_from_path(in_path: str | Path, *, condition: str = "full",
                  cache_namespace: str | None = None,
                  output_path: str | Path | None = None,
                  movement_ledger_path: str | Path | None = None,
                  write_manifest: bool = True) -> Path:
    """Run one condition from an explicit frozen input and persist its ledger."""
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}, got {condition!r}")
    source = Path(in_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"S09a input does not exist: {source}")
    input_sha = C.sha256_file(source)
    cache_stage = _normalise_cache_namespace(cache_namespace)
    print(f"📂 S09a frozen input: {source} (sha256={input_sha})")

    try:
        outcome = run_conditions(
            C.load_json(source), conditions=(condition,), input_sha=input_sha,
            cache_namespace=cache_stage,
        )[condition]
    except C.QuotaExhausted as exc:
        print(
            f"[{STAGE}] paused — resume later (daily LLM quota exhausted). "
            f"Progress is checkpointed in {C.CACHES / cache_stage}; "
            f"re-run the same condition and namespace to continue. ({exc})"
        )
        sys.exit(0)

    destination = (
        Path(output_path).resolve() if output_path is not None
        else C.output_path(STAGE, __file__, ext="json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    C.save_json(destination, outcome["db"])

    if movement_ledger_path is not None:
        ledger_path = Path(movement_ledger_path).resolve()
    elif output_path is not None:
        ledger_path = destination.with_name(
            f"{destination.stem}.movements.jsonl"
        )
    else:
        ledger_path = C.report_path("s10_movements", __file__, ext="jsonl")
    _write_jsonl(ledger_path, outcome["ledger"])

    if write_manifest:
        C.write_manifest(
            STAGE, __file__, in_path=source, out_path=destination,
            counts=outcome["counts"],
            extra={
                "condition": condition,
                "cache_namespace": cache_stage,
                "movement_ledger": str(ledger_path),
                "input_sha256": input_sha,
                "cache_identity": "input+complete-prompt-content",
            },
        )
    print(
        f"[{STAGE}] {condition} complete -> {destination} "
        f"(changed_original_parents="
        f"{outcome['counts']['changed_original_parents']}, "
        f"orphans={outcome['counts']['orphan_count_excluding_bypassed']})"
    )
    return destination


def run() -> Path:
    """Normal pipeline entry point: full S09a from the latest S09 artifact."""
    print("🚀 S09a: semantic taxonomy re-homing (full condition)...")
    return run_from_path(
        C.require_latest("s09_qa_repair", ext="json"),
        condition="full", cache_namespace=STAGE,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher for S09a: runs pipeline mode by default, or ablation study when requested."""
    import argparse
    if argv is None:
        argv = sys.argv[1:]

    # If ablation study explicitly requested or ablation-specific arguments passed:
    if "--ablation" in argv or "--replicates" in argv or any(arg.startswith("--experiment-id") for arg in argv):
        ablation_args = [a for a in argv if a != "--ablation"]
        try:
            from analysis import v14_s09a_paired_ablation as ablation_module
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
            import v14_s09a_paired_ablation as ablation_module
        return ablation_module.main(ablation_args)

    # Standard pipeline / single-condition CLI
    parser = argparse.ArgumentParser(
        description="Stage 09a: Semantic Taxonomy Re-homing (Pipeline & Ablation Interface)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Execution Modes:
  1. Standard Pipeline Mode (default):
     python stages/s09a_taxonomy_rehome.py
     Processes the latest s09_qa_repair artifact through Phase 1 & Phase 2 re-homing
     and emits a versioned S09a artifact for Stage S10 without running the ablation study.

  2. Controlled Ablation Study Mode:
     python stages/s09a_taxonomy_rehome.py --ablation [OPTIONS]
     Runs the controlled paired ablation experiment (fallback vs phase1 vs full)
     delegating to analysis/v14_s09a_paired_ablation.py.
"""
    )
    parser.add_argument("--ablation", action="store_true", help="Run the controlled paired ablation study across conditions")
    parser.add_argument("--input", type=Path, default=None, help="Explicit input S09 JSON artifact path (default: latest S09 output)")
    parser.add_argument("--condition", choices=CONDITIONS, default="full", help="Single condition to execute for pipeline (default: full)")
    parser.add_argument("--cache-namespace", default=STAGE, help="Cache namespace for LLM calls (default: s09a_taxonomy_rehome)")
    parser.add_argument("--output", type=Path, default=None, help="Explicit output JSON path (default: versioned pipeline artifact)")

    args, remaining = parser.parse_known_args(argv)
    if args.ablation:
        try:
            from analysis import v14_s09a_paired_ablation as ablation_module
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
            import v14_s09a_paired_ablation as ablation_module
        return ablation_module.main(remaining)

    # Normal pipeline run
    if args.input:
        out_path = run_from_path(args.input, condition=args.condition, cache_namespace=args.cache_namespace, output_path=args.output)
    else:
        out_path = run()
    return 0 if out_path else 1


if __name__ == "__main__":
    sys.exit(main())

