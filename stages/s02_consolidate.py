"""
s02_consolidate.py — Stage 2: consolidate seed concepts (Port+Extend).

Input : latest artifacts/s01_seed_concepts/*.jsonl   (schema: {id, concept_name, definition})
Output: artifacts/s02_consolidate/<RUN_ID>__<codehash>.json   (never overwritten)
LLM   : no

Port (from scripts/shared/first_v2.py, preserved byte-identical under legacy):
  Phase 1  group records per concept, attach corpus_frequency + consolidated
           definitions.
  Phase 2  lexical broader/narrower via whole-word containment (inverted index
           on the first word for speed).
  Phase 3  evidence mentions: which OTHER concepts each concept's definitions
           mention (flashtext keyword search, per-sentence).

Extend (R9 — the mandated logic change): group by a NORMALIZED concept_name
  (lowercased, stripped, internal whitespace collapsed) so case/spacing variants
  like "Deep Learning" / "deep learning" / "deep  learning" merge into ONE
  concept. Frequencies and definitions of the merged variants combine into the
  single surviving concept. The manifest reports the pre- and post-normalization
  unique-concept counts so the effect of the fix is visible (R9.4).

Output contract per concept (R9.2):
  {target_concept, corpus_frequency, consolidated_definitions[],
   lexical_broader[], lexical_narrower[], evidence_mentions[]}
"""

import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
from flashtext import KeywordProcessor
from tqdm import tqdm

# Make the package importable whether run from pipeline_v2/ or its parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

STAGE = "s02_consolidate"


def normalize_name(name: str) -> str:
    """Deterministic normalization key for grouping (R9.1).

    Lowercase, strip surrounding whitespace, and collapse every run of internal
    whitespace to a single space. Same input always yields the same key, so
    case/spacing variants of a concept merge into one group.
    """
    return re.sub(r"\s+", " ", str(name).strip().lower())


def split_sentences(text) -> list[str]:
    """Split a definition into sentences for precise evidence extraction."""
    return re.split(r"(?<=[.!?])\s+", str(text))


def run() -> Path:
    print("🚀 S02: consolidating seed concepts (with normalization)...")
    start_time = time.time()

    # ── 1. LOAD latest S01 artifact (never a hardcoded filename) ──────────
    in_path = C.require_latest("s01_seed_concepts", ext="jsonl")
    print(f"📂 Loading {in_path} ...")
    df = pd.read_json(in_path, lines=True)
    df["definition"] = df["definition"].fillna("")
    df["concept_name"] = df["concept_name"].astype(str)
    print(f"✅ Loaded {len(df):,} raw records.")

    # Unique count BEFORE normalization (raw concept names), for the manifest.
    pre_unique = int(df["concept_name"].nunique())

    # ── 2. PHASE 1: normalized consolidation (R9.1, R9.3) ─────────────────
    # Group by the normalized key; merge frequencies and definitions of every
    # case/space variant into a single surviving concept.
    print("🔄 Phase 1: consolidating by normalized concept_name...")
    df["_norm"] = df["concept_name"].map(normalize_name)

    grouped = df.groupby("_norm").agg(
        frequency=("id", "count"),
        unique_definitions=("definition", lambda x: sorted({d for d in x if str(d).strip()})),
        variants=("concept_name", lambda x: list(x)),
    ).reset_index()

    # Survivor label: the most frequent original surface form among the merged
    # variants (deterministic tie-break: shortest, then lexicographically first).
    def pick_survivor(variants: list[str]) -> str:
        counts = defaultdict(int)
        for v in variants:
            counts[v] += 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]

    grouped["concept_name"] = grouped["variants"].map(pick_survivor)

    # Sort by length to help the lexical-hierarchy pass (short → long), as in the
    # ported logic.
    grouped["name_length"] = grouped["concept_name"].apply(len)
    grouped = grouped.sort_values(["name_length", "concept_name"]).reset_index(drop=True)

    post_unique = len(grouped)
    print(f"✅ {pre_unique:,} raw names → {post_unique:,} normalized concepts "
          f"(merged {pre_unique - post_unique:,}).")

    # ── 3. PHASE 2: lexical broader/narrower (Port) ───────────────────────
    print("🔄 Phase 2: lexical hierarchy (broader/narrower)...")
    word_index = defaultdict(list)
    for idx, row in grouped.iterrows():
        for word in row["concept_name"].lower().split():
            word_index[word].append(idx)

    lexical_broader = defaultdict(list)
    lexical_narrower = defaultdict(list)

    for idx, row in tqdm(grouped.iterrows(), total=len(grouped), desc="Hierarchy Matching"):
        short_concept = row["concept_name"]
        words = short_concept.lower().split()
        if not words:
            continue
        # Only check candidates sharing the first word (massive speedup).
        candidates = set(word_index[words[0]])
        for cand_idx in candidates:
            if cand_idx == idx:
                continue
            long_concept = grouped.at[cand_idx, "concept_name"]
            # Whole-word match ("cat" must not match "concatenate").
            pattern = r"\b" + re.escape(short_concept) + r"\b"
            if re.search(pattern, long_concept, re.IGNORECASE):
                if len(short_concept) < len(long_concept):
                    lexical_narrower[short_concept].append(long_concept)
                    lexical_broader[long_concept].append(short_concept)
    print("✅ Hierarchy mapping complete.")

    # ── 4. PHASE 3: evidence mentions (Port) ──────────────────────────────
    print("🔄 Phase 3: extracting evidence mentions from definitions...")
    processor = KeywordProcessor(case_sensitive=False)
    for concept in grouped["concept_name"]:
        processor.add_keyword(concept, concept)

    consolidated = []
    for idx, row in tqdm(grouped.iterrows(), total=len(grouped), desc="Building Payload"):
        concept = row["concept_name"]
        mentions = []
        for defn in row["unique_definitions"]:
            for sent in split_sentences(defn):
                for m in processor.extract_keywords(sent):
                    if m.lower() != concept.lower():
                        mentions.append({
                            "mentioned_concept": m,
                            "evidence_sentence": sent,
                        })
        # Deduplicate on the mentioned concept.
        unique_mentions = list({v["mentioned_concept"]: v for v in mentions}.values())

        consolidated.append({
            "target_concept": concept,
            "corpus_frequency": int(row["frequency"]),
            "consolidated_definitions": row["unique_definitions"],
            "lexical_broader": lexical_broader.get(concept, []),
            "lexical_narrower": lexical_narrower.get(concept, []),
            "evidence_mentions": unique_mentions,
        })

    # ── 5. SAVE new versioned artifact + manifest ─────────────────────────
    out_path = C.output_path(STAGE, __file__, ext="json")
    C.save_json(out_path, consolidated)

    C.write_manifest(
        STAGE, __file__, in_path=in_path, out_path=out_path,
        counts={
            "records_in": len(df),
            "unique_pre_normalization": pre_unique,
            "unique_post_normalization": post_unique,
            "merged_by_normalization": pre_unique - post_unique,
        },
    )
    elapsed = time.time() - start_time
    print(f"[{STAGE}] wrote {post_unique:,} consolidated concepts "
          f"in {elapsed:.1f}s -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
