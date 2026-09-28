"""Unit tests for resumable_map + run_resumable_stage (Task 7.1).

Covers the two correctness properties this infrastructure must uphold:
  * resume idempotence (R8.2 / R19.5): resumable_map calls fn exactly once per
    not-yet-cached item and zero times for cached items; the final result set
    equals a from-scratch run.
  * promote-on-complete atomicity (R8.4 / R19.6): a primary artifact exists iff
    all items completed; a QuotaExhausted mid-run leaves zero primary artifacts
    but a non-empty checkpoint.

Also covers R8.1 (cache location) and R8.3 (deleting the cache forces a clean
recompute).

Run:  pytest test_result/pipeline_v2/tests/test_common_resumable.py
"""

import sys
from pathlib import Path

import pytest

# Make the pipeline_v2 dir importable so `import common` works regardless of the
# pytest invocation directory.
PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))

import common as C  # noqa: E402


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect CACHES / ARTIFACTS / MANIFEST to a temp dir for test isolation.

    Every helper under test reads these module-level paths, so pointing them at
    tmp_path keeps tests hermetic and leaves the real project tree untouched.
    """
    caches = tmp_path / "caches"
    artifacts = tmp_path / "artifacts"
    logs = tmp_path / "logs"
    for d in (caches, artifacts, logs):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(C, "CACHES", caches)
    monkeypatch.setattr(C, "ARTIFACTS", artifacts)
    monkeypatch.setattr(C, "MANIFEST", logs / "manifest.jsonl")
    return tmp_path


# ── resumable_map: resume idempotence (Property 5, R8.2 / R19.5) ───────────
def test_resumable_map_calls_fn_once_per_item_fresh_run(isolated_dirs):
    """A from-scratch run calls fn exactly once per item, in order."""
    calls = []

    def fn(x):
        calls.append(x)
        return x * 10

    items = [1, 2, 3]
    results = C.resumable_map("s_map_fresh", items, fn)

    assert results == [10, 20, 30]
    assert calls == [1, 2, 3]          # exactly once per item


def test_resumable_map_skips_cached_items_on_rerun(isolated_dirs):
    """A re-run calls fn ZERO times for already-cached items."""
    def fn_first(x):
        return x * 10

    C.resumable_map("s_map_resume", [1, 2, 3], fn_first)

    # Second run over the same items: fn must never be called.
    calls = []

    def fn_second(x):
        calls.append(x)
        return x * 999  # would differ if (wrongly) recomputed

    results = C.resumable_map("s_map_resume", [1, 2, 3], fn_second)

    assert calls == []                 # zero calls for cached items
    assert results == [10, 20, 30]     # served from checkpoint


def test_resumable_map_partial_resume_only_new_items(isolated_dirs):
    """After a partial run, only not-yet-cached items invoke fn (R19.5)."""
    C.resumable_map("s_map_partial", [1, 2], lambda x: x * 10)

    calls = []

    def fn(x):
        calls.append(x)
        return x * 10

    results = C.resumable_map("s_map_partial", [1, 2, 3, 4], fn)

    assert calls == [3, 4]             # only the new items
    assert results == [10, 20, 30, 40]


def test_resumable_map_result_equals_from_scratch(isolated_dirs):
    """Resumed result set equals a from-scratch run's result set (Property 5)."""
    items = ["a", "b", "c", "d"]

    def fn(x):
        return x.upper()

    # From-scratch reference run in its own stage namespace.
    reference = C.resumable_map("s_map_ref", items, fn)

    # Interrupted-then-resumed run in a second namespace.
    C.resumable_map("s_map_interrupted", items[:2], fn)
    resumed = C.resumable_map("s_map_interrupted", items, fn)

    assert resumed == reference == ["A", "B", "C", "D"]


# ── R8.1 cache location + R8.3 delete-to-recompute ─────────────────────────
def test_checkpoint_lives_under_caches_stage(isolated_dirs):
    """The checkpoint is written under caches/<stage>/ (R8.1)."""
    C.resumable_map("s_map_loc", [1], lambda x: x)
    checkpoint = C.CACHES / "s_map_loc" / "map_cache.json"
    assert checkpoint.is_file()


def test_deleting_cache_forces_clean_recompute(isolated_dirs):
    """Deleting the checkpoint causes fn to run again on the next call (R8.3)."""
    calls = []

    def fn(x):
        calls.append(x)
        return x * 10

    C.resumable_map("s_map_delete", [1, 2], fn)
    assert calls == [1, 2]

    # Remove the checkpoint → next run must recompute everything.
    (C.CACHES / "s_map_delete" / "map_cache.json").unlink()

    calls.clear()
    results = C.resumable_map("s_map_delete", [1, 2], fn)
    assert calls == [1, 2]             # recomputed cleanly
    assert results == [10, 20]


