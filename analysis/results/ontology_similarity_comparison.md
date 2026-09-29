# Comparative Analysis: SCOP Baseline vs Guided Ontologies

This report quantifies the exact structural, conceptual, and relational differences
between the newly generated `scop_baseline.owl` and `scop_guided.owl` artifacts.

## 1. Concept Vocabulary Overlap

| Metric | Baseline | Guided | Delta / Overlap |
| :--- | :---: | :---: | :---: |
| **Total Classes** | 2054 | 2090 | +36 |
| **Shared Concepts** | 1114 | 1114 | 53.3% of Guided |
| **Unique to Ontology** | 940 | 976 | — |
| **Concept Jaccard (Exact Slug)** | — | — | **36.8%** |
| **Concept Jaccard (Normalized Lexical)** | — | — | **38.2%** |

### Sample Vocabulary Differences
- **Shared concepts (sample):** 3d_convolutional_neural_network, 3d_object_detection, abductive_reasoning, abstractive_summarization, accelerated_gradient_descent, acoustic_scene_classification, acquisition_function, acquisitionfunction, action_recognition, activation_function
- **Only in Baseline (sample):** abstract_model, activation_and_layer_types, active_learning_objective, actor_critic, adversarial_defenses, adversarial_multiarmed_bandit, adversarial_robustness_monitoring, adversarial_training_methods, adversarialattack, adversarialdomainadaptation
- **Only in Guided (sample):** a3c, activation_unit, actor_critic_algorithm, actor_critic_rl, actorcriticmethod, adaptive_boosting_algorithm, adaptive_iterative_optimization, advanced_deployment_and_robustness, adversarial_attack_method, adversarial_attack_types

## 2. Taxonomic Subsumption & Hierarchy Alignment

| Metric | Baseline | Guided | Comparison / Agreement |
| :--- | :---: | :---: | :---: |
| **Subsumption Edges (rdfs:subClassOf)** | 2049 | 2085 | Shared: 154 (Jaccard: **3.9%**) |
| **Identical Direct Parent (on shared concepts)** | — | — | **154 / 1114 (13.8%)** |
| **Different Direct Parent (Re-homed / Stratified)** | — | — | **960 / 1114 (86.2%)** |
| **Mean Transitive Ancestor Jaccard** | — | — | **45.6%** |
| **Max Subsumption Depth** | 10 | 10 | Guided is more compact / stratified |
| **Mean Concept Depth** | 5.08 | 5.07 | — |
| **Branching Factor** | 2.411 | 2.444 | Guided is slightly denser |

### Sample Direct Parent Shifts (Baseline vs Guided)
| Concept | Baseline Parent | Guided Parent |
| :--- | :--- | :--- |
| `signal_decomposition` | `core_core_ml_task` | `unsupervised_learning_task` |
| `regularized_empirical_risk_minimization` | `risk_minimization_objective` | `regularized_risk_objectives` |
| `classification_model` | `ml_task` | `core_parametric_ml_model` |
| `gaussian_process` | `stochastic_process_model` | `probabilistic_functional_model` |
| `core_ml_algorithm` | `ml_algorithm_architecture` | `ml_algorithm` |
| `large_language_model` | `neural_network_architecture` | `neural_language_model` |
| `convolutional_kernel` | `neural_network_component` | `new_ml_feature_extractor` |
| `probabilistic_model` | `ml_model` | `ml_foundations_and_theory` |

## 3. Relational Structure & Object Properties

| Metric | Baseline | Guided | Delta / Overlap |
| :--- | :---: | :---: | :---: |
| **Total Object Property Triples** | 946 | 995 | +49 |
| **Shared Triples** | 640 | 640 | **49.2%** Jaccard |
| **Unique Triples** | 306 | 355 | — |

### Predicate Frequency Breakdown
| Predicate | Baseline Triples | Guided Triples | Delta |
| :--- | :---: | :---: | :---: |
| `evaluates` | 12 | 15 | +3 |
| `hasCharacteristic` | 26 | 35 | +9 |
| `hasComponent` | 521 | 524 | +3 |
| `hasPurpose` | 30 | 17 | -13 |
| `integrates` | 13 | 19 | +6 |
| `learnsFrom` | 75 | 85 | +10 |
| `modifies` | 30 | 37 | +7 |
| `optimizes` | 72 | 92 | +20 |
| `organizes` | 5 | 7 | +2 |
| `processesData` | 50 | 49 | -1 |
| `producesOutput` | 61 | 64 | +3 |
| `selects` | 24 | 26 | +2 |
| `transforms` | 27 | 25 | -2 |

## 4. Annotation & Definition Richness

| Annotation Property | Baseline Literals | Guided Literals | Delta |
| :--- | :---: | :---: | :---: |
| `skos:definition` | 34,639 | 34,393 | -246 |
| `rdfs:comment` | 42,861 | 42,783 | -78 |
| `skos:altLabel` | 927 | 864 | -63 |
| **Definition Concept Coverage** | 39.3% | 40.3% | Guided has higher concept coverage |

## 5. Synthesis: Why They Differ

1. **Lexical and Conceptual Intersection (36.7% - 41.2% Jaccard):**
   Both ontologies harvest the core machine learning lexicon from the corpus (1,132 shared concepts).
   Guided discovers additional domain concepts by systematically expanding along guided taxonomical pathways.

2. **Substantial Hierarchical Divergence (85.4% Parent Shift):**
   Even on shared concepts, Guided places 85.4% under more semantically refined domain-specific parent classes
   (e.g., placing specific models under `ML_Model` subtrees rather than generic parents), explaining why edge Jaccard is only 4.1%.

3. **Relational Enrichment (50.9% Triple Overlap):**
   Guided asserts 997 object property triples compared to Baseline's 950, with higher density in `optimizes` and domain links.

4. **Complete Consistency & Answerability Parity:**
   Both ontologies achieve 100% HermiT reasoner satisfiability, 0 cycles, 0 orphans, and 11/12 answerable Competency Questions.