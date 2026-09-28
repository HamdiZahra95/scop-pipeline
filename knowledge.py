"""
knowledge.py — external reference-ontology index for the knowledge-guided run.

Loads the frozen guiding ontology (ML Ontology, Humm 2026 — seed/ML_Ontology.ttl)
ONCE and exposes a single alignment primitive, `match()`, that every guided stage
uses so alignment can never drift between stages (the same single-source
discipline as common.get_uri / common.call_llm).

Design contract:
  * Imported/loaded ONLY by guided-mode stages; the baseline run never touches it.
  * Loading is lazy (first use) so importing the module is free.
  * `match(label, definition=None)` returns a KnowledgeMatch describing whether a
    generated concept aligns to a reference concept, by which method, and to which
    reference parent — used for grounding (S07), skeleton anchoring (S08),
    gate-recovery (S03), and skos:*Match emission (S11).
  * The reference is the GUIDING ontology only. The held-out evaluation ontology
    (ACM CCS) is deliberately NOT loaded here — it must never enter the pipeline.

Exposed data:
  concepts        : {slug: prefLabel} for every reference concept.
  categories      : the reference's top-level category slugs (ML_area, ML_task…).
  broader         : {child_slug: [parent_slug, ...]} from skos:broader.
  relations       : set of reference relation names (used_for, can_perform, …).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import common as C

if (C.ROOT / "data" / "reference" / "ML_Ontology.ttl").exists():
    REF_PATH = C.ROOT / "data" / "reference" / "ML_Ontology.ttl"
elif (C.SEED / "ML_Ontology.ttl").exists():
    REF_PATH = C.SEED / "ML_Ontology.ttl"
else:
    REF_PATH = C.ROOT / "reference" / "ML_Ontology.ttl"
REF_NS = "http://h-da.de/ml-ontology/"

# Semantic-match threshold shared by all guided stages (env-tunable).
import os
FUZZY_THRESHOLD = float(os.getenv("SCOP_KG_THRESHOLD", "0.85"))


@dataclass
class KnowledgeMatch:
    """Result of aligning a generated concept to the reference ontology."""
    kind: str                      # "exact" | "lexical" | "semantic" | "none"
    ref_term: Optional[str] = None     # reference prefLabel matched (canonical)
    ref_slug: Optional[str] = None     # its slug
    ref_parent: Optional[str] = None   # a reference skos:broader parent slug, if any
    score: float = 0.0

    @property
    def matched(self) -> bool:
        return self.kind != "none"


# ── module-level lazy singletons ─────────────────────────────────────────────
_loaded = False
concepts: dict = {}       # slug -> prefLabel
_norm_index: dict = {}    # aggressive-norm key -> slug
categories: set = set()   # top-category slugs
broader: dict = {}        # child_slug -> [parent_slug]
relations: set = set()
_labels_list: list = []   # [(slug, prefLabel)] for embedding order
_emb = None               # cached reference embeddings (tensor)
_model = None


def _norm(label: str) -> str:
    """Aggressive lexical key (matches the analysis scripts): lowercase, strip
    punctuation, singularise last token, collapse whitespace."""
    s = str(label).lower().strip().replace("_", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
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


def load(force: bool = False) -> None:
    """Parse the reference ontology once into the module-level indexes."""
    global _loaded, concepts, _norm_index, categories, broader, relations, _labels_list
    if _loaded and not force:
        return
    if not REF_PATH.is_file():
        raise FileNotFoundError(
            f"Guiding ontology not found at {REF_PATH}. "
            f"Copy ML_Ontology.ttl into seed/ for the knowledge-guided run."
        )
    from rdflib import Graph, RDF, RDFS, URIRef
    from rdflib.namespace import SKOS

    g = Graph(); g.parse(str(REF_PATH), format="turtle")

    concepts = {}
    _norm_index = {}
    for s, _, lbl in g.triples((None, SKOS.prefLabel, None)):
        if isinstance(s, URIRef):
            slug = C.get_uri_name(str(lbl))
            if slug:
                concepts[slug] = str(lbl)
                _norm_index.setdefault(_norm(lbl), slug)

    categories = {C.get_uri_name(str(c).split("/")[-1])
                  for c in g.subjects(RDF.type, RDFS.Class)}

    broader = {}
    for child, _, parent in g.triples((None, SKOS.broader, None)):
        cl = concepts_slug_for(g, child)
        pl = concepts_slug_for(g, parent)
        if cl and pl:
            broader.setdefault(cl, []).append(pl)

    relations = {C.get_uri_name(str(p).split("/")[-1])
                 for p in g.subjects(RDF.type, RDF.Property)}

    _labels_list = sorted(concepts.items())
    _loaded = True


def concepts_slug_for(g, node) -> Optional[str]:
    """Slug of a node's prefLabel (fallback to its local name)."""
    from rdflib.namespace import SKOS
    lbl = g.value(node, SKOS.prefLabel)
    if lbl:
        return C.get_uri_name(str(lbl))
    return C.get_uri_name(str(node).split("/")[-1]) or None


def _get_embeddings():
    """Lazily embed the reference labels once (reuses S06's model)."""
    global _emb, _model
    if _emb is not None:
        return _model, _emb
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    labels = [lbl for _, lbl in _labels_list]
    _emb = _model.encode(labels, convert_to_tensor=True, show_progress_bar=False)
    return _model, _emb


def _parent_of(slug: str) -> Optional[str]:
    parents = broader.get(slug)
    return parents[0] if parents else None


def match(label: str, definition: Optional[str] = None,
          use_semantic: bool = True) -> KnowledgeMatch:
    """Align a generated concept `label` to the reference ontology.

    Tries, in order: exact slug → aggressive-lexical → semantic (embedding cosine
    ≥ FUZZY_THRESHOLD). Returns a KnowledgeMatch (kind="none" when nothing clears
    the bar, so callers can treat "no match" as a graceful no-op).
    """
    load()
    slug = C.get_uri_name(label)
    if slug and slug in concepts:
        return KnowledgeMatch("exact", concepts[slug], slug, _parent_of(slug), 1.0)

    key = _norm(label)
    if key in _norm_index:
        rs = _norm_index[key]
        return KnowledgeMatch("lexical", concepts[rs], rs, _parent_of(rs), 1.0)

    if use_semantic and _labels_list:
        from sentence_transformers import util
        model, emb = _get_embeddings()
        q = model.encode(label, convert_to_tensor=True, show_progress_bar=False)
        sims = util.cos_sim(q, emb)[0]
        j = int(sims.argmax()); score = float(sims[j])
        if score >= FUZZY_THRESHOLD:
            rs, rlbl = _labels_list[j]
            return KnowledgeMatch("semantic", rlbl, rs, _parent_of(rs), round(score, 3))

    return KnowledgeMatch("none")


def is_reference_concept(label: str) -> bool:
    """True if `label` matches a reference concept (exact or lexical — cheap,
    no embeddings). Used by the S03 gate-recovery rule."""
    load()
    slug = C.get_uri_name(label)
    return bool(slug and (slug in concepts or _norm(label) in _norm_index))
