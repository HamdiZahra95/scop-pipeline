from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = [
    "01_compare_inductive_biases.py",
    "02_corpus_grounded_differential_analysis.py",
    "03_concept_generation_behavior_analysis.py",
    "04_semantic_fidelity_analysis.py",
    "05_mistake_taxonomy_analysis.py",
    "06_threshold_sensitivity_analysis.py",
    "07_missing_concept_analysis.py",
    "08_evaluation_design_critique.py",
    "09_synthesis_summary.py",
    "10_balanced_cq_benchmark.py",
    "11_balanced_cq_evaluation.py",
    "13_cq_scale_comparison.py",
]


def main() -> None:
    for name in SCRIPTS:
        script = ROOT / name
        print(f"Running {script.name}...")
        subprocess.run([sys.executable, str(script)], check=True)
    print(f"All analysis scripts completed. Results in: {ROOT / 'results'}")


if __name__ == "__main__":
    main()
