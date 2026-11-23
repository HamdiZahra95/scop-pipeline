"""
common.py — shared foundation for every pipeline_v2 stage.

Delivers the core design guarantee: NO stage output is ever overwritten.
Each stage writes to  artifacts/<stage>/<RUN_ID>__<codehash8>.<ext> , so a
re-run (especially after a code change) produces a NEW file next to the old
one — you can always diff the previous vs the new run to diagnose.

See REBUILD_PLAN.md §4.0, §5.2, §5.4.
"""

import os
import re
import sys
import json
import time
import hashlib
from datetime import datetime
from pathlib import Path

# ── Locations ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent            # pipeline_v2/

# Run mode (mode-aware knowledge-guided support). SCOP_MODE selects where a
# stage's artifacts / caches / logs / reports live, so the knowledge-guided run
# is fully isolated from the proven baseline WITHOUT changing any stage code.
#   * baseline (default / unset): artifacts/, caches/, logs/, reports/  — EXACTLY
#     as before, so the baseline run is byte-identical.
#   * guided                    : runs/guided/{artifacts,caches,logs,reports}/
# SEED/ is shared and read-only in both modes (same frozen concept seed).
SCOP_MODE = os.getenv("SCOP_MODE", "baseline").strip().lower() or "baseline"
_VALID_MODES = {"baseline", "guided"}
if SCOP_MODE not in _VALID_MODES:
    raise ValueError(f"SCOP_MODE must be one of {_VALID_MODES}, got {SCOP_MODE!r}.")

# Run root: every mode nests its whole tree symmetrically under runs/<mode>/.
_RUN_ROOT = ROOT / "runs" / SCOP_MODE

ARTIFACTS = _RUN_ROOT / "artifacts"
CACHES = _RUN_ROOT / "caches"
LOGS = _RUN_ROOT / "logs"
REPORTS = _RUN_ROOT / "reports"
if (ROOT / "data" / "seed").exists():
    SEED = ROOT / "data" / "seed"
elif (ROOT / "seed").exists():
    SEED = ROOT / "seed"
else:
    SEED = ROOT.parent / "seed"                        # test_result/seed/ (shared)

MANIFEST = LOGS / "manifest.jsonl"

for _d in (ARTIFACTS, CACHES, LOGS, REPORTS):
    _d.mkdir(parents=True, exist_ok=True)

# Load secrets from .env (the pipeline_v2 one first, then any ambient .env) so
# GOOGLE_API_KEY is never hardcoded in a stage. See get_client() / R5.
try:  # python-dotenv is optional at import time; only LLM stages truly need it.
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(ROOT / ".env")   # test_result/pipeline_v2/.env (preferred)
    _load_dotenv()                # fall back to any .env found by walking up
except Exception:  # pragma: no cover - dotenv missing or unreadable .env
    pass

# One RUN_ID per process (sortable). Override with RUN_ID / RUN_LABEL env vars.
_LABEL = os.getenv("RUN_LABEL", "")
RUN_ID = os.getenv("RUN_ID") or (
    datetime.now().strftime("%Y%m%d-%H%M%S") + (f"_{_LABEL}" if _LABEL else "")
)


