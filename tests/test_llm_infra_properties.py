"""Property-based tests for the LLM infrastructure in common.py (Task 7.2).

Framework: Hypothesis (design.md "Testing Strategy" — PBT is appropriate for the
common.py invariants). Each test maps to a numbered Correctness Property from the
design's "Correctness Properties" section:

  * Property 5 — Resume idempotence            (Requirements 8.2, 19.5)
  * Property 6 — Promote-on-complete atomicity (Requirements 8.4, 19.4, 19.6)
  * Property 7 — Guard soundness               (Requirements 19.2)

The LLM client is ALWAYS mocked (see :class:`FakeClient`): every test is fully
offline and deterministic — no real network / API calls are made. Responses are
served from a caller-supplied queue, and provider errors (daily-quota / 429) are
simulated by raising exceptions the real ``call_llm`` would classify identically.

Because Hypothesis does not reset function-scoped pytest fixtures between
generated inputs, each property manages its own temp directory and patches
``common``'s module globals (CACHES, ARTIFACTS, MANIFEST) via the ``sandbox``
context manager below, restoring them afterwards. The module-level LLM client and
cache singletons are cleared per example so no state leaks between inputs.

Run:  pytest test_result/pipeline_v2/tests/test_llm_infra_properties.py
"""

import contextlib
import json
import sys
import tempfile
import types as _pytypes
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

# Make the pipeline_v2 dir importable so `import common` works regardless of the
# pytest invocation directory.
PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))

import common as C  # noqa: E402


# ── Mocked LLM client (no network, fully deterministic) ─────────────────────
class _DailyQuotaError(Exception):
    """A provider error whose message ``call_llm`` classifies as daily quota.

    ``common._classify_rate_error`` inspects the stringified error for per-DAY
    markers (e.g. ``GenerateRequestsPerDay``). Raising this from the mock's
    ``generate_content`` therefore drives ``call_llm`` to raise QuotaExhausted,
    exactly as a real daily-cap 429 would.
    """
    def __init__(self):
        super().__init__(
            "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
            "'GenerateRequestsPerDay' (per day)."
        )


class _FakeModels:
    """Stand-in for ``client.models`` exposing ``generate_content``."""

    def __init__(self, responder):
        self._responder = responder

    def generate_content(self, *, model, contents, config):  # noqa: D401
        return self._responder(model=model, contents=contents, config=config)


class FakeClient:
    """A mocked ``google.genai`` client.

    ``responder(model, contents, config)`` returns either a raw response object
    exposing ``.text`` OR raises an exception (to simulate quota / rate errors).
    """

    def __init__(self, responder):
        self.models = _FakeModels(responder)


def _resp(text):
    """A minimal response object mirroring the provider's ``.text`` attribute."""
    return _pytypes.SimpleNamespace(text=text)


def queue_responder(texts):
    """Serve ``texts`` in order; repeat the last once exhausted.

    Each entry is either a string (returned as ``.text``) or an Exception
    instance/class (raised) — letting a single mock emit a valid response, a
    malformed one, or a provider error on demand.
    """
    box = {"i": 0}

    def responder(*, model, contents, config):
        i = min(box["i"], len(texts) - 1)
        box["i"] += 1
        item = texts[i]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item()
        return _resp(item)

    return responder


