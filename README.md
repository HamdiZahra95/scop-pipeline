# SCOP: Staged Corpus-to-Ontology Pipeline

[![Conference](https://img.shields.io/badge/ICAART_2027-Accepted_Paper_%23394-success.svg)](https://icaart.scitepress.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)]()
[![OWL 2 DL](https://img.shields.io/badge/OWL_2_DL-100%25_HermiT_Certified-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)]()

> **Official Implementation & Reproduction Package**  
> Companion repository for the paper:  
> **"SCOP: A Staged Neuro-Symbolic Architecture for Automated Ontology Construction from Scientific Literature"**  
> Accepted at the *19th International Conference on Agents and Artificial Intelligence (ICAART 2027)*.

---

## 📌 Overview

**SCOP (Staged Corpus-to-Ontology Pipeline)** is an open, verifiable neuro-symbolic framework for automated ontology generation from unstructured scientific literature. 

SCOP enforces a strict separation of concerns between:
1. **Stochastic Neural Extraction:** Open-domain term harvesting, hypernym proposals, and floater re-homing using foundation models (e.g., Gemini, open-weight LLMs).
2. **Deterministic Symbolic Formalization:** Schema-bound compilation, cycle breaking, target grounding, disjointness collision prevention, and terminal HermiT hypertableau reasoning ($\mathcal{SROIQ}(\mathcal{D})$ consistency certification).

```
[Raw Scientific Literature (112k Abstracts)]
                 │
  Pre-Pipeline   ▼  (harvest/)
  ┌──────────────────────────────────────────────┐
  │ Volume-over-Depth Corpus Harvesting          │
  └──────────────────────┬───────────────────────┘
  Phase I                ▼  (S01 - S03)
  ┌──────────────────────────────────────────────┐
  │ Vocabulary Induction & Zipfian Gating        │
  └──────────────────────┬───────────────────────┘
  Phase II               ▼  (S04 - S07)
  ┌──────────────────────────────────────────────┐
  │ Non-Taxonomic Extraction & Grounding Gate    │
  └──────────────────────┬───────────────────────┘
  Phase III              ▼  (S08 - S10)
  ┌──────────────────────────────────────────────┐
  │ Taxonomic Induction, Repair & Re-Homing      │
  │ • S08: Initial Taxonomy Induction            │
  │ • S09: Structural Graph Repair (SCC/Cycles)  │
  │ • S10: Semantic Taxonomic Re-Homing          │
  └──────────────────────┬───────────────────────┘
  Phase IV               ▼  (S11 - S12)
  ┌──────────────────────────────────────────────┐
  │ Property Formalization & OWL-DL Serialization│
  │ • S11: Relational Property Formalization     │
  │ • S12: Deterministic W3C OWL 2 DL Export     │
  └──────────────────────┬───────────────────────┘
  Phase V                ▼  (S13)
  ┌──────────────────────────────────────────────┐
  │ Terminal Reasoner Certification (HermiT)     │
  └──────────────────────────────────────────────┘
                 │
   [Verified OWL 2 DL Domain Ontology]
```

---

## 📂 Repository Structure

```text
├── harvest/                           # Pre-Pipeline: Volume-over-Depth Harvester
│   ├── harvest_concepts.py            # Extracts concept + definition per abstract
│   └── sample_abstracts.csv           # 10 raw arXiv paper abstracts for testing
├── stages/                            # 13 formal transformation stages (S01 - S13)
│   ├── s01_seed_concepts.py           # Phase I: Seed schema validation
│   ├── s02_consolidate.py             # Phase I: Lexical normalization & indexing
│   ├── s03_frequency_gate.py          # Phase I: Zipfian frequency stratification
│   ├── s04_extract_properties.py      # Phase II: Deterministic Hearst relation mining
│   ├── s05_rescue_untreated.py        # Phase II: Schema-guarded neural rescue
│   ├── s06_clean_vocab.py             # Phase II: Target clustering & synonym merging
│   ├── s07_ground_to_master.py        # Phase II: Anti-hallucination grounding gate
│   ├── s08_build_taxonomy.py          # Phase III: Recursive taxonomy induction
│   ├── s09_qa_repair.py               # Phase III: Structural repair & cycle breaking
│   ├── s10_taxonomy_rehome.py         # Phase III: Multi-pass semantic re-homing
│   ├── s11_formalize_properties.py    # Phase IV: Property mapping onto 13 core predicates
│   ├── s12_export_owl.py              # Phase IV: W3C OWL 2 DL serialization
│   └── s13_quality_gate.py            # Phase V: HermiT hypertableau certification
├── data/
│   ├── seed/
│   │   ├── lean_checkpoint.jsonl      # Frozen harvested corpus (112,594 abstracts)
│   │   └── sample_100_seed.jsonl      # Compact 100-paper sample for testing
│   └── reference/
│       └── ML_Ontology.ttl            # External guiding reference taxonomy
├── ontologies/
│   ├── scop_baseline.owl              # HermiT-certified baseline ontology (1,993 classes)
│   └── scop_guided.owl                # HermiT-certified guided ontology (2,041 classes)
├── analysis/                          # Paper evaluation and ablation harness
│   ├── data/                          # 10-model blinded adjudication CSVs & metrics
│   └── reproduce_evaluation.py        # 1-click script replicating Table 5 ablation results
├── tools/
│   └── query_ontology.py              # Interactive SPARQL diagnostics utility
├── tests/                             # Automated pytest suite (stages & properties)
├── common.py                          # Core engine: immutability, schemas & execution
├── knowledge.py                       # Reference taxonomy alignment engine
├── run.py                             # Master pipeline CLI runner (stages 01 to 13)
└── requirements.txt                   # Pinned Python dependencies
```

---

## 🚀 Quickstart & Reproduction

### 1. Prerequisites
* **Python:** 3.10+
* **Java JRE:** Java 11+ is required for the HermiT hypertableau reasoner (`default-jre` or `openjdk-11-jre`).

```bash
# Clone the repository
git clone https://github.com/HamdiZahra95/scop-pipeline.git
cd scop-pipeline

# Install dependencies
pip install -r requirements.txt
```

### 2. Reproduce Paper Ablation Results (1-Click)
To replicate the empirical ablation results (10-model frontier panel, Fleiss' $\kappa = 0.4233$, direct-parent accuracy $+15.04\%$, McNemar test $p = 0.0241$):

```bash
python analysis/reproduce_evaluation.py
```

### 3. Evaluate Competency Questions (200 SPARQL CQs Suite)
To reproduce the multi-tiered Competency Question evaluation (20, 50, 100, 150, and 200 CQs) across SCOP ontologies and external gold baselines (ACM CCS, AIO, ITO) under Description Logic reasoning:

```bash
python analysis/13_cq_scale_comparison.py
```
> The complete inventory of 200 formal SPARQL competency questions, classification categories, and query answers is available in [`analysis/results/expanded_cq_benchmark_200.md`](analysis/results/expanded_cq_benchmark_200.md).

> [!NOTE]
> **Held-Out Gold Standards:** Evaluation benchmarks compare against human-curated references in `analysis/gold/` (AIO, ACM CCS 2012, and the lightweight ITO task backbone `ito-ai-process.json`, all included in the repository). The full 124 MB Intelligence Task Ontology (`ITO.owl`) is excluded from version control to respect repository limits; if you wish to run the expanded ITO alignment evaluation, download it via:
> ```bash
> cd analysis/gold && curl -sSL -o ITO.owl.zip https://raw.githubusercontent.com/OpenBioLink/ITO/master/ITO.owl.zip && python3 -c "import zipfile; zipfile.ZipFile('ITO.owl.zip').extractall('.')" && cd ../..
> ```
> See [`analysis/gold/SOURCES.md`](analysis/gold/SOURCES.md) for full provenance and retrieval details.


### 4. Run Test Suite
To verify the programmatic contracts, schema validations, and reasoner gates across all 13 stages:

```bash
pytest tests/ -v
```

### 5. Live Trial Run (Top-N Demonstration from Scratch)
Executes the pipeline stages from seed data to W3C OWL 2 DL export and terminal HermiT hypertableau reasoning in an isolated sandbox (`runs/trial_10/`):

First, configure your preferred LLM provider in `.env` (see `.env.example`):
* **Google GenAI API:** `GOOGLE_API_KEY=your_key` (Free tier via Google AI Studio)
* **Ollama Cloud:** `OLLAMA_API_KEY=your_key`
* **Local Ollama:** `OLLAMA_HOST=http://localhost:11434`

It is recommended to use a Pro Ollama account or a Tier 1 Google API account, as the free tier has recently experienced frequent server errors under high load.

Then execute:
```bash
# Compare Baseline vs. Knowledge-Guided on top 10 concepts:
python analysis/trial_run.py --mode all --top 10

# Or individual modes:
python analysis/trial_run.py --mode baseline --top 10
python analysis/trial_run.py --mode guided --top 10
```

### 6. Running the Pipeline (Full Corpus)
```bash
# List stages and status
python run.py --list

# Run unguided baseline pipeline (stages 01 to 13)
python run.py --mode baseline --all

# Run knowledge-guided production pipeline (stages 01 to 13)
python run.py --mode guided --all
```

### 7. Optional: Testing Upstream Corpus Harvesting
To test extracting concepts and definitions directly from raw literature abstracts:

```bash
python harvest/harvest_concepts.py --input harvest/sample_abstracts.csv --limit 5 --mock
```

---

## 🔬 Pre-Generated Ontology Artifacts

For immediate inspection and semantic verification, the final serialized ontologies are provided in `ontologies/`:
* `ontologies/scop_baseline.owl`: Baseline unguided ontology (1,993 classes, 0 unsatisfiable concepts, 0 subsumption cycles).
* `ontologies/scop_guided.owl`: Full reference-guided ontology (2,041 classes, expanded taxonomic depth, HermiT certified).

Both files can be opened and inspected in standard ontology editors (e.g., Protégé) or queried using RDFLib/HermiT.

---

## 📖 Citation

If you use SCOP or our serialized ontology artifacts in your research, please cite:

```bibtex
@inproceedings{ezzahra2027scop,
  author    = {Hamdi Ezzahra and Wided Ben Abid},
  title     = {SCOP: A Staged Neuro-Symbolic Architecture for Automated Ontology Construction from Scientific Literature},
  booktitle = {Proceedings of the 19th International Conference on Agents and Artificial Intelligence (ICAART 2027)},
  year      = {2027},
  publisher = {SCITEPRESS},
  note      = {To appear}
}
```
