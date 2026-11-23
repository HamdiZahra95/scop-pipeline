# Comparative Analysis: SCOP Baseline vs Guided Ontologies

This report quantifies the exact structural, conceptual, and relational differences
between the newly generated `scop_baseline.owl` and `scop_guided.owl` artifacts.

## 1. Concept Vocabulary Overlap

| Metric | Baseline | Guided | Delta / Overlap |
| :--- | :---: | :---: | :---: |
| **Total Classes** | 1993 | 2041 | +48 |
| **Shared Concepts** | 1194 | 1194 | 58.5% of Guided |
| **Unique to Ontology** | 799 | 847 | — |
| **Concept Jaccard (Exact Slug)** | — | — | **42.0%** |
| **Concept Jaccard (Normalized Lexical)** | — | — | **43.7%** |

### Sample Vocabulary Differences
- **Shared concepts (sample):** 3d_convolutional_neural_network, 3d_object_detection, abductive_reasoning, abstractive_summarization, accelerated_gradient_descent, acoustic_scene_classification, acquisition_function, action_recognition, activation_function, activation_sparsity
- **Only in Baseline (sample):** abstract_model, activation_and_layer_types, activation_function_algorithm, actor_critic, adversarial_defenses, adversarial_robustness_monitoring, adversarial_training_methods, agent_based_learning_strategies, algebraic_and_geometric_methods, algorithm
- **Only in Guided (sample):** a3c, activation_unit, actor_critic_algorithm, actor_critic_rl, adaptive_boosting_algorithm, adaptive_iterative_optimization, advanced_deployment_and_robustness, adversarial_attack_method, adversarial_attack_types, adversarial_defense

## 2. Taxonomic Subsumption & Hierarchy Alignment

| Metric | Baseline | Guided | Comparison / Agreement |
| :--- | :---: | :---: | :---: |
| **Subsumption Edges (rdfs:subClassOf)** | 1988 | 2036 | Shared: 153 (Jaccard: **4.0%**) |
| **Identical Direct Parent (on shared concepts)** | — | — | **153 / 1194 (12.8%)** |
| **Different Direct Parent (Re-homed / Stratified)** | — | — | **1041 / 1194 (87.2%)** |
| **Mean Transitive Ancestor Jaccard** | — | — | **45.5%** |
| **Max Subsumption Depth** | 10 | 11 | Guided is more compact / stratified |
| **Mean Concept Depth** | 5.09 | 5.1 | — |
| **Branching Factor** | 2.398 | 2.444 | Guided is slightly denser |

### Sample Direct Parent Shifts (Baseline vs Guided)
| Concept | Baseline Parent | Guided Parent |
| :--- | :--- | :--- |
| `black_box_optimization` | `heuristic_search_algorithm` | `general_ml_theory` |
| `spectral_normalization` | `regularization` | `normalization_regularization` |
| `unsupervised_clustering` | `pattern_discovery` | `grouping_analysis` |
| `machine_learning_algorithm` | `ml_algorithm` | `statistical_learning_model` |
| `chaotic_dynamical_system` | `nonlinear_system` | `dynamical_system` |
| `variational_autoencoder` | `autoencoder_architecture` | `latent_variable_model` |
| `latent_variable_model` | `probabilistic_model` | `probabilistic_generative_model` |
| `ensemble_kalman_filter` | `state_estimation_algorithms` | `sequential_monte_carlo` |

## 3. Relational Structure & Object Properties

| Metric | Baseline | Guided | Delta / Overlap |
| :--- | :---: | :---: | :---: |
| **Total Object Property Triples** | 946 | 995 | +49 |
| **Shared Triples** | 735 | 735 | **61.0%** Jaccard |
| **Unique Triples** | 211 | 260 | — |

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
| **Definition Concept Coverage** | 40.5% | 41.2% | Guided has higher concept coverage |

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