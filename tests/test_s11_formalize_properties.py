"""Logic tests for S10's properties-only formalization (Task 11 / 11.1).

Verifies the ported analytical logic and the mandated SCOPE REDUCTION (R10):

  * S10 maps each concept's raw-verb `props` to the 13 core object properties
    and demotes sentence-like targets (>4 words) to `literal_annotations` (R10.1);
  * S10 leaves the taxonomy UNTOUCHED — the `taxonomy_parent` map in S10's output
    is byte-identical to its S09 input (R10.2, R10.3) — the Property 11 seed;
  * S10 emits NO OWL: no `.owl` file is produced anywhere under the run tree
    (R10.2); the sole artifact is the versioned JSON;
  * S10 records the verb→core mapping under `__meta__.property_mapping` for S11's
    sub-property layer and surfaces uncertain verbs; when mapping quality is too
    low the layer is omitted while the 13 core still apply (R23);
  * `run()` reads the latest S09 artifact, writes ONE versioned artifact, and
    returns it (R2.3, R13.3); the input file is never mutated (R2.4); re-runs
    never overwrite (R1.1);
  * pause: a mid-run QuotaExhausted leaves the checkpoint but NO primary artifact
    and NO manifest line (R8.4, R19.4, R19.6).

The LLM client is ALWAYS mocked (see :class:`FakeClient`) so tests are fully
offline and deterministic.

Run:  pytest test_result/pipeline_v2/tests/test_s11_formalize_properties.py
"""

import json
import sys
import types as _pytypes
from pathlib import Path

import pytest

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s11_formalize_properties as S10  # noqa: E402


# ── Mocked LLM client (no network) ──────────────────────────────────────────
class _DailyQuotaError(Exception):
    """Provider error common._classify_rate_error classifies as daily quota."""
    def __init__(self):
        super().__init__(
            "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
            "'GenerateRequestsPerDay' (per day)."
        )


class _FakeModels:
    def __init__(self, responder):
        self._responder = responder

    def generate_content(self, *, model, contents, config):
        return self._responder(contents=contents)


class FakeClient:
    def __init__(self, responder):
        self.models = _FakeModels(responder)


def _resp(text):
    return _pytypes.SimpleNamespace(text=text)


def _install_client(monkeypatch, responder):
    monkeypatch.setattr(C, "_LLM_CLIENT", FakeClient(responder))
    monkeypatch.setattr(C, "_LLM_CACHES", {})


def _redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "CACHES", tmp_path / "caches")
    monkeypatch.setattr(C, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    (tmp_path / "caches").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)


def _seed_s09(db, tmp_path):
    d = tmp_path / "artifacts" / "s09_qa_repair"
    d.mkdir(parents=True)
    p = d / "20990101-000000__deadbeef.json"
    p.write_text(json.dumps(db), encoding="utf-8")
    return p


# ── Verb → core mapping the mocked LLM returns ──────────────────────────────
# The prompt lists the raw verbs; the responder returns a schema-shaped mapping.
_VERB_MAP = {
    "use": "hasComponent",
    "learn": "learnsFrom",
    "optimize": "optimizes",
    "predict": "producesOutput",
}


def _responder(*, contents):
    """Return a BatchMappingResponse-shaped JSON for the verbs in the prompt."""
    text = contents if isinstance(contents, str) else str(contents)
    mappings = []
    for verb, core in _VERB_MAP.items():
        # only include verbs that actually appear in this batch prompt
        if f'"{verb}"' in text:
            mappings.append({"raw_verb": verb, "core_property": core})
    return _resp(json.dumps({"mappings": mappings}))