# ── Hashing ────────────────────────────────────────────────────
def sha256_file(path) -> str:
    """SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def code_hash(caller_file: str) -> str:
    """First 8 hex chars of the SHA-256 of the calling stage's own source.

    Embedding this in output filenames lets you tell, at a glance, whether an
    output changed because the CODE changed (different code hash) or because
    upstream DATA changed (same code hash, newer RUN_ID).
    """
    return sha256_file(caller_file)[:8]


# ── Versioned output paths (the anti-overwrite core) ───────────
def output_path(stage: str, caller_file: str, ext: str = "json",
                sub: str | None = None) -> Path:
    """Return a NEW, never-overwritten output path for this stage-run.

        artifacts/<stage>/<RUN_ID>__<codehash8>[.<sub>].<ext>

    Args:
        stage: e.g. "s04_extract_properties".
        caller_file: pass __file__ from the stage so its code hash is embedded.
        ext: file extension without the dot.
        sub: optional extra label (e.g. a bin name) inserted before the ext.
    """
    stage_dir = ARTIFACTS / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    ch = code_hash(caller_file)
    name = f"{RUN_ID}__{ch}"
    if sub:
        name += f".{sub}"
    return stage_dir / f"{name}.{ext}"


def output_dir(stage: str, caller_file: str) -> Path:
    """Return a NEW, never-overwritten output DIRECTORY for this stage-run.

        artifacts/<stage>/<RUN_ID>__<codehash8>/

    Mirror of :func:`output_path` for stages that emit MANY files in one run
    (e.g. S03's per-frequency-bin ``freq_*.jsonl`` files). The directory is
    created and returned; every file the stage writes lives inside it, so a
    re-run — with a different ``RUN_ID`` and/or a different code hash — produces
    a NEW directory next to the old one and never overwrites prior bins.

    Collision guarantee: the directory name is ``<RUN_ID>__<codehash8>``, the
    exact naming convention used by :func:`output_path`. Two runs collide only
    if they share both the same ``RUN_ID`` and the same 8-char code hash; a
    distinct ``RUN_ID`` (new process / timestamp) or distinct code hash (changed
    source) yields a distinct directory.

    Args:
        stage: e.g. "s03_frequency_gate".
        caller_file: pass __file__ from the stage so its code hash is embedded.
    """
    stage_dir = ARTIFACTS / stage
    ch = code_hash(caller_file)
    run_dir = stage_dir / f"{RUN_ID}__{ch}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def report_path(name: str, caller_file: str, ext: str = "json") -> Path:
    """Return a NEW, never-overwritten READ-ONLY report path under ``reports/``.

        reports/<RUN_ID>__<codehash8>.<name>.<ext>

    Reports are audits/diagnostics (S09's redundancy & validation audits, S12's
    quality report) that are NOT a stage's primary versioned artifact — they live
    in ``reports/`` and are never fed downstream (R11.3). Naming mirrors
    :func:`output_path` (``<RUN_ID>__<codehash8>``) so a report is traceable to
    the exact run and code that produced it and a re-run never overwrites a prior
    report.

    Args:
        name: audit label inserted before the extension (e.g. "redundancy").
        caller_file: pass __file__ from the stage so its code hash is embedded.
        ext: file extension without the dot.
    """
    REPORTS.mkdir(parents=True, exist_ok=True)
    ch = code_hash(caller_file)
    return REPORTS / f"{RUN_ID}__{ch}.{name}.{ext}"


def latest_output(stage: str, ext: str = "json") -> Path | None:
    """Newest existing output for a stage (lexicographic = chronological).

    This is how a downstream stage finds its input without hardcoding a run:
    it grabs the most recent version, while every older version stays on disk.
    """
    stage_dir = ARTIFACTS / stage
    if not stage_dir.exists():
        return None
    candidates = sorted(p for p in stage_dir.glob(f"*.{ext}") if p.is_file())
    return candidates[-1] if candidates else None


def require_latest(stage: str, ext: str = "json") -> Path:
    """Like latest_output but raises a clear error if the stage never ran."""
    p = latest_output(stage, ext)
    if p is None:
        raise FileNotFoundError(
            f"No output found for stage '{stage}' (looked in {ARTIFACTS / stage}). "
            f"Run that stage first."
        )
    return p


# ── JSON / JSONL I/O ───────────────────────────────────────────
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def save_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Manifest (the run dashboard) ───────────────────────────────
def write_manifest(stage: str, caller_file: str, in_path, out_path,
                   counts: dict | None = None, extra: dict | None = None) -> None:
    """Append one authoritative line to logs/manifest.jsonl for this stage-run."""
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "run_id": RUN_ID,
        "stage": stage,
        "code_sha": code_hash(caller_file),
        "in": str(in_path) if in_path else None,
        "in_sha": sha256_file(in_path)
        if in_path and Path(in_path).is_file() else None,
        "out": str(out_path) if out_path else None,
        # A stage output may be a single file OR a versioned directory (S03's
        # per-bin dir). SHA-256 is only meaningful for a file, so a directory
        # output records out_sha=None rather than crashing.
        "out_sha": sha256_file(out_path)
        if out_path and Path(out_path).is_file() else None,
        "counts": counts or {},
    }
    if extra:
        rec["extra"] = extra
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    print(f"[manifest] {stage} run={RUN_ID} code={rec['code_sha']} "
          f"-> {out_path}  counts={rec['counts']}")


# ── Shared constants (single source of truth) — REBUILD_PLAN.md §5.4 ──
TOP_LEVEL_DOMAINS = [
    "Computer_Science", "Mathematics", "Physics", "Biology", "Engineering",
]

ML_LEAVES = [
    "ML_Task", "ML_Model", "ML_Algorithm", "ML_Data_and_Representation",
    "ML_Objective_and_Constraint", "ML_Workflow_and_Protocol",
    "ML_Foundations_and_Theory", "ML_Infrastructure_and_Environment",
    "ML_Property_and_Quality_Attribute", "ML_Methodology_and_Science_Provenance",
]

SKELETON = {
    "Computer_Science": "owl:Thing", "Mathematics": "owl:Thing",
    "Physics": "owl:Thing", "Biology": "owl:Thing", "Engineering": "owl:Thing",
    "Artificial_Intelligence": "Computer_Science",
    "Machine_Learning": "Artificial_Intelligence",
}
SKELETON.update({leaf: "Machine_Learning" for leaf in ML_LEAVES})

CORE_PROPERTIES = [
    "hasComponent", "processesData", "transforms", "learnsFrom", "optimizes",
    "producesOutput", "integrates", "organizes", "selects", "modifies",
    "evaluates", "hasPurpose", "hasCharacteristic",
]

# ── Frequency gate (single tunable knob) — REBUILD_PLAN §S03, R21 ──
# The ONE documented threshold that decides which concepts pass the frequency
# gate. S03 bins concepts by `corpus_frequency`; the `freq_gt_10` bin (frequency
# > FREQ_GATE_DEFAULT) is the single source of truth fed downstream to S04.
#
# CAVEAT (R21): this gate trades recall for precision. A HIGHER threshold keeps
# only the most frequent (highest-precision) concepts but DROPS rarer valid ones
# (lower recall); a LOWER threshold recovers rare concepts at the cost of more
# noise (lower precision). All bins are retained on disk (see `output_dir`), so
# the gate can be widened later without recomputing the pipeline.
FREQ_GATE_DEFAULT = 10


# ── URI generation (single source shared by S09 and S11) — R6.2 ──
# The ontology namespace every stage-generated URI hangs off of. Slugs are
# appended after the trailing '#'.
ONTOLOGY_NS = "http://linqubit.co/ontology/ml_concepts#"


def get_uri_name(name: str) -> str:
    """Deterministic URI slug for a concept/target/property name.

    Normalization (fixed, deterministic — same input always yields same slug):
      1. strip surrounding whitespace and remove any [NEW] prefix,
      2. map '&' to 'and',
      3. preserve trailing domain symbols if present (e.g. '++' in 'k-means++'),
      4. split PascalCase boundaries (e.g. BinarizedNeuralNetwork -> binarized_neural_network),
      5. replace every run of non-[a-z0-9_] characters with a single '_',
      6. collapse repeated underscores and trim leading/trailing underscores.
    """
    s = str(name).strip()
    s = re.sub(r"^\[NEW\][\s_]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[NEW\][\s_]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*&\s*", " and ", s)

    # Check for trailing domain symbols (like ++ or +)
    trailing_match = re.search(r"([^a-zA-Z0-9\s\-_)]+)$", s)
    trailing_sym = ""
    if trailing_match:
        sym = trailing_match.group(1)
        if sym in ("++", "+", "#", "*"):
            trailing_sym = sym
            s = s[:-len(trailing_sym)].rstrip()

    # Split PascalCase: lowercase followed by uppercase
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    slug = re.sub(r"[^a-z0-9_]", "_", s.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if trailing_sym:
        slug += trailing_sym
    return slug


def get_uri(name: str) -> str:
    """Full URI for a name: the ontology namespace + ``#`` + the deterministic
    slug from :func:`get_uri_name`.

    Shares :func:`get_uri_name`'s determinism and collision behavior: two names
    that produce the same slug produce the same URI. Returns e.g.
    ``"http://linqubit.co/ontology/ml_concepts#neural_network"``.
    """
    return ONTOLOGY_NS + get_uri_name(name)


# ── OWL-DL property axiom box (curated, never LLM-written) — R16 ──
# One entry per core property. Hand-reviewed. S11 reads this table verbatim to
# emit each property as an owl:ObjectProperty with domain/range, inverse, and
# characteristics. Tiering (R16.2–16.5):
#   Tier 1  every entry MUST carry `domain` + `range` (owl:Thing where no tighter
#           type universally applies; ML_LEAVES types where one does).
#   Tier 2  `inverse` + Irreflexive/Asymmetric where universally true.
#   Tier 3  Transitive / Symmetric ONLY where it universally holds
#           (hasComponent, organizes → Transitive; integrates → Symmetric).
# Functional / InverseFunctional are DELIBERATELY absent from all 13 (R16.5):
# each concept legitimately has many components, outputs, characteristics, etc.
# OWL-DL guard (R16.1): a Transitive property MUST NOT carry a `cardinality`
# restriction — enforced by validate_property_axioms() below.
PROPERTY_AXIOMS: dict[str, dict] = {
    # Tier 3 — mereological containment: TRANSITIVE only. In OWL 2 DL a transitive
    # (non-simple) property MAY NOT also be declared Irreflexive/Asymmetric (those
    # require simple properties), so we keep the semantically load-bearing
    # Transitive characteristic and omit irreflexive/asymmetric to stay in DL.
    "hasComponent": {
        "domain": "owl:Thing", "range": "owl:Thing",
        "inverse": "isComponentOf",
        "characteristics": ["Transitive"],
    },
    "processesData": {
        "domain": "ML_Model", "range": "ML_Data_and_Representation",
        "inverse": "isProcessedBy",
        "characteristics": [],
    },
    "transforms": {
        "domain": "owl:Thing", "range": "owl:Thing",
        "inverse": "isTransformedBy",
        "characteristics": [],
    },
    "learnsFrom": {
        "domain": "ML_Model", "range": "ML_Data_and_Representation",
        "inverse": "isLearnedFrom",
        "characteristics": ["Irreflexive"],
    },
    "optimizes": {
        "domain": "ML_Algorithm", "range": "ML_Objective_and_Constraint",
        "inverse": "isOptimizedBy",
        "characteristics": [],
    },
    "producesOutput": {
        "domain": "ML_Model", "range": "owl:Thing",
        "inverse": "isOutputOf",
        "characteristics": [],
    },
    # Tier 3 — integration is mutual: symmetric (its own inverse, so no `inverse`).
    "integrates": {
        "domain": "owl:Thing", "range": "owl:Thing",
        "characteristics": ["Symmetric"],
    },
    # Tier 3 — organizing is transitive containment: TRANSITIVE only (see
    # hasComponent — a transitive property cannot also be Irreflexive/Asymmetric
    # in OWL 2 DL).
    "organizes": {
        "domain": "owl:Thing", "range": "owl:Thing",
        "inverse": "isOrganizedBy",
        "characteristics": ["Transitive"],
    },
    "selects": {
        "domain": "ML_Algorithm", "range": "owl:Thing",
        "inverse": "isSelectedBy",
        "characteristics": [],
    },
    "modifies": {
        "domain": "owl:Thing", "range": "owl:Thing",
        "inverse": "isModifiedBy",
        "characteristics": ["Irreflexive"],
    },
    "evaluates": {
        "domain": "ML_Workflow_and_Protocol", "range": "owl:Thing",
        "inverse": "isEvaluatedBy",
        "characteristics": [],
    },
    "hasPurpose": {
        "domain": "owl:Thing", "range": "owl:Thing",
        "characteristics": [],
    },
    "hasCharacteristic": {
        "domain": "owl:Thing", "range": "ML_Property_and_Quality_Attribute",
        "inverse": "isCharacteristicOf",
        "characteristics": [],
    },
}

# Characteristics that are illegal for any of the 13 core properties (R16.5):
# assigning these would over-constrain the ontology and risk OWL-DL violations.
_FORBIDDEN_CHARACTERISTICS = {"Functional", "InverseFunctional"}


def validate_property_axioms(axioms: dict | None = None) -> None:
    """Fail-fast OWL-DL sanity check on the property axiom box (R16.1, R16.5).

    Raises ``ValueError`` if any entry:
      * carries a ``characteristics`` list containing both ``Transitive`` and a
        cardinality restriction (a Transitive property with cardinality breaks
        OWL-DL decidability — detected via a truthy ``cardinality`` key),
      * lists ``Functional`` or ``InverseFunctional`` (forbidden on the 13),
      * is missing ``domain`` or ``range`` (Tier 1 requirement — every property
        must be typed).

    Called at import time so a bad edit to :data:`PROPERTY_AXIOMS` crashes the
    process immediately rather than surfacing later in S11.

    Args:
        axioms: table to validate; defaults to :data:`PROPERTY_AXIOMS`. The
            argument exists so tests can feed deliberately-broken mutations.
    """
    table = PROPERTY_AXIOMS if axioms is None else axioms
    for prop, spec in table.items():
        chars = spec.get("characteristics", []) or []

        # Tier 1: domain + range are mandatory.
        if not spec.get("domain") or not spec.get("range"):
            raise ValueError(
                f"PROPERTY_AXIOMS['{prop}'] must define both 'domain' and "
                f"'range' (Tier 1, R16.2)."
            )

        # R16.5: no Functional / InverseFunctional on the core 13.
        forbidden = _FORBIDDEN_CHARACTERISTICS.intersection(chars)
        if forbidden:
            raise ValueError(
                f"PROPERTY_AXIOMS['{prop}'] carries forbidden characteristic(s) "
                f"{sorted(forbidden)}; Functional/InverseFunctional are not "
                f"allowed on the 13 core properties (R16.5)."
            )

        # R16.1: a Transitive property must not also carry a cardinality
        # restriction (would break OWL-DL decidability).
        if "Transitive" in chars and spec.get("cardinality"):
            raise ValueError(
                f"PROPERTY_AXIOMS['{prop}'] is Transitive AND carries a "
                f"cardinality restriction; this is illegal in OWL-DL (R16.1)."
            )

        # OWL 2 DL: a Transitive property is NON-SIMPLE and therefore may NOT be
        # declared Irreflexive or Asymmetric (both require simple properties).
        # HermiT rejects this combination outright ("Non-simple property ... in
        # asymmetric object property axiom"), leaving consistency unverifiable.
        if "Transitive" in chars:
            illegal = {"Irreflexive", "Asymmetric"} & set(chars)
            if illegal:
                raise ValueError(
                    f"PROPERTY_AXIOMS['{prop}'] is Transitive AND {sorted(illegal)}; "
                    f"a non-simple (transitive) property cannot be irreflexive or "
                    f"asymmetric in OWL-DL. Drop those characteristics."
                )


# Fail fast at import: a malformed axiom box must never reach S11.
validate_property_axioms()

# ── LLM infrastructure (single guarded entry point) — R5, R19, R22 ──
# Every stage that needs an LLM goes through get_client() / call_llm() so that:
#   * the API key lives ONLY in .env (R5 — no hardcoded key anywhere),
#   * calls are deterministic (temperature 0 + fixed seed where supported, R22.1),
#   * malformed responses are rejected-and-retried and NEVER reach an artifact
#     or the cache (R19.2),
#   * rate limits (HTTP 429) wait-and-retry the SAME request (R19.3),
#   * daily-quota exhaustion raises the DISTINCT QuotaExhausted signal so a stage
#     can pause cleanly instead of failing (R19.4),
#   * identical (cache_key) work is served from a per-stage JSON cache (R22.2).

# Provider / determinism knobs (overridable via env; defaults are deterministic).
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-31b-it")
LLM_SEED = int(os.getenv("LLM_SEED", "42"))          # fixed seed where supported
LLM_MAX_SCHEMA_ATTEMPTS = int(os.getenv("LLM_MAX_SCHEMA_ATTEMPTS", "3"))
LLM_MAX_RATE_RETRIES = int(os.getenv("LLM_MAX_RATE_RETRIES", "6"))
LLM_BACKOFF_BASE = float(os.getenv("LLM_BACKOFF_BASE", "5"))   # seconds
LLM_BACKOFF_CAP = float(os.getenv("LLM_BACKOFF_CAP", "60"))    # seconds
# When truthy, call_llm prints each network call as it starts/finishes with
# timing + response size, so long stages show live API progress (default on).
LLM_VERBOSE = os.getenv("LLM_VERBOSE", "1") not in ("0", "false", "False", "")
# Hard cap on output tokens per call. Without a cap, a model degeneration loop
# (repeating tokens) can run for many minutes and emit >100k chars before
# failing. A cap turns that runaway into a fast, cheap failure that
# reject-and-retry handles. 0/empty disables the cap.
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8192"))
# Hard per-request wall-clock timeout (seconds). max_output_tokens does not help
# if the model streams slowly or hangs, so a timeout guarantees no single call
# blocks the stage for minutes. On timeout we nudge temperature and retry to
# break a degeneration loop. 0 disables the timeout.
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "200"))
# When truthy, EVERY LLM attempt (prompt sent + raw response or error) is
# appended to logs/llm_trace.jsonl for offline diagnosis of why a specific
# batch keeps failing. One JSON line per attempt. Default on.
LLM_TRACE = os.getenv("LLM_TRACE", "1") not in ("0", "false", "False", "")
LLM_TRACE_PATH = LOGS / "llm_trace.jsonl"


def _trace_llm(record: dict) -> None:
    """Append one JSON line to logs/llm_trace.jsonl (best-effort, never raises).

    Captures the full request/response of a single LLM attempt so a persistently
    failing batch can be inspected: the exact prompt sent, the raw response text
    (or the exception), timing, sizes, and the outcome. Tracing must never break
    a run, so every error here is swallowed.
    """
    if not LLM_TRACE:
        return
    try:
        record.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        with open(LLM_TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


class QuotaExhausted(Exception):
    """Raised by :func:`call_llm` when the provider's *daily* quota is spent.

    This is a DISTINCT signal from an ordinary failure (R19.4): a stage catches
    it, checkpoints, prints a "paused — resume later" message and exits WITHOUT
    writing a primary artifact, so the run can resume the next day exactly where
    it left off. It is deliberately separate from transient rate limiting (HTTP
    429 for per-minute limits), which :func:`call_llm` handles internally by
    waiting and retrying the same request.
    """


class MalformedResponse(Exception):
    """Raised by :func:`call_llm` when a schema-guarded response stays invalid
    after ``LLM_MAX_SCHEMA_ATTEMPTS`` reject-and-retry attempts (R19.2).

    A malformed response NEVER enters the cache or an artifact; the stage that
    triggered it fails loudly rather than persisting garbage.
    """


# Module-level client singleton and per-stage cache tables (lazy).
_LLM_CLIENT = None
_LLM_CACHES: dict[str, dict] = {}


def get_llm_provider() -> str:
    """Detect the active LLM provider based on environment variables.

    Supports:
      1. 'ollama' : Ollama Cloud (OLLAMA_API_KEY) or Local Ollama (OLLAMA_HOST).
      2. 'google' : Google GenAI (GOOGLE_API_KEY or GEMINI_API_KEY).
    """
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit in {"ollama", "ollama_cloud", "local_ollama"}:
        return "ollama"
    if explicit in {"google", "gemini"}:
        return "google"

    if os.getenv("OLLAMA_API_KEY", "").strip() or os.getenv("OLLAMA_HOST", "").strip():
        return "ollama"
    return "google"


def _call_ollama_api(prompt: str, schema=None, temperature: float = 0, timeout: float = 120.0) -> str:
    """Call Ollama (Cloud or Local) via HTTP POST."""
    import urllib.request
    import urllib.error

    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    host = os.getenv("OLLAMA_HOST", "").strip()
    if not host:
        host = "https://ollama.com" if api_key else "http://localhost:11434"
    host = host.rstrip("/")

    url = f"{host}/api/generate"
    model = os.getenv("OLLAMA_MODEL", "gemma2")

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "seed": LLM_SEED,
        },
    }
    if schema is not None:
        payload["format"] = "json"

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            return res_json.get("response", "")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        err = RuntimeError(f"Ollama API error (HTTP {e.code}): {body}")
        err.code = e.code
        raise err from e
    except urllib.error.URLError as e:
        err = RuntimeError(f"Failed to connect to Ollama at {host}: {e}")
        err.code = None
        raise err from e


def get_client():
    """Build and return the LLM client or provider identifier.

    Supports Google GenAI API and Ollama (Cloud & Local).
    """
    global _LLM_CLIENT
    if _LLM_CLIENT is not None:
        return _LLM_CLIENT

    provider = get_llm_provider()
    if provider == "ollama":
        _LLM_CLIENT = "ollama"
        return _LLM_CLIENT

    # Google GenAI Provider
    api_key = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "No LLM credentials configured. Set one of the following in .env:\n"
            "  1. GOOGLE_API_KEY=<key> or GEMINI_API_KEY=<key> (for Google GenAI API)\n"
            "  2. OLLAMA_API_KEY=<key> (for Ollama Cloud)\n"
            "  3. OLLAMA_HOST=http://localhost:11434 (for Local Ollama)"
        )

    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "The 'google-genai' SDK is required for Google LLM stages but is not "
            "installed. Install it with: pip install google-genai"
        ) from e

    _LLM_CLIENT = genai.Client(api_key=api_key)
    return _LLM_CLIENT


# ── Per-stage LLM cache (keyed by cache_key) ───────────────────
def _llm_cache_path(stage: str) -> Path:
    """Location of a stage's LLM response cache: caches/<stage>/llm_cache.json."""
    d = CACHES / stage
    d.mkdir(parents=True, exist_ok=True)
    return d / "llm_cache.json"


def _load_llm_cache(stage: str) -> dict:
    """Load (once per process) and memoize a stage's on-disk LLM cache."""
    if stage in _LLM_CACHES:
        return _LLM_CACHES[stage]
    path = _llm_cache_path(stage)
    if path.is_file():
        try:
            _LLM_CACHES[stage] = load_json(path)
        except Exception:  # corrupt cache → start clean rather than crash
            _LLM_CACHES[stage] = {}
    else:
        _LLM_CACHES[stage] = {}
    return _LLM_CACHES[stage]


def _save_llm_cache(stage: str) -> None:
    """Persist a stage's in-memory cache to disk (atomic-ish via replace)."""
    path = _llm_cache_path(stage)
    tmp = path.with_suffix(".json.tmp")
    save_json(tmp, _LLM_CACHES.get(stage, {}))
    tmp.replace(path)


def _classify_rate_error(err: Exception) -> str:
    """Classify a provider error as ``"daily"``, ``"rate"``, ``"transient"``, or ``"other"``.

    Gemini surfaces both per-minute rate limiting and daily-quota exhaustion as
    HTTP 429 / RESOURCE_EXHAUSTED, so the two are told apart by inspecting the
    message/details for daily-quota markers (e.g. "PerDay", "quota"). A daily
    marker → ``"daily"`` (caller raises :class:`QuotaExhausted`); any other 429
    → ``"rate"`` (caller waits and retries).

    Transient server-side errors (HTTP 500, 502, 503, 504) as well as temporary
    network disruptions, DNS lookup hiccups, socket drops, and connection resets
    clear on their own, so they are classified ``"transient"`` and retried with
    backoff. Anything else → ``"other"``.
    """
    code = getattr(err, "code", None)
    status = str(getattr(err, "status", "") or "")
    text = f"{status} {getattr(err, 'message', '')} {getattr(err, 'details', '')} {err}".lower()

    if code is None:
        m = re.search(r"http\s*(\d{3})", text)
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                pass

    is_429 = code == 429 or "429" in text or "resource_exhausted" in text \
        or "rate limit" in text or "quota" in text
    if not is_429:
        # A hung / slow request that hit the client timeout.
        if "timeout" in text or "timed out" in text or "deadline" in text \
                or "read timed out" in text:
            return "timeout"
        # Transient 5xx server errors, network drops, DNS blips, socket drops:
        # retry with backoff rather than crash.
        network_markers = (
            "temporary failure in name resolution", "name resolution", "gaierror",
            "connection reset", "connection refused", "remote disconnected",
            "network is unreachable", "network unreachable", "no route to host",
            "broken pipe", "ssl", "urlopen error", "failed to connect",
            "connection error", "socket error", "remotedisconnected",
        )
        is_transient = (
            code in (500, 502, 503, 504)
            or any(f"http {c}" in text or f"status {c}" in text for c in ("500", "502", "503", "504"))
            or any(w in text for w in ("503", "502", "504", "500", "unavailable",
                                       "overloaded", "high demand", "internal error",
                                       "try again later", "bad gateway", "gateway timeout"))
            or any(m in text for m in network_markers)
        )
        return "transient" if is_transient else "other"

    # Both per-minute rate limits and daily-quota exhaustion arrive as
    # 429 / RESOURCE_EXHAUSTED, so the generic status word "exhausted" can NOT
    # be used to tell them apart. Discriminate ONLY on explicit per-DAY markers
    # (Gemini uses "...PerDay" / "per day" for the daily cap); everything else
    # 429 is treated as a transient per-minute rate limit that we retry.
    daily_markers = ("perday", "per day", "per-day", "/day", "per_day",
                     "requestsperday", "generaterequestsperday", "daily")
    if any(m in text for m in daily_markers):
        return "daily"
    return "rate"


def _validate_response(text: str, schema):
    """Validate raw response ``text`` against ``schema``.

    Supported schema kinds:
      * a Pydantic ``BaseModel`` subclass → ``model_validate_json`` (markdown
        code-fence tolerant); returns the validated model instance.
      * a callable ``fn(text) -> parsed`` → returns whatever it returns, treating
        a raised exception or a ``None`` return as invalid.

    Returns the parsed/validated object on success, or ``None`` if invalid.
    """
    if not text:
        # Preserve the historical "do not invoke" behavior for ordinary
        # callables and Pydantic schemas. Feedback-enabled callable validators
        # opt in to seeing an empty response so they can explain the correction
        # required on the next schema attempt.
        if callable(schema):
            try:
                if hasattr(schema, _VALIDATION_FEEDBACK_ATTR):
                    return schema("")
            except Exception:
                return None
        return None

    # Strip common ```json / ``` fences the model may wrap JSON in.
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    # Pydantic model?
    try:
        from pydantic import BaseModel
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                return schema.model_validate_json(cleaned)
            except Exception:
                # If the schema expects a wrapper object (e.g. {"mappings": [...]})
                # but the LLM emitted a raw JSON array `[...]`, auto-wrap it into the expected field.
                try:
                    data = json.loads(cleaned)
                    if isinstance(data, list):
                        fields = getattr(schema, "model_fields", {})
                        if len(fields) == 1:
                            wrapper_field = next(iter(fields.keys()))
                            return schema.model_validate({wrapper_field: data})
                        for field_name in ("mappings", "assignments", "items", "subcategories"):
                            if field_name in fields:
                                return schema.model_validate({field_name: data})
                except Exception:
                    pass
                return None
    except ImportError:  # pragma: no cover - pydantic always present here
        pass

    # Callable validator.
    if callable(schema):
        try:
            result = schema(cleaned)
            return result  # None → treated as invalid by caller
        except Exception:
            return None

    # Unknown schema kind → cannot validate; treat as invalid to be safe.
    return None


def _serialize_for_cache(value):
    """Make a validated value JSON-serializable for the cache."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return value


_VALIDATION_FEEDBACK_ATTR = "validation_feedback"
_VALIDATION_FEEDBACK_MAX_CHARS = 6000


def _reset_schema_validation_feedback(schema) -> None:
    """Clear per-attempt callable-validator diagnostics when supported."""
    if not callable(schema):
        return
    try:
        if hasattr(schema, _VALIDATION_FEEDBACK_ATTR):
            setattr(schema, _VALIDATION_FEEDBACK_ATTR, None)
    except Exception:
        # Feedback is optional metadata; a hostile/read-only callable attribute
        # must never change the validation contract.
        pass


def _schema_validation_feedback(schema) -> str | None:
    """Read and bound optional diagnostics exposed by a callable validator."""
    if not callable(schema):
        return None
    try:
        feedback = getattr(schema, _VALIDATION_FEEDBACK_ATTR, None)
    except Exception:
        return None
    if feedback is None:
        return None
    if not isinstance(feedback, str):
        try:
            feedback = json.dumps(
                feedback, ensure_ascii=False, sort_keys=True, default=str
            )
        except Exception:
            feedback = str(feedback)
    feedback = feedback.strip()
    if not feedback:
        return None
    if len(feedback) > _VALIDATION_FEEDBACK_MAX_CHARS:
        feedback = (
            feedback[:_VALIDATION_FEEDBACK_MAX_CHARS]
            + "\n[validation feedback truncated]"
        )
    return feedback


def _schema_retry_prompt(base_prompt: str, feedback: str) -> str:
    """Append bounded validator feedback while preserving the original prompt."""
    return (
        f"{base_prompt}\n\n"
        "CORRECTION REQUIRED AFTER VALIDATION FAILURE:\n"
        "The validator detected the following validation errors. Follow the specific "
        "corrections below to produce a valid output:\n"
        "<validation-feedback>\n"
        f"{feedback}\n"
        "</validation-feedback>\n"
        "Return the COMPLETE response again, including every originally "
        "requested item, as one valid JSON object in exactly the originally "
        "requested format. Do not return commentary, a patch, or only the "
        "corrected items."
    )


def _response_token_counts(response) -> dict[str, int | None]:
    """Extract provider usage counts without making tracing provider-fragile."""
    usage = getattr(response, "usage_metadata", None)
    counts: dict[str, int | None] = {}
    for field in (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "total_token_count",
    ):
        value = getattr(usage, field, None) if usage is not None else None
        try:
            counts[field] = int(value) if value is not None else None
        except (TypeError, ValueError):
            counts[field] = None
    return counts


def call_llm(prompt, cache_key, schema=None, temperature=0, *,
             stage: str = "_llm", model: str | None = None, client=None,
             request_timeout: float | None = None, max_output_tokens: int | None = None):
    """The one guarded LLM entry point (R19, R22).

    Behavior (matches the design's ``call_llm`` contract exactly):
      1. Per-stage JSON cache keyed by ``cache_key``: a cache hit returns
         immediately without any network call (R22.2).
      2. Deterministic settings: ``temperature=0`` and a fixed ``seed`` where the
         provider supports it (R22.1).
      3. HTTP 429 rate limiting → wait with exponential backoff and retry the
         SAME request (R19.3), up to ``LLM_MAX_RATE_RETRIES`` waits.
      4. Daily-quota exhaustion → raise :class:`QuotaExhausted`, a DISTINCT
         signal so the stage can pause cleanly (R19.4).
      5. ``schema`` provided and validation fails → reject-and-retry up to
         ``LLM_MAX_SCHEMA_ATTEMPTS`` times, then raise :class:`MalformedResponse`.
         A callable validator may expose bounded ``validation_feedback``; when
         present it is appended to the original string prompt only for the next
         schema attempt. A malformed/unvalidated response NEVER enters the cache
         or an artifact (R19.2).

    Args:
        prompt: the prompt string (or provider-accepted contents).
        cache_key: stable identity for this unit of work; the cache key.
        schema: optional Pydantic ``BaseModel`` subclass or ``fn(text)->parsed``
            validator. When ``None``, the raw response text is returned.
        temperature: sampling temperature; forced deterministic (default 0).
        stage: cache namespace → ``caches/<stage>/llm_cache.json``.
        model: provider model id; defaults to :data:`GEMINI_MODEL`.
        client: optional pre-built client (used by tests to inject a mock);
            defaults to :func:`get_client`.

    Returns:
        The validated object when ``schema`` is given, else the raw response
        text. On a cache hit with a schema, the cached value is re-validated so
        the return type is consistent across hit/miss.
    """
    cache = _load_llm_cache(stage)

    # 1. Cache hit → return immediately (re-validate so type matches a miss).
    if cache_key in cache:
        cached = cache[cache_key]
        if schema is not None:
            revalidated = _validate_response(
                cached if isinstance(cached, str) else json.dumps(cached), schema
            )
            if revalidated is not None:
                return revalidated
            # Cached value no longer validates (schema changed) → drop & refetch.
            del cache[cache_key]
        else:
            return cached

    client = client or get_client()
    model = model or GEMINI_MODEL
    from google.genai import types

    # Build deterministic config; attach a schema for structured output when the
    # schema is a Pydantic model (lets the provider emit conforming JSON).
    cfg_kwargs = {"temperature": temperature, "seed": LLM_SEED}
    # Cap output length so a degeneration loop fails fast instead of running for
    # minutes and emitting a huge, unparseable response. A caller may pass a
    # tighter per-call cap (e.g. short structured replies).
    _max_tokens = max_output_tokens if max_output_tokens is not None else LLM_MAX_OUTPUT_TOKENS
    if _max_tokens and _max_tokens > 0:
        cfg_kwargs["max_output_tokens"] = _max_tokens
    # Hard per-request timeout (ms) so a slow/hung call can't block the stage.
    # A caller may pass a tighter per-call timeout for fail-fast behavior.
    _timeout = request_timeout if request_timeout is not None else LLM_REQUEST_TIMEOUT
    if _timeout and _timeout > 0:
        cfg_kwargs["http_options"] = types.HttpOptions(
            timeout=int(_timeout * 1000)
        )
    try:
        from pydantic import BaseModel
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            cfg_kwargs["response_mime_type"] = "application/json"
            cfg_kwargs["response_schema"] = schema
    except ImportError:  # pragma: no cover
        pass

    def _build_config(temp):
        return types.GenerateContentConfig(**{**cfg_kwargs, "temperature": temp})

    config = _build_config(temperature)
    # Keep the initial request byte-for-byte identical. Callable validators may
    # supply bounded diagnostics only after rejecting a response; rate/timeout
    # retries always repeat whichever request prompt is currently active.
    base_prompt = prompt
    request_prompt = base_prompt

    schema_attempts = 0
    rate_retries = 0
    attempt_no = 0
    while True:
        # ── one network attempt, with 429 / quota handling ──
        try:
            attempt_no += 1
            if LLM_VERBOSE:
                print(f"      ↳ [api] {stage}:{cache_key} calling {model} "
                      f"(attempt {attempt_no})...", flush=True)
            _t0 = time.monotonic()
            provider = get_llm_provider()
            response = None
            if provider == "ollama":
                text = _call_ollama_api(
                    request_prompt,
                    schema=schema,
                    temperature=temperature,
                    timeout=_timeout if _timeout and _timeout > 0 else 120.0
                )
            else:
                response = client.models.generate_content(
                    model=model, contents=request_prompt, config=config
                )
                text = getattr(response, "text", "") or ""
            _elapsed = time.monotonic() - _t0
            if LLM_VERBOSE:
                print(f"      ↳ [api] {stage}:{cache_key} responded in "
                      f"{_elapsed:.1f}s ({len(text)} chars).",
                      flush=True)
            # Trace the raw request + response of this attempt (finish reason and
            # token accounting included so hidden reasoning / truncation can be
            # distinguished from an empty model answer).
            _finish = None
            try:
                _finish = str(response.candidates[0].finish_reason)
            except Exception:
                pass
            _token_counts = _response_token_counts(response)
            _trace_llm({
                "stage": stage, "cache_key": cache_key, "attempt": attempt_no,
                "outcome": "response", "elapsed_s": round(_elapsed, 1),
                "resp_chars": len(text), "finish_reason": _finish,
                "temperature": config.temperature, "model": model,
                "effective_max_output_tokens": (
                    int(_max_tokens) if _max_tokens and _max_tokens > 0 else None
                ),
                **_token_counts,
                "prompt": request_prompt, "response": text,
            })
        except QuotaExhausted:
            raise
        except Exception as e:
            kind = _classify_rate_error(e)
            _trace_llm({
                "stage": stage, "cache_key": cache_key, "attempt": attempt_no,
                "outcome": f"error:{kind}", "error": repr(e),
                "elapsed_s": round(time.monotonic() - _t0, 1),
                "temperature": config.temperature, "model": model,
                "effective_max_output_tokens": (
                    int(_max_tokens) if _max_tokens and _max_tokens > 0 else None
                ),
                "prompt_token_count": None,
                "candidates_token_count": None,
                "thoughts_token_count": None,
                "total_token_count": None,
                "prompt": request_prompt,
            })
            if kind == "daily":
                raise QuotaExhausted(
                    f"Daily LLM quota exhausted on stage '{stage}': {e}"
                ) from e
            if kind == "timeout":
                # A hung/slow call (often a degeneration loop). Don't repeat the
                # identical deterministic request — nudge temperature to break
                # the loop, then retry (counts against the rate-retry budget).
                if rate_retries >= LLM_MAX_RATE_RETRIES:
                    raise RuntimeError(
                        f"Request kept timing out after {rate_retries} retries "
                        f"on stage '{stage}' (configured deadline "
                        f"{_timeout:.0f}s): {e}"
                    ) from e
                print(f"[call_llm] request hit its configured "
                      f"{_timeout:.0f}s deadline (stage={stage}); nudging "
                      f"temperature and retrying "
                      f"({rate_retries + 1}/{LLM_MAX_RATE_RETRIES}).")
                rate_retries += 1
                config = _build_config(min(0.6, 0.2 * rate_retries))
                continue
            if kind in ("rate", "transient"):
                if rate_retries >= LLM_MAX_RATE_RETRIES:
                    raise RuntimeError(
                        f"Still failing after {rate_retries} backoff "
                        f"retries on stage '{stage}' ({kind}): {e}"
                    ) from e
                wait = min(LLM_BACKOFF_BASE * (2 ** rate_retries), LLM_BACKOFF_CAP)
                reason = ("429 rate-limited" if kind == "rate"
                          else f"transient server/network error ({e})")
                print(f"[call_llm] {reason} (stage={stage}); backing off "
                      f"{wait:.0f}s then retrying same request "
                      f"({rate_retries + 1}/{LLM_MAX_RATE_RETRIES}).")
                time.sleep(wait)
                rate_retries += 1
                continue  # retry the SAME request
            raise  # not a rate/quota/transient error → propagate

        # ── schema validation (reject-and-retry) ──
        if schema is not None:
            _reset_schema_validation_feedback(schema)
            parsed = _validate_response(text, schema)
            if parsed is None:
                schema_attempts += 1
                validation_feedback = _schema_validation_feedback(schema)
                _trace_llm({
                    "stage": stage, "cache_key": cache_key, "attempt": attempt_no,
                    "outcome": "malformed", "schema_attempt": schema_attempts,
                    "resp_chars": len(text), "finish_reason": _finish,
                    "effective_max_output_tokens": (
                        int(_max_tokens)
                        if _max_tokens and _max_tokens > 0 else None
                    ),
                    **_token_counts,
                    "validation_feedback": validation_feedback,
                    "prompt": request_prompt,
                    "response": text,
                })
                if schema_attempts < LLM_MAX_SCHEMA_ATTEMPTS:
                    print(f"[call_llm] malformed response (stage={stage}); "
                          f"reject-and-retry "
                          f"{schema_attempts}/{LLM_MAX_SCHEMA_ATTEMPTS} "
                          f"({len(text)} chars).")
                    # At temperature 0 + fixed seed, an identical retry can
                    # reproduce the SAME malformed/degenerate output. Nudge the
                    # temperature up on each schema retry to break the loop while
                    # keeping the first attempt fully deterministic (R22.1).
                    config = _build_config(min(0.4, 0.2 * schema_attempts))
                    rate_retries = 0
                    request_prompt = base_prompt
                    if (validation_feedback
                            and isinstance(base_prompt, str)):
                        request_prompt = _schema_retry_prompt(
                            base_prompt, validation_feedback
                        )
                    continue
                # Never cache/return a malformed response.
                raise MalformedResponse(
                    f"LLM response failed schema validation after "
                    f"{LLM_MAX_SCHEMA_ATTEMPTS} attempts on stage '{stage}'."
                )
            # valid → cache the serializable form, return the parsed object.
            cache[cache_key] = _serialize_for_cache(parsed)
            _save_llm_cache(stage)
            return parsed

        # No schema → cache and return raw text.
        cache[cache_key] = text
        _save_llm_cache(stage)
        return text


# ── Shared JSON salvage parser (deduped from the 9 S09 QA scripts) — R6.1 ──
# Every legacy QA script (routing_targets, assign_parents_to_targets,
# rescue_floating_concepts, resubdivide_promoted_targets, onto_health_refinement,
# llm_node_validator, llm_issue_fixer) shipped its OWN copy of a "best-effort"
# JSON extractor. They are merged here into one shared helper so S09 (and any
# future stage) parses semi-structured LLM output the same way. It is written to
# double as a :func:`call_llm` ``schema`` validator: it returns the parsed object
# on success and ``None`` on total failure, so a malformed response is
# reject-and-retried and never enters the cache/artifact (R19.2).
def safe_parse_json(text):
    """Salvage a JSON object/array from an LLM ``text`` response.

    Tries, in order: strip ```` ```json ```` / ```` ``` ```` fences then a direct
    ``json.loads``; the outermost ``{...}`` slice; the outermost ``[...]`` slice.
    Returns the parsed value (``dict`` or ``list`` — possibly empty) on success,
    or ``None`` when nothing parseable is found.

    Returning ``None`` (not ``{}``) on failure is deliberate: it lets this helper
    be passed straight to :func:`call_llm` as a ``schema`` callable, where a
    ``None`` return marks the response invalid and triggers reject-and-retry. A
    successfully parsed but *empty* ``{}`` is a VALID result (the caller applies
    its own per-item fallback), matching the legacy scripts' behaviour.
    """
    if not text:
        return None

    # Strip common markdown code fences the model may wrap JSON in.
    cleaned = re.sub(r"^```(?:json)?\s*", "", str(text).strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    # 1. direct parse of the cleaned text.
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 2. outermost {...} object slice.
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1 and start < end:
        try:
            return json.loads(cleaned[start:end + 1])
        except Exception:
            pass

    # 3. outermost [...] array slice.
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end != -1 and start < end:
        try:
            return json.loads(cleaned[start:end + 1])
        except Exception:
            pass

    return None


# ── Resumable per-item map + promote-on-complete (R8, R19.5, R19.6) ──
# Long-running LLM stages (S05, S08, S09 sub-steps) process MANY items, each an
# expensive guarded LLM call. Two invariants make them safe to interrupt:
#
#   * resumable_map()  — per-item work is cached under caches/<stage>/ keyed by a
#     STABLE per-item key. A re-run skips every already-cached item and calls the
#     work function exactly once per not-yet-cached item (R8.2, R19.5). If the
#     work raises QuotaExhausted mid-run, the checkpoint is flushed to disk and
#     the pause propagates cleanly — no completed work is lost.
#
#   * run_resumable_stage() — the promote-on-complete wrapper: it only calls
#     output_path + write_manifest AFTER every item completes (R8.4, R19.6). A
#     QuotaExhausted pause writes NO primary artifact, prints a
#     "paused — resume later" message, and exits without error (a pause is
#     distinct from a failure). The checkpoint (caches/<stage>/) survives so the
#     next run resumes exactly where it left off.
#
# The map checkpoint lives in its own file (map_cache.json) so it never collides
# with the LLM response cache (llm_cache.json) a stage may also keep.

# The map checkpoint is deliberately NOT memoized in-process: resumable_map reads
# it fresh from disk on every call and rewrites it after each completed item.
# This keeps the on-disk checkpoint the single source of truth, so deleting it
# (R8.3) makes the very next call recompute cleanly instead of serving a stale
# in-memory copy.


def _map_cache_path(stage: str) -> Path:
    """Location of a stage's resumable-map checkpoint: caches/<stage>/map_cache.json."""
    d = CACHES / stage
    d.mkdir(parents=True, exist_ok=True)
    return d / "map_cache.json"


def _load_map_cache(stage: str) -> dict:
    """Load a stage's on-disk map checkpoint (empty dict if absent/corrupt).

    Always reads from disk (no memoization) so a deleted checkpoint (R8.3) forces
    a clean recompute on the next call rather than serving a stale copy.
    """
    path = _map_cache_path(stage)
    if path.is_file():
        try:
            return load_json(path)
        except Exception:  # corrupt checkpoint → start clean rather than crash
            return {}
    return {}


def _save_map_cache(stage: str, cache: dict) -> None:
    """Persist a stage's map checkpoint to disk (atomic-ish via replace)."""
    path = _map_cache_path(stage)
    tmp = path.with_suffix(".json.tmp")
    save_json(tmp, cache)
    tmp.replace(path)


def item_key(item) -> str:
    """Stable per-item cache key derived from the item's content.

    JSON-serializes the item with sorted keys (falling back to ``repr`` for
    non-serializable items) and returns the first 16 hex chars of its SHA-256.
    Deterministic: the same item content always yields the same key, so a re-run
    finds its prior result. Callers that already have a natural stable id (e.g. a
    concept URI) should pass their own ``key`` function to :func:`resumable_map`.
    """
    try:
        blob = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        blob = repr(item)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# Alias for content-based hashing of arbitrary Python structures
content_hash = item_key


def resumable_map(stage: str, items, fn, *, key=None) -> list:
    """Apply ``fn`` to each item, caching every result under ``caches/<stage>/``.

    The resumable core of every long LLM stage (R8, R19.5). Behavior:
      * a STABLE key per item (``key(item)``, default :func:`item_key`) indexes a
        JSON checkpoint at ``caches/<stage>/map_cache.json``,
      * an item already in the checkpoint is SKIPPED — ``fn`` is NOT called for it
        (resume idempotence, R8.2 / R19.5),
      * ``fn`` is called exactly once per not-yet-cached item; its result is
        written to the checkpoint immediately so an interrupt loses nothing,
      * :class:`QuotaExhausted` raised by ``fn`` flushes the checkpoint and
        propagates unchanged, so the caller (see :func:`run_resumable_stage`) can
        pause cleanly.

    Args:
        stage: cache namespace → ``caches/<stage>/map_cache.json``.
        items: iterable of work items (consumed once).
        fn: ``fn(item) -> result``; result must be JSON-serializable (Pydantic
            models are dumped via ``model_dump`` before caching).
        key: optional ``key(item) -> str`` for a natural stable id; defaults to
            :func:`item_key` (content hash).

    Returns:
        list: results in item order, equal to a from-scratch run's results.
    """
    keyfn = key or item_key
    cache = _load_map_cache(stage)
    results = []
    try:
        for item in items:
            k = keyfn(item)
            if k in cache:
                results.append(cache[k])         # resume: skip completed work
                continue
            value = fn(item)                     # exactly one call per new item
            stored = _serialize_for_cache(value)
            cache[k] = stored
            _save_map_cache(stage, cache)         # checkpoint immediately
            results.append(stored)
    except QuotaExhausted:
        # Pause, not failure: flush what completed and let the caller handle it.
        _save_map_cache(stage, cache)
        raise
    return results


def run_resumable_stage(stage: str, caller_file: str, items, fn, *,
                        key=None, build_output=None, ext: str = "json",
                        in_path=None, counts: dict | None = None,
                        extra: dict | None = None,
                        exit_on_pause: bool = True):
    """Promote-on-complete wrapper around :func:`resumable_map` (R8.4, R19.6).

    Runs ``fn`` over ``items`` with per-item resume, then — ONLY if every item
    completed — promotes the checkpoint to a NEW versioned artifact via
    :func:`output_path` and records a :func:`write_manifest` line. This is the
    "an artifact exists iff all items completed" guarantee (Property 6).

    On :class:`QuotaExhausted` mid-run: NO primary artifact is written, a
    ``paused — resume later`` message is printed, and the stage exits without
    error (a pause is distinct from a failure, R19.4). The checkpoint under
    ``caches/<stage>/`` survives so the next run resumes where it left off.

    Args:
        stage / caller_file: the stage name and its ``__file__`` (for the code
            hash embedded in the output path).
        items / fn / key: forwarded to :func:`resumable_map`.
        build_output: optional ``build_output(results) -> payload`` to shape the
            artifact body; defaults to the raw results list.
        ext / in_path / counts / extra: forwarded to :func:`output_path` /
            :func:`write_manifest`.
        exit_on_pause: when True (default, real-stage behavior) a pause calls
            ``sys.exit(0)``; tests pass False to receive ``None`` instead and
            assert on the "no artifact + non-empty checkpoint" state.

    Returns:
        Path: the new artifact path on completion; ``None`` on a pause when
        ``exit_on_pause`` is False.
    """
    try:
        results = resumable_map(stage, items, fn, key=key)
    except QuotaExhausted as e:
        # Paused, not failed: no primary artifact, checkpoint left intact.
        print(f"[{stage}] paused — resume later (daily LLM quota exhausted). "
              f"Progress is checkpointed in {CACHES / stage}; re-run this stage "
              f"to continue where it left off. ({e})")
        if exit_on_pause:
            sys.exit(0)
        return None

    payload = build_output(results) if build_output is not None else results
    out_path = output_path(stage, caller_file, ext=ext)
    save_json(out_path, payload)
    write_manifest(stage, caller_file, in_path, out_path,
                   counts=counts, extra=extra)
    return out_path