# ── Sandbox: isolate a generated example ────────────────────────────────────
@contextlib.contextmanager
def sandbox():
    """Fresh temp dir + patched common globals + cleared LLM singletons.

    Restores everything on exit so no real pipeline output is touched and
    examples never leak state into one another.
    """
    saved = {
        "CACHES": C.CACHES,
        "ARTIFACTS": C.ARTIFACTS,
        "MANIFEST": C.MANIFEST,
        "_LLM_CLIENT": C._LLM_CLIENT,
        "_LLM_CACHES": C._LLM_CACHES,
    }
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        try:
            C.CACHES = base / "caches"
            C.ARTIFACTS = base / "artifacts"
            C.MANIFEST = base / "logs" / "manifest.jsonl"
            for d in (C.CACHES, C.ARTIFACTS, C.MANIFEST.parent):
                d.mkdir(parents=True, exist_ok=True)
            # Force fresh, empty per-stage caches for this example.
            C._LLM_CLIENT = None
            C._LLM_CACHES = {}
            yield base
        finally:
            C.CACHES = saved["CACHES"]
            C.ARTIFACTS = saved["ARTIFACTS"]
            C.MANIFEST = saved["MANIFEST"]
            C._LLM_CLIENT = saved["_LLM_CLIENT"]
            C._LLM_CACHES = saved["_LLM_CACHES"]


# ── Schema used by the guarded-call tests ───────────────────────────────────
class NumberModel(BaseModel):
    """Trivial schema: a single integer field. Guards call_llm's structured
    output so we can generate clearly valid vs invalid responses."""
    value: int


def _valid_text(n: int) -> str:
    return json.dumps({"value": n})


# Texts that MUST fail NumberModel validation (missing / wrong-typed field, or
# not JSON at all). These stand in for malformed LLM responses.
_INVALID_TEXTS = [
    "",                       # empty
    "not json at all",       # unparseable
    "{}",                    # missing required field
    '{"value": "not-int"}',  # wrong type
    '{"other": 1}',          # wrong field
    "[1, 2, 3]",             # wrong shape
]


# ════════════════════════════════════════════════════════════════════════════
# Property 5: Resume idempotence
# For any partition of items into "already cached" and "remaining", resumable_map
# calls the work function exactly once per not-yet-cached item and zero times for
# cached items, and the final result set equals a from-scratch run.
# **Validates: Requirements 8.2, 19.5**
# ════════════════════════════════════════════════════════════════════════════
@settings(max_examples=200, deadline=None)
@given(
    spec=st.lists(
        st.tuples(st.integers(min_value=-1000, max_value=1000), st.booleans()),
        min_size=0, max_size=30, unique_by=lambda t: t[0],
    ),
)
def test_property5_resume_idempotence(spec):
    with sandbox():
        items = [v for v, _cached in spec]
        pre_cached = [v for v, cached in spec if cached]

        stage = "s_prop5"

        def work(x):
            return x * 10

        # Seed the checkpoint with the "already cached" partition (a prior run).
        C.resumable_map(stage, pre_cached, work)

        # Now run over the FULL item list with a counting work function.
        calls = []

        def counting_work(x):
            calls.append(x)
            return x * 10

        results = C.resumable_map(stage, items, counting_work)

        # fn is called exactly once per not-yet-cached item, zero for cached.
        expected_calls = [x for x in items if x not in set(pre_cached)]
        assert calls == expected_calls

        # Final result set equals a from-scratch run (own namespace).
        from_scratch = C.resumable_map("s_prop5_ref", items, work)
        assert results == from_scratch == [x * 10 for x in items]


# ════════════════════════════════════════════════════════════════════════════
# Property 6: Promote-on-complete atomicity
# An artifact for an LLM stage exists iff all items completed; a QuotaExhausted
# mid-run leaves zero primary artifacts and a non-empty checkpoint.
# Generator: inject pause at a random item index (via a mocked client that raises
# a daily-quota error on that item).
# **Validates: Requirements 8.4, 19.4, 19.6**
# ════════════════════════════════════════════════════════════════════════════
def _stage_artifacts(stage):
    d = C.ARTIFACTS / stage
    return sorted(d.glob("*.json")) if d.exists() else []


def _manifest_lines_for(stage):
    if not C.MANIFEST.exists():
        return []
    return [ln for ln in C.MANIFEST.read_text().splitlines()
            if f'"{stage}"' in ln]