def _make_db():
    """A synthetic S09-shaped DB with a taxonomy, raw-verb props, a sentence-like
    target to demote, and a literal-annotation-only concept."""
    return {
        # skeleton spine nodes carry a taxonomy_parent and empty props.
        "Machine_Learning": {
            "f": 0, "td": 0, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "Artificial_Intelligence",
            "is_skeleton": True,
        },
        "ML_Model": {
            "f": 0, "td": 0, "cov": 1.0, "props": {},
            "literal_annotations": [], "taxonomy_parent": "Machine_Learning",
            "is_skeleton": True,
        },
        "cnn": {
            "f": 5, "td": 5, "cov": 1.0,
            "props": {
                # short target -> stays as a core-property edge
                "use": {"filter": {"f": 3, "v": {"filter": 3}, "e": "ex"}},
                # sentence-like target (>4 words) -> demoted to literal_annotations
                "predict": {
                    "the class label of an input image": {
                        "f": 1, "v": {"predict": 1}, "e": "ex2"
                    }
                },
            },
            "literal_annotations": [], "taxonomy_parent": "ML_Model",
        },
        "linear_regression": {
            "f": 4, "td": 4, "cov": 1.0,
            "props": {
                "optimize": {"loss": {"f": 2, "v": {"optimize": 2}, "e": "ex3"}},
                "learn": {"weights": {"f": 1, "v": {"learn": 1}, "e": "ex4"}},
            },
            "literal_annotations": [], "taxonomy_parent": "ML_Model",
        },
        # literal-annotation-only concept: no props, carries a demoted fact.
        "legacy_concept": {
            "f": 0, "td": 1, "cov": 1.0, "props": {},
            "literal_annotations": [
                {"prop": "hasComponent", "value": "widget", "weight": 1,
                 "raw_verbs": ["use"]}
            ],
            "taxonomy_parent": "ML_Model",
        },
    }


def _taxonomy_map(db):
    """The {concept: taxonomy_parent} projection used for the byte-identical check."""
    return {k: v.get("taxonomy_parent") for k, v in db.items() if k != S10.META_KEY}


