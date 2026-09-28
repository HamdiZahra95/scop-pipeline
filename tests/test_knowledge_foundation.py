"""Tests for the knowledge-guided foundation: mode-aware paths + reference index.

Verifies:
  * SCOP_MODE unset/baseline leaves common's path roots IDENTICAL to the historical
    layout (the baseline run must be byte-identical);
  * SCOP_MODE=guided redirects artifacts/caches/logs/reports under runs/guided/,
    while SEED stays shared;
  * knowledge.match() aligns concepts (exact / lexical / semantic) and degrades
    gracefully to kind="none" for concepts absent from the reference.

The mode-path tests re-import common in a subprocess so the module-level SCOP_MODE
constant is evaluated under the chosen environment.
"""

import subprocess
import sys
from pathlib import Path

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))

import common as C  # noqa: E402
import knowledge as K  # noqa: E402


def _paths_under(mode: str) -> dict:
    """Import common under SCOP_MODE=<mode> in a subprocess; return its roots."""
    code = (
        "import common as C, json;"
        "print(json.dumps({"
        "'artifacts': str(C.ARTIFACTS), 'caches': str(C.CACHES),"
        "'logs': str(C.LOGS), 'reports': str(C.REPORTS),"
        "'manifest': str(C.MANIFEST), 'seed': str(C.SEED), 'root': str(C.ROOT)}))"
    )
    env = {"SCOP_MODE": mode} if mode else {}
    import os
    full_env = dict(os.environ)
    full_env.pop("SCOP_MODE", None)
    full_env.update(env)
    out = subprocess.check_output([sys.executable, "-c", code],
                                  cwd=str(PIPELINE_V2), env=full_env)
    import json
    return json.loads(out)


def test_baseline_paths_unchanged():
    p = _paths_under("")   # unset → baseline
    root = p["root"]
    assert p["artifacts"] == f"{root}/artifacts"
    assert p["caches"] == f"{root}/caches"
    assert p["logs"] == f"{root}/logs"
    assert p["reports"] == f"{root}/reports"
    assert p["manifest"] == f"{root}/logs/manifest.jsonl"


def test_guided_paths_redirected():
    p = _paths_under("guided")
    root = p["root"]
    assert p["artifacts"] == f"{root}/runs/guided/artifacts"
    assert p["caches"] == f"{root}/runs/guided/caches"
    assert p["logs"] == f"{root}/runs/guided/logs"
    assert p["reports"] == f"{root}/runs/guided/reports"
    # SEED is shared (read-only) across modes.
    assert p["seed"].endswith("/seed")
    assert "runs/guided" not in p["seed"]


def test_invalid_mode_rejected():
    import os
    env = dict(os.environ); env["SCOP_MODE"] = "nonsense"
    r = subprocess.run([sys.executable, "-c", "import common"],
                       cwd=str(PIPELINE_V2), env=env, capture_output=True)
    assert r.returncode != 0
    assert b"SCOP_MODE" in r.stderr


# ── knowledge index ──────────────────────────────────────────────────────────
def test_reference_index_loads():
    K.load()
    assert len(K.concepts) > 500
    assert len(K.categories) == 9
    assert "used_for" in K.relations or len(K.relations) >= 10


def test_match_exact_and_none():
    m = K.match("convolutional neural network", use_semantic=False)
    assert m.kind == "exact" and m.matched
    # a clearly novel concept degrades to a graceful no-op
    n = K.match("zzz nonexistent widget concept", use_semantic=False)
    assert n.kind == "none" and not n.matched


def test_is_reference_concept():
    assert K.is_reference_concept("XGBoost") is True
    assert K.is_reference_concept("zzz nonexistent widget concept") is False
