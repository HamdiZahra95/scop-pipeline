from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_REPORTS = ROOT / "runs" / "baseline" / "reports" if (ROOT / "runs" / "baseline" / "reports").exists() else ROOT / "reports"
GUIDED_REPORTS = ROOT / "runs" / "guided" / "reports"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def latest_json(dirpath: Path) -> Path:
    files = sorted(dirpath.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No JSON files found in {dirpath}")
    return files[-1]


def load_json(path: str | Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_md(path: str | Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def latest_quality_report(mode: str) -> Path:
    report_dir = BASELINE_REPORTS if mode == "baseline" else GUIDED_REPORTS
    files = sorted(report_dir.glob("*.quality.json"))
    if not files:
        raise FileNotFoundError(f"No *.quality.json files found in {report_dir}")
    return files[-1]


def quality_summary(path: str | Path) -> dict:
    report = load_json(path)
    metrics = report.get("metrics", {})
    cq = report.get("competency_questions", {})
    return {
        "run_id": report.get("run_id"),
        "verdict": report.get("verdict"),
        "class_count": metrics.get("class_count"),
        "concept_count": metrics.get("concept_count"),
        "skeleton_count": metrics.get("skeleton_count"),
        "max_depth": metrics.get("max_depth"),
        "branching_factor": metrics.get("branching_factor"),
        "pct_with_parent": metrics.get("pct_with_parent"),
        "pct_with_property": metrics.get("pct_with_property"),
        "orphan_ratio": metrics.get("orphan_ratio"),
        "cq_total": cq.get("total"),
        "cq_answerable": cq.get("answerable"),
        "cq_gaps": cq.get("gaps"),
        "cq_results": cq.get("results", []),
    }


# ============================================================================
# Validation-suite foundation: held-out gold-standard alignment
# ----------------------------------------------------------------------------
# Added for the rigorous (non-circular) evaluation. Provides:
#   * locating the S11 OWL exports per mode,
#   * loading the GENERATED ontology (class set + is-a edges),
#   * loading a HELD-OUT gold ontology (AIO/ITO OWL via rdfs:subClassOf, ACM CCS
#     via skos:broader) into a uniform GoldOntology with transitive ancestors,
#   * a calibrated concept matcher (exact slug -> normalized-lexical -> embedding),
#   * bootstrap confidence intervals.
# The gold ontologies live under analysis/gold/ and are NEVER in seed/, so the
# pipeline cannot consume them as guidance (see analysis/gold/SOURCES.md).
# ============================================================================

import re as _re
import random as _random
import logging as _logging
from collections import defaultdict as _defaultdict
from dataclasses import dataclass as _dataclass, field as _field
from typing import Optional as _Optional

# The ACM CCS SKOS file contains one label-like URI with spaces; rdflib logs a
# WARNING per triple on parse. It parses fine, so quiet that specific logger.
_logging.getLogger("rdflib.term").setLevel(_logging.ERROR)

GOLD_DIR = Path(__file__).resolve().parent / "gold"

# Pipeline constants (single source of truth) with a self-contained fallback so
# the analysis package stays usable even if the pipeline package can't import.
try:
    import sys as _sys
    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    import common as _PC  # pipeline_v2/common.py
    ONTOLOGY_NS = _PC.ONTOLOGY_NS
    _SKELETON_NAMES = (set(_PC.SKELETON) | set(_PC.TOP_LEVEL_DOMAINS)
                       | set(_PC.ML_LEAVES))
    _pc_slug = _PC.get_uri_name
except Exception:  # pragma: no cover - fallback keeps analysis self-contained
    ONTOLOGY_NS = "http://linqubit.co/ontology/ml_concepts#"
    _SKELETON_NAMES = {
        "Computer_Science", "Mathematics", "Physics", "Biology", "Engineering",
        "Artificial_Intelligence", "Machine_Learning",
        "ML_Task", "ML_Model", "ML_Algorithm", "ML_Data_and_Representation",
        "ML_Objective_and_Constraint", "ML_Workflow_and_Protocol",
        "ML_Foundations_and_Theory", "ML_Infrastructure_and_Environment",
        "ML_Property_and_Quality_Attribute", "ML_Methodology_and_Science_Provenance",
    }

    def _pc_slug(name: str) -> str:
        s = _re.sub(r"[^a-z0-9_]", "_", str(name).lower().strip())
        return _re.sub(r"_+", "_", s).strip("_")

# Slugs of the fixed scaffolding (5 domains + CS->AI->ML spine + 10 ML leaves).
# These are injected structure, not discovered concepts, so they are excluded
# from content coverage/precision against a gold standard.
SKELETON_SLUGS = {_pc_slug(n) for n in _SKELETON_NAMES}


# ── S11/S12 OWL export locations ─────────────────────────────────────────────
def owl_dir(mode: str) -> Path:
    """Directory of OWL exports for a run mode (baseline or guided)."""
    if (ROOT / "ontologies" / f"scop_{mode}.owl").exists():
        return ROOT / "ontologies"
    for stage_dir in ("s12_export_owl", "s11_export_owl"):
        p = ROOT / "runs" / mode / "artifacts" / stage_dir
        if p.exists() and list(p.glob("*.owl")):
            return p
    if mode == "baseline":
        for stage_dir in ("s12_export_owl", "s11_export_owl"):
            p = ROOT / "artifacts" / stage_dir
            if p.exists() and list(p.glob("*.owl")):
                return p
    return ROOT / "runs" / mode / "artifacts" / "s12_export_owl"


def all_owls(mode: str) -> list:
    """All OWL exports for a mode, oldest-first (lexicographic == chrono)."""
    canonical = ROOT / "ontologies" / f"scop_{mode}.owl"
    if canonical.exists():
        return [canonical]
    d = owl_dir(mode)
    return sorted(d.glob("*.owl")) if d.exists() else []


def latest_owl(mode: str) -> Path:
    canonical = ROOT / "ontologies" / f"scop_{mode}.owl"
    if canonical.exists():
        return canonical
    files = all_owls(mode)
    if not files:
        raise FileNotFoundError(
            f"No OWL export for mode '{mode}' under {owl_dir(mode)}")
    return files[-1]


# ── label / slug normalization (for matching) ───────────────────────────────
def slug(label: str) -> str:
    """Deterministic slug identical to the pipeline's get_uri_name."""
    return _pc_slug(label)


def normalize_label(label: str) -> str:
    """Aggressive lexical key: lowercase, drop punctuation, singularise the last
    token, collapse whitespace. Matches knowledge.py's normalization so a
    generated label and a gold label that differ only by case/plural/punctuation
    map together."""
    s = str(label).lower().strip().replace("_", " ").replace("-", " ")
    s = _re.sub(r"[^a-z0-9 ]", " ", s)
    s = _re.sub(r"\s+", " ", s).strip()
    toks = s.split()
    if toks:
        w = toks[-1]
        if w.endswith("ies"):
            toks[-1] = w[:-3] + "y"
        elif w.endswith("sses") or w.endswith("ches") or w.endswith("shes"):
            toks[-1] = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
            toks[-1] = w[:-1]
    return " ".join(toks)


def local_name(uri) -> str:
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


def transitive_ancestors(parents_map: dict, node) -> set:
    """All ancestors of ``node`` following ``parents_map`` (child -> {parents}),
    transitive and cycle-safe."""
    seen = set()
    stack = list(parents_map.get(node, ()))
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(parents_map.get(n, ()))
    return seen


# ── Uniform gold-ontology model ─────────────────────────────────────────────
@_dataclass
class GoldOntology:
    name: str
    concepts: set                 # concept ids (str)
    label_of: dict                # id -> primary label
    parents: dict                 # id -> set(direct parent id)
    slug_index: dict              # slug(label) -> id
    norm_index: dict              # normalize_label(label) -> id
    _anc_cache: dict = _field(default_factory=dict)

    def ancestors(self, node) -> set:
        if node in self._anc_cache:
            return self._anc_cache[node]
        anc = transitive_ancestors(self.parents, node)
        self._anc_cache[node] = anc
        return anc

    def is_ancestor(self, anc, node) -> bool:
        return anc in self.ancestors(node)


def _index_labels(label_of: dict, alt_of: dict):
    slug_index, norm_index = {}, {}
    for cid, lbl in label_of.items():
        for L in [lbl] + list(alt_of.get(cid, [])):
            sg, nm = slug(L), normalize_label(L)
            if sg:
                slug_index.setdefault(sg, cid)
            if nm:
                norm_index.setdefault(nm, cid)
    return slug_index, norm_index


def _load_owl_gold(path: Path, name: str, ns_substr: _Optional[str] = None) -> GoldOntology:
    """Load an OWL gold ontology using rdfs:subClassOf as the hierarchy.

    ``ns_substr`` (case-insensitive) restricts concepts to the ontology's own
    namespace, dropping imported upper-ontology classes (e.g. BFO in AIO).
    """
    from rdflib import Graph, RDF, RDFS, OWL, URIRef

    g = Graph()
    g.parse(str(path), format="xml")

    def keep(u) -> bool:
        return isinstance(u, URIRef) and (
            ns_substr is None or ns_substr in str(u).lower())

    label_of = {}
    for s, o in g.subject_objects(RDFS.label):
        if keep(s):
            label_of.setdefault(str(s), str(o))
    classes = {str(s) for s in g.subjects(RDF.type, OWL.Class) if keep(s)}
    concepts = {c for c in classes if c in label_of}

    parents = _defaultdict(set)
    for c, p in g.subject_objects(RDFS.subClassOf):
        cs, ps = str(c), str(p)
        if cs in concepts and isinstance(p, URIRef) and ps in concepts:
            parents[cs].add(ps)

    slug_index, norm_index = _index_labels(label_of, {})
    return GoldOntology(name, concepts, label_of, dict(parents),
                        slug_index, norm_index)


def _load_skos_gold(path: Path, name: str) -> GoldOntology:
    """Load a SKOS gold ontology using skos:broader (+ inverse skos:narrower)."""
    from rdflib import Graph, URIRef
    from rdflib.namespace import SKOS

    g = Graph()
    g.parse(str(path), format="xml")

    label_of, alt_of = {}, _defaultdict(list)
    for s, o in g.subject_objects(SKOS.prefLabel):
        if isinstance(s, URIRef):
            label_of.setdefault(str(s), str(o))
    for s, o in g.subject_objects(SKOS.altLabel):
        if isinstance(s, URIRef):
            alt_of[str(s)].append(str(o))
    concepts = set(label_of)

    parents = _defaultdict(set)
    for c, p in g.subject_objects(SKOS.broader):
        cs, ps = str(c), str(p)
        if cs in concepts and ps in concepts:
            parents[cs].add(ps)
    for p, c in g.subject_objects(SKOS.narrower):   # inverse of broader
        cs, ps = str(c), str(p)
        if cs in concepts and ps in concepts:
            parents[cs].add(ps)

    slug_index, norm_index = _index_labels(label_of, alt_of)
    return GoldOntology(name, concepts, label_of, dict(parents),
                        slug_index, norm_index)


def _load_ito_tree(path: Path, name: str) -> GoldOntology:
    """Load ITO's lightweight ``{name, children}`` process/task tree JSON."""
    data = load_json(path)
    label_of, parents = {}, _defaultdict(set)

    def walk(node, parent_id):
        nm = node.get("name") if isinstance(node, dict) else str(node)
        cid = None
        if nm:
            cid = "ito:" + slug(nm)
            label_of.setdefault(cid, nm)
            if parent_id and parent_id != cid:
                parents[cid].add(parent_id)
        kids = node.get("children") if isinstance(node, dict) else None
        for k in (kids or []):
            walk(k, cid or parent_id)

    walk(data, None)
    concepts = set(label_of)
    slug_index, norm_index = _index_labels(label_of, {})
    return GoldOntology(name, concepts, label_of, dict(parents),
                        slug_index, norm_index)


def load_gold(name: str, *, ito_full: bool = False) -> GoldOntology:
    """Load a held-out gold ontology by short name: 'aio', 'ccs', or 'ito'.

    ITO defaults to the lightweight task tree (fast); ``ito_full=True`` parses
    the 124 MB OWL instead.
    """
    name = name.lower()
    if name == "aio":
        return _load_owl_gold(GOLD_DIR / "aio.owl", "aio", ns_substr="aio")
    if name == "ccs":
        return _load_skos_gold(GOLD_DIR / "acm_ccs2012_skos.xml", "ccs")
    if name == "ito":
        if ito_full:
            return _load_owl_gold(GOLD_DIR / "ITO.owl", "ito", ns_substr=None)
        return _load_ito_tree(GOLD_DIR / "ito-ai-process.json", "ito")
    raise ValueError(f"Unknown gold '{name}' (expected aio|ccs|ito).")


# ── Concept matcher (exact slug -> normalized-lexical -> embedding) ──────────
_MODEL = None


def load_embedding_model():
    """Lazily load the shared all-MiniLM-L6-v2 model (same as the pipeline)."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _MODEL


@_dataclass
class Match:
    kind: str                       # "exact" | "lexical" | "semantic" | "none"
    gold_id: _Optional[str] = None
    gold_label: _Optional[str] = None
    score: float = 0.0

    @property
    def matched(self) -> bool:
        return self.kind != "none"


class GoldMatcher:
    """Align generated concept labels to a GoldOntology.

    Tiered: exact slug equality -> normalized-lexical equality -> embedding
    cosine >= threshold. ``match_many`` batches the embedding step for speed.
    """

    def __init__(self, gold: GoldOntology, *, use_semantic: bool = True,
                 threshold: float = 0.85, model=None):
        self.gold = gold
        self.use_semantic = use_semantic
        self.threshold = threshold
        self._model = model
        self._gold_ids = None
        self._gold_emb = None

    def _ensure_gold_emb(self):
        if self._gold_emb is not None:
            return
        self._model = self._model or load_embedding_model()
        self._gold_ids = list(self.gold.concepts)
        labels = [self.gold.label_of[i] for i in self._gold_ids]
        self._gold_emb = self._model.encode(
            labels, convert_to_tensor=True, normalize_embeddings=True,
            show_progress_bar=False)

    def match_many(self, labels: list) -> list:
        results = [None] * len(labels)
        pending, pending_idx = [], []
        for i, lab in enumerate(labels):
            gid = self.gold.slug_index.get(slug(lab))
            if gid is not None:
                results[i] = Match("exact", gid, self.gold.label_of.get(gid), 1.0)
                continue
            gid = self.gold.norm_index.get(normalize_label(lab))
            if gid is not None:
                results[i] = Match("lexical", gid, self.gold.label_of.get(gid), 1.0)
                continue
            if self.use_semantic:
                pending.append(lab)
                pending_idx.append(i)
            else:
                results[i] = Match("none")

        if pending and self.use_semantic:
            try:
                from sentence_transformers import util as st_util
                self._ensure_gold_emb()
                q = self._model.encode(pending, convert_to_tensor=True,
                                       normalize_embeddings=True,
                                       show_progress_bar=False)
                sims = st_util.cos_sim(q, self._gold_emb)
                best = sims.max(dim=1)
                for j, idx in enumerate(pending_idx):
                    score = float(best.values[j])
                    gi = int(best.indices[j])
                    if score >= self.threshold:
                        gid = self._gold_ids[gi]
                        results[idx] = Match("semantic", gid,
                                             self.gold.label_of.get(gid),
                                             round(score, 3))
                    else:
                        results[idx] = Match("none", score=round(score, 3))
            except Exception as e:  # model/deps unavailable -> strict only
                print(f"[gold-matcher] semantic matching unavailable "
                      f"({type(e).__name__}: {e}); falling back to strict.")
                for idx in pending_idx:
                    if results[idx] is None:
                        results[idx] = Match("none")

        return [r if r is not None else Match("none") for r in results]


# ── bootstrap confidence interval ───────────────────────────────────────────
def bootstrap_ci(values: list, *, n: int = 1000, alpha: float = 0.05,
                 statistic=None, seed: int = 0) -> dict:
    """Percentile bootstrap CI for a statistic (default: mean) of ``values``."""
    if not values:
        return {"point": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    stat = statistic or (lambda xs: sum(xs) / len(xs))
    rnd = _random.Random(seed)
    k = len(values)
    point = stat(values)
    boots = []
    for _ in range(n):
        sample = [values[rnd.randrange(k)] for _ in range(k)]
        boots.append(stat(sample))
    boots.sort()
    lo = boots[int((alpha / 2) * n)]
    hi = boots[min(int((1 - alpha / 2) * n), n - 1)]
    return {"point": round(point, 4), "lo": round(lo, 4),
            "hi": round(hi, 4), "n": k}
