"""Logic tests for S06's vocabulary cleanup (Task 5 / R20).

Verifies the ported three-pass analytical logic and the mandated port changes:

  * Pass 1 lowercases, strips leading articles + trailing punctuation, and
    merges verb synonyms (utilize/employ/apply → use, perform → execute),
  * Pass 2 folds a plural target into its singular when the singular exists,
  * Pass 3 semantically clusters remaining targets to the shortest surface
    string in each cluster (monkeypatched offline here),
  * the vocabulary is CLEANER after cleanup (fewer distinct verbs/targets),
  * merged surface forms are recorded per canonical target as `sf` so S11 can
    emit `skos:altLabel` (R20.1),
  * `run()` reads the latest S05 artifact, writes a versioned artifact, and
    returns it (R2.3, R13.3); re-runs never overwrite (R1.1),
  * the manifest records before/after vocabulary sizes and alt-label counts.

The Pass-3 SentenceTransformer step is monkeypatched to identity so tests run
fast and offline; the string-cleanup, verb-merge, plural-merge, and
surface-form bookkeeping under test are exercised for real (no mocks).

Run:  pytest test_result/pipeline_v2/tests/test_s06_clean_vocab.py
"""

import json
import sys
from pathlib import Path

import pytest

PIPELINE_V2 = Path(__file__).resolve().parent.parent
if str(PIPELINE_V2) not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2))
if str(PIPELINE_V2 / "stages") not in sys.path:
    sys.path.insert(0, str(PIPELINE_V2 / "stages"))

import common as C  # noqa: E402
import s06_clean_vocab as S06  # noqa: E402


# ── pure helpers: string cleanup + singularization (Port logic) ─────────────
def test_clean_target_string_lowercases_strips_articles_and_punct():
    assert S06.clean_target_string("The Neural Networks.") == "neural networks"
    assert S06.clean_target_string("  A Model,") == "model"
    assert S06.clean_target_string("an Image;") == "image"


def test_singularize_technical_rules():
    assert S06.singularize("networks") == "network"
    assert S06.singularize("categories") == "category"
    assert S06.singularize("classes") == "class"       # -ses → -s? no: 'classes'->'class'
    assert S06.singularize("boxes") == "box"
    # invariant words (port guards -is/-us/-ss so these stay unchanged)
    assert S06.singularize("analysis") == "analysis"   # -is guard
    assert S06.singularize("status") == "status"       # -us guard
    assert S06.singularize("loss") == "loss"           # -ss guard


def test_verb_merge_table_folds_synonyms():
    assert S06.VERB_MERGE["utilize"] == "use"
    assert S06.VERB_MERGE["employ"] == "use"
    assert S06.VERB_MERGE["applied"] == "use"
    assert S06.VERB_MERGE["performs"] == "execute"


# ── run(): end-to-end over a synthetic S05 property DB ──────────────────────
def _seed_s04(db, tmp_path, monkeypatch):
    """Write a synthetic latest-S05 artifact and redirect ARTIFACTS/MANIFEST.

    S06 reads the latest S05 output (re-pointed in task 8.1); S05 preserves the
    same `{f, td, cov, props, unt}` contract as S04, so this synthetic DB seeds
    the S05 artifact directory.
    """
    s05_dir = tmp_path / "artifacts" / "s05_rescue_untreated"
    s05_dir.mkdir(parents=True)
    (s05_dir / "20990101-000000__deadbeef.json").write_text(
        json.dumps(db), encoding="utf-8"
    )
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(C, "MANIFEST", tmp_path / "manifest.jsonl")
    # Identity semantic map so the test needs no embedding model.
    monkeypatch.setattr(
        S06, "_semantic_target_map", lambda targets: {t: t for t in targets}
    )


def _make_db():
    """A property DB exercising verb merge, article/punct cleanup, plural merge."""
    return {
        "CNN": {
            "f": 42, "td": 3, "cov": 0.9,
            "consolidated_definitions": [
                "A neural network that uses convolution.",
                "A model that applies pooling layers.",
            ],
            "props": {
                # 'utilize' + 'use' should merge to a single 'use' verb.
                "utilize": {"The Filters": {"f": 2, "v": {"filters": 2}, "e": "ex1"}},
                "use": {"filter": {"f": 3, "v": {"filter": 3}, "e": "ex2"}},
                # 'apply' → 'use' too.
                "apply": {"convolution.": {"f": 1, "v": {"convolution": 1}, "e": "ex3"}},
            },
            "unt": ["some untreated def"],
        },
    }