@settings(max_examples=150, deadline=None)
@given(
    n_items=st.integers(min_value=1, max_value=12),
    # pause_at in [0, n_items): pause before completing that item.
    # pause_at == n_items (or beyond): no pause → full completion.
    pause_at=st.integers(min_value=0, max_value=12),
)
def test_property6_promote_on_complete_atomicity(n_items, pause_at):
    with sandbox():
        items = list(range(n_items))
        stage = "s_prop6"
        will_pause = pause_at < n_items

        # Mocked client: returns a valid schema response for every item EXCEPT
        # the pause item, for which it raises a daily-quota error.
        def responder(*, model, contents, config):
            # contents carries the item index we encoded into the prompt.
            idx = int(str(contents).rsplit("#", 1)[-1])
            if will_pause and idx == pause_at:
                raise _DailyQuotaError()
            return _resp(_valid_text(idx * 10))

        client = FakeClient(responder)

        def work(item):
            return C.call_llm(
                prompt=f"item#{item}", cache_key=str(item),
                schema=NumberModel, stage=stage, client=client,
            )

        out = C.run_resumable_stage(
            stage, __file__, items, work, exit_on_pause=False,
        )

        artifacts = _stage_artifacts(stage)
        checkpoint_path = C.CACHES / stage / "map_cache.json"

        if will_pause:
            # Pause → NO primary artifact, NO manifest line.
            assert out is None
            assert artifacts == []
            assert _manifest_lines_for(stage) == []
            # Non-empty checkpoint holding exactly the items completed before
            # the pause (items 0..pause_at-1).
            assert checkpoint_path.is_file()
            checkpoint = C.load_json(checkpoint_path)
            assert len(checkpoint) == pause_at
        else:
            # Full completion → exactly one artifact + exactly one manifest line.
            assert out is not None
            assert len(artifacts) == 1
            assert artifacts[0] == out
            assert len(_manifest_lines_for(stage)) == 1
            # Artifact body equals every item's completed result, in order.
            assert C.load_json(out) == [{"value": i * 10} for i in items]

        # Biconditional restated: an artifact exists IFF all items completed.
        assert (len(artifacts) == 1) == (not will_pause)


# ════════════════════════════════════════════════════════════════════════════
# Property 7: Guard soundness
# No value that fails schema validation is ever present in a stage's output or
# cache. Generator: random valid/invalid LLM responses.
# **Validates: Requirements 19.2**
# ════════════════════════════════════════════════════════════════════════════
# A response element is either a validity flag we turn into a concrete text.
_response_element = st.one_of(
    st.integers(min_value=-1000, max_value=1000).map(lambda n: ("valid", n)),
    st.sampled_from(_INVALID_TEXTS).map(lambda t: ("invalid", t)),
)


def _cache_is_all_valid(stage):
    """Every value in the stage's LLM cache must pass NumberModel validation."""
    cache = C._load_llm_cache(stage)
    for v in cache.values():
        blob = v if isinstance(v, str) else json.dumps(v)
        assert C._validate_response(blob, NumberModel) is not None, v


@settings(max_examples=200, deadline=None)
@given(
    responses=st.lists(_response_element, min_size=1, max_size=8),
)
def test_property7_guard_soundness(responses):
    with sandbox():
        stage = "s_prop7"
        cache_key = "k0"

        texts = [
            _valid_text(payload) if kind == "valid" else payload
            for kind, payload in responses
        ]
        client = FakeClient(queue_responder(texts))

        try:
            result = C.call_llm(
                prompt="p", cache_key=cache_key, schema=NumberModel,
                stage=stage, client=client,
            )
        except C.MalformedResponse:
            # Guard fired: nothing malformed may have entered the cache.
            cache = C._load_llm_cache(stage)
            assert cache_key not in cache
        else:
            # A returned value MUST be schema-valid...
            assert isinstance(result, NumberModel)
            # ...and the cached serialization MUST re-validate to the same value.
            cache = C._load_llm_cache(stage)
            assert cache_key in cache
            revalidated = C._validate_response(
                json.dumps(cache[cache_key]), NumberModel
            )
            assert revalidated is not None
            assert revalidated.value == result.value

        # In every branch: no invalid value is present anywhere in the cache.
        _cache_is_all_valid(stage)