# ── Property 11 seed: taxonomy untouched + no OWL ───────────────────────────
def test_taxonomy_parent_byte_identical_and_no_owl(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    src = _make_db()
    in_path = _seed_s09(src, tmp_path)
    before_tax = json.dumps(_taxonomy_map(src), sort_keys=True)

    _install_client(monkeypatch, _responder)
    out_path = S10.run()

    out_db = json.loads(Path(out_path).read_text())
    after_tax = json.dumps(_taxonomy_map(out_db), sort_keys=True)

    # R10.2 / R10.3 (Property 11 seed): taxonomy_parent map is byte-identical.
    assert after_tax == before_tax
    # Every concept's taxonomy_parent is preserved value-for-value.
    for k, v in src.items():
        assert out_db[k]["taxonomy_parent"] == v["taxonomy_parent"]

    # R10.2: S10 emits NO OWL anywhere under the run tree.
    owl_files = list(tmp_path.rglob("*.owl"))
    assert owl_files == [], f"S10 must not emit OWL, found: {owl_files}"

    # R10.4: no regex_superclass field is introduced.
    assert all("regex_superclass" not in out_db[k]
               for k in src), "S10 must not add regex_superclass (R10.4)"

    # The sole S10 artifact is the versioned JSON that was returned.
    art_dir = tmp_path / "artifacts" / "s11_formalize_properties"
    assert [p.name for p in art_dir.glob("*")] == [Path(out_path).name]
    assert Path(out_path).suffix == ".json"


def test_props_rekeyed_and_sentences_demoted(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s09(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)

    out_db = json.loads(Path(S10.run()).read_text())

    # R10.1: props are re-keyed to core properties.
    cnn = out_db["cnn"]
    assert "hasComponent" in cnn["props"]          # "use" -> hasComponent
    assert "filter" in cnn["props"]["hasComponent"]
    # raw verb preserved in the reified `v` map for S11.
    assert "use" in cnn["props"]["hasComponent"]["filter"]["v"]

    # The sentence-like target was demoted, not kept as an edge.
    assert "producesOutput" not in cnn["props"], "sentence-like edge must be demoted"
    demoted_values = [a["value"] for a in cnn["literal_annotations"]]
    assert "the class label of an input image" in demoted_values

    lr = out_db["linear_regression"]
    assert "optimizes" in lr["props"] and "learnsFrom" in lr["props"]

    # literal-annotation-only concept carried through unchanged.
    assert out_db["legacy_concept"]["literal_annotations"]
    assert out_db["legacy_concept"]["props"] == {}


def test_property_mapping_recorded_for_subproperty_layer(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s09(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)

    out_db = json.loads(Path(S10.run()).read_text())

    # R23: verb→core mapping recorded under the reserved meta key.
    meta = out_db[S10.META_KEY]
    assert meta["property_mapping"]["use"] == "hasComponent"
    assert meta["property_mapping"]["optimize"] == "optimizes"
    # All four verbs mapped confidently -> layer is NOT omitted.
    assert meta["sub_property_layer_omitted"] is False
    assert meta["uncertain_verbs"] == []


def test_uncertain_mapping_omits_layer(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s09(_make_db(), tmp_path)

    # Responder returns an EMPTY mapping -> every verb hits the fallback and is
    # flagged uncertain, tripping the R23.5 omit threshold.
    _install_client(monkeypatch, lambda *, contents: _resp(json.dumps({"mappings": []})))

    out_db = json.loads(Path(S10.run()).read_text())
    meta = out_db[S10.META_KEY]

    # R23.5: sub-property layer omitted, but the 13 core still apply (props keyed
    # to hasCharacteristic fallback), and taxonomy remains untouched.
    assert meta["sub_property_layer_omitted"] is True
    assert meta["property_mapping"] == {}
    assert len(meta["uncertain_verbs"]) > 0
    # The 13 core still apply: with no mapping every verb folds into the
    # 'hasCharacteristic' fallback, so cnn's short "filter" edge lands there.
    assert "hasCharacteristic" in out_db["cnn"]["props"]
    assert "filter" in out_db["cnn"]["props"]["hasCharacteristic"]
    # taxonomy remains untouched even when the layer is omitted.
    assert out_db["cnn"]["taxonomy_parent"] == "ML_Model"


def test_input_not_mutated_and_reruns_never_overwrite(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    in_path = _seed_s09(_make_db(), tmp_path)
    before = in_path.read_bytes()
    _install_client(monkeypatch, _responder)

    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S10.run()
    # R2.4: input file never mutated.
    assert in_path.read_bytes() == before

    # New RUN_ID + clear the resumable checkpoint so the second pass reruns.
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    ckpt = tmp_path / "caches" / "s11_formalize_properties" / "map_cache.json"
    if ckpt.is_file():
        ckpt.unlink()
    p2 = S10.run()

    # R1.1: a re-run produces a NEW versioned file (both retained).
    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_manifest_records_one_line(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s09(_make_db(), tmp_path)
    _install_client(monkeypatch, _responder)
    S10.run()

    lines = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["stage"] == "s11_formalize_properties"
    assert rec["counts"]["verbs_total"] >= 1
    assert "sub_property_layer_omitted" in rec["extra"]


def test_run_raises_when_no_s09_present(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        S10.run()


# ── pause: mid-run QuotaExhausted leaves NO primary artifact ────────────────
def test_pause_writes_no_artifact(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    _seed_s09(_make_db(), tmp_path)

    def responder(*, contents):
        raise _DailyQuotaError()

    _install_client(monkeypatch, responder)

    with pytest.raises(SystemExit) as ei:
        S10.run()
    assert ei.value.code == 0

    art_dir = tmp_path / "artifacts" / "s11_formalize_properties"
    assert not art_dir.exists() or list(art_dir.glob("*.json")) == []
    manifest = tmp_path / "manifest.jsonl"
    if manifest.exists():
        assert '"s11_formalize_properties"' not in manifest.read_text()