def test_run_merges_verbs_and_cleans_targets(tmp_path, monkeypatch):
    _seed_s04(_make_db(), tmp_path, monkeypatch)

    out_path = S06.run()
    assert Path(out_path).is_file()
    db = json.loads(Path(out_path).read_text())

    entry = db["CNN"]
    # {f, td, cov, props, unt, consolidated_definitions} contract preserved.
    assert set(entry.keys()) == {"f", "td", "cov", "props", "unt",
                                 "consolidated_definitions"}
    # R20.3: definitions survive the field-by-field concept rebuild so S11 can
    # emit skos:definition/rdfs:comment (previously dropped here → coverage 0).
    assert entry["consolidated_definitions"] == [
        "A neural network that uses convolution.",
        "A model that applies pooling layers.",
    ]
    # utilize/apply/use all collapsed to a single 'use' verb; no raw synonyms.
    assert "use" in entry["props"]
    assert "utilize" not in entry["props"]
    assert "apply" not in entry["props"]
    # targets cleaned: lowercase, articles/punct stripped, plural folded to singular.
    targets = entry["props"]["use"]
    assert "the filters" not in targets      # article stripped + lowercased
    assert "convolution." not in targets     # trailing punct stripped
    assert "filter" in targets               # 'filters' → 'filter' (plural merge)
    assert "convolution" in targets


def test_vocabulary_is_cleaner_after_cleanup(tmp_path, monkeypatch):
    """Distinct verbs/targets after cleanup are fewer than before (R20)."""
    _seed_s04(_make_db(), tmp_path, monkeypatch)
    S06.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert counts["verbs_after"] < counts["verbs_before"]     # 3 verbs → 1
    assert counts["targets_after"] < counts["targets_before"]


def test_alt_label_surface_forms_recorded(tmp_path, monkeypatch):
    """Merged surface forms are recorded on the canonical target (R20.1)."""
    _seed_s04(_make_db(), tmp_path, monkeypatch)
    out_path = S06.run()
    db = json.loads(Path(out_path).read_text())

    targets = db["CNN"]["props"]["use"]
    # every target entry carries an `sf` list (alt-label source for S11).
    for target, meta in targets.items():
        assert "sf" in meta
        assert isinstance(meta["sf"], list)

    # 'filter' absorbed the plural 'filters' and article variant 'the filters'.
    filter_sf = targets["filter"]["sf"]
    assert "filters" in filter_sf
    assert "the filters" in filter_sf
    # a canonical never lists itself as its own alt-label.
    assert "filter" not in filter_sf

    # manifest reports non-zero alt-label counts.
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    assert counts["alt_label_surface_forms"] >= 2
    assert counts["alt_label_targets"] >= 1


def test_manifest_reports_expected_metrics(tmp_path, monkeypatch):
    _seed_s04(_make_db(), tmp_path, monkeypatch)
    S06.run()
    line = (tmp_path / "manifest.jsonl").read_text().strip().splitlines()[-1]
    counts = json.loads(line)["counts"]
    for key in (
        "concepts", "verbs_before", "verbs_after",
        "targets_before", "targets_after",
        "alt_label_targets", "alt_label_surface_forms",
    ):
        assert key in counts


def test_reruns_never_overwrite_prior_artifact(tmp_path, monkeypatch):
    _seed_s04(_make_db(), tmp_path, monkeypatch)
    monkeypatch.setattr(C, "RUN_ID", "20990101-000001")
    p1 = S06.run()
    monkeypatch.setattr(C, "RUN_ID", "20990101-000002")
    p2 = S06.run()
    assert p1 != p2
    assert Path(p1).is_file() and Path(p2).is_file()


def test_run_raises_when_no_s05_present(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARTIFACTS", tmp_path / "artifacts")
    with pytest.raises(FileNotFoundError):
        S06.run()