# ── QuotaExhausted propagation + checkpoint survival ───────────────────────
def test_quota_exhausted_propagates_and_flushes_checkpoint(isolated_dirs):
    """A QuotaExhausted mid-run propagates and leaves completed work cached."""
    def fn(x):
        if x == 3:
            raise C.QuotaExhausted("daily quota spent")
        return x * 10

    with pytest.raises(C.QuotaExhausted):
        C.resumable_map("s_map_quota", [1, 2, 3, 4], fn)

    # Items 1 and 2 completed before the pause → checkpoint is non-empty.
    checkpoint = C.load_json(C.CACHES / "s_map_quota" / "map_cache.json")
    assert len(checkpoint) == 2
    assert set(checkpoint.values()) == {10, 20}

    # Resuming skips the two completed items and only retries from item 3.
    calls = []

    def fn_resume(x):
        calls.append(x)
        return x * 10

    results = C.resumable_map("s_map_quota", [1, 2, 3, 4], fn_resume)
    assert calls == [3, 4]             # completed items never repeated (R19.5)
    assert results == [10, 20, 30, 40]


# ── run_resumable_stage: promote-on-complete atomicity (Property 6) ────────
def _stage_artifacts(stage):
    d = C.ARTIFACTS / stage
    return sorted(d.glob("*.json")) if d.exists() else []


def test_promote_on_complete_writes_one_artifact_and_manifest(isolated_dirs):
    """Full completion → exactly one artifact + one manifest line (R19.6)."""
    out = C.run_resumable_stage(
        "s_stage_ok", __file__, [1, 2, 3], lambda x: x * 10,
        exit_on_pause=False,
    )

    assert out is not None
    artifacts = _stage_artifacts("s_stage_ok")
    assert len(artifacts) == 1
    assert artifacts[0] == out
    assert C.load_json(out) == [10, 20, 30]

    # Exactly one manifest line for this stage.
    manifest_lines = [
        ln for ln in C.MANIFEST.read_text().splitlines() if '"s_stage_ok"' in ln
    ]
    assert len(manifest_lines) == 1


def test_promote_on_complete_respects_build_output(isolated_dirs):
    """build_output shapes the promoted artifact body."""
    out = C.run_resumable_stage(
        "s_stage_shaped", __file__, [1, 2], lambda x: x,
        build_output=lambda results: {"items": results, "n": len(results)},
        exit_on_pause=False,
    )
    assert C.load_json(out) == {"items": [1, 2], "n": 2}


def test_pause_writes_no_artifact_but_keeps_checkpoint(isolated_dirs):
    """A pause writes ZERO primary artifacts but a non-empty checkpoint (Property 6)."""
    def fn(x):
        if x == 2:
            raise C.QuotaExhausted("paused")
        return x * 10

    result = C.run_resumable_stage(
        "s_stage_paused", __file__, [1, 2, 3], fn,
        exit_on_pause=False,
    )

    assert result is None                       # pause, not completion
    assert _stage_artifacts("s_stage_paused") == []   # no primary artifact

    # Checkpoint retains the one completed item so the next run resumes.
    checkpoint = C.load_json(C.CACHES / "s_stage_paused" / "map_cache.json")
    assert len(checkpoint) == 1
    assert list(checkpoint.values()) == [10]

    # No manifest line was written for a paused stage.
    manifest_lines = (
        [ln for ln in C.MANIFEST.read_text().splitlines()
         if '"s_stage_paused"' in ln]
        if C.MANIFEST.exists() else []
    )
    assert manifest_lines == []


def test_pause_then_resume_completes_and_promotes(isolated_dirs):
    """After a pause, a resume completes all items and promotes exactly once."""
    state = {"fail": True}

    def fn(x):
        if x == 3 and state["fail"]:
            raise C.QuotaExhausted("paused first time")
        return x * 10

    # First run pauses at item 3 → no artifact.
    first = C.run_resumable_stage(
        "s_stage_resume", __file__, [1, 2, 3, 4], fn, exit_on_pause=False,
    )
    assert first is None
    assert _stage_artifacts("s_stage_resume") == []

    # Second run: quota restored → completes and promotes.
    state["fail"] = False
    calls = []

    def fn2(x):
        calls.append(x)
        return x * 10

    out = C.run_resumable_stage(
        "s_stage_resume", __file__, [1, 2, 3, 4], fn2, exit_on_pause=False,
    )
    assert out is not None
    assert calls == [3, 4]                      # items 1,2 never repeated
    assert C.load_json(out) == [10, 20, 30, 40]
    assert len(_stage_artifacts("s_stage_resume")) == 1


def test_pause_exits_zero_without_error_when_exit_on_pause(isolated_dirs):
    """Real-stage behavior: a pause calls sys.exit(0) (clean, non-error exit)."""
    def fn(x):
        raise C.QuotaExhausted("paused")

    with pytest.raises(SystemExit) as ei:
        C.run_resumable_stage("s_stage_exit", __file__, [1], fn)
    assert ei.value.code == 0