@settings(max_examples=100, deadline=None)
@given(
    valid_n=st.integers(min_value=-1000, max_value=1000),
    n_bad_first=st.integers(min_value=0, max_value=2),
)
def test_property7_reject_and_retry_then_accept(valid_n, n_bad_first):
    """Up to LLM_MAX_SCHEMA_ATTEMPTS-1 malformed responses are rejected-and-
    retried; a subsequent valid response is accepted and cached (R19.2)."""
    with sandbox():
        stage = "s_prop7_retry"
        # n_bad_first invalids (< max attempts) followed by a valid response.
        texts = (["not json"] * n_bad_first) + [_valid_text(valid_n)]
        client = FakeClient(queue_responder(texts))

        result = C.call_llm(
            prompt="p", cache_key="k", schema=NumberModel,
            stage=stage, client=client,
        )
        assert isinstance(result, NumberModel)
        assert result.value == valid_n
        _cache_is_all_valid(stage)


@settings(max_examples=100, deadline=None)
@given(bad=st.sampled_from(_INVALID_TEXTS))
def test_property7_all_malformed_raises_and_caches_nothing(bad):
    """When every attempt is malformed, call_llm raises MalformedResponse and the
    cache stays empty — a malformed value never reaches the cache (R19.2)."""
    with sandbox():
        stage = "s_prop7_bad"
        # Always malformed: more than LLM_MAX_SCHEMA_ATTEMPTS copies.
        client = FakeClient(queue_responder([bad] * (C.LLM_MAX_SCHEMA_ATTEMPTS + 2)))

        with pytest.raises(C.MalformedResponse):
            C.call_llm(prompt="p", cache_key="k", schema=NumberModel,
                       stage=stage, client=client)

        assert C._load_llm_cache(stage) == {}


def test_callable_without_feedback_retries_the_identical_original_prompt():
    """Legacy callable validators keep their exact pre-v1.4 prompt behavior."""
    with sandbox():
        prompts = []
        texts = iter(["not json", '{"accepted": true}'])

        def responder(*, model, contents, config):
            prompts.append(contents)
            return _resp(next(texts))

        def validator(text):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return None
            return value if value.get("accepted") is True else None

        result = C.call_llm(
            prompt="byte-identical-base-prompt",
            cache_key="legacy-callable",
            schema=validator,
            stage="s_callable_no_feedback",
            client=FakeClient(responder),
        )
        assert result == {"accepted": True}
        assert prompts == [
            "byte-identical-base-prompt",
            "byte-identical-base-prompt",
        ]


def test_feedback_validator_diagnoses_empty_and_timeout_reuses_corrected_prompt():
    """Feedback is available for empty text and timeout retries do not drift."""
    with sandbox():
        prompts = []

        def responder(*, model, contents, config):
            prompts.append(contents)
            if len(prompts) == 1:
                return _resp("")
            if len(prompts) == 2:
                raise TimeoutError("request timed out")
            return _resp('{"accepted": true}')

        def validator(text):
            validator.validation_feedback = None
            if not text:
                validator.validation_feedback = (
                    "The response was empty; return one complete JSON object."
                )
                return None
            value = json.loads(text)
            return value if value.get("accepted") is True else None

        validator.validation_feedback = None
        result = C.call_llm(
            prompt="original-request",
            cache_key="empty-then-timeout",
            schema=validator,
            stage="s_feedback_empty_timeout",
            client=FakeClient(responder),
        )

        assert result == {"accepted": True}
        assert prompts[0] == "original-request"
        assert "CORRECTION REQUIRED" in prompts[1]
        assert "response was empty" in prompts[1]
        assert prompts[2] == prompts[1]
