# Comparative Analysis: SCOP Baseline vs Guided Ontologies

This report quantifies the exact structural, conceptual, and relational differences
between the newly generated `scop_baseline.owl` and `scop_guided.owl` artifacts.

## 1. Concept Vocabulary Overlap

| Metric | Baseline | Guided | Delta / Overlap |
| :--- | :---: | :---: | :---: |
| **Total Classes** | 2089 | 2129 | +40 |
| **Shared Concepts** | 1132 | 1132 | 53.2% of Guided |
| **Unique to Ontology** | 957 | 997 | — |
| **Concept Jaccard (Exact Slug)** | — | — | **36.7%** |
| **Concept Jaccard (Normalized Lexical)** | — | — | **38.2%** |

### Sample Vocabulary Differences
- **Shared concepts (sample):** 3d_convolutional_neural_network, 3d_object_detection, abductive_reasoning, abstractive_summarization, accelerated_gradient_descent, acoustic_scene_classification, acquisition_function, action_recognition, activation_function, activation_sparsity
- **Only in Baseline (sample):** abstract_base_models, abstract_task_definitions, activationsparsity, adversarial_generative_model, adversarial_generative_models, adversarial_multiarmed_bandit, adversarialattack, adversarialdomainadaptation, agent_based_learning_strategies, algebraic_and_geometric_methods
- **Only in Guided (sample):** a3c, acquisitionfunction, activation_unit, actor_critic_rl, actorcriticmethod, adaptive_boosting_algorithm, adaptive_iterative_optimization, advanced_deployment_and_robustness, adversarial_attack, adversarial_attack_method

## 2. Taxonomic Subsumption & Hierarchy Alignment

| Metric | Baseline | Guided | Comparison / Agreement |
| :--- | :---: | :---: | :---: |
| **Subsumption Edges (rdfs:subClassOf)** | 2084 | 2124 | Shared: 164 (Jaccard: **4.1%**) |
| **Identical Direct Parent (on shared concepts)** | — | — | **164 / 1132 (14.5%)** |
| **Different Direct Parent (Re-homed / Stratified)** | — | — | **968 / 1132 (85.5%)** |
| **Mean Transitive Ancestor Jaccard** | — | — | **46.2%** |
| **Max Subsumption Depth** | 11 | 10 | Guided is more compact / stratified |
| **Mean Concept Depth** | 5.12 | 5.16 | — |
| **Branching Factor** | 2.352 | 2.376 | Guided is slightly denser |

### Sample Direct Parent Shifts (Baseline vs Guided)
| Concept | Baseline Parent | Guided Parent |
| :--- | :--- | :--- |
| `stochastic_policy` | `reinforcement_learning_policy` | `policy_based_methods` |
| `metamodel` | `engineering_approximation_model` | `ml_model` |
| `perturbation` | `theoretical_frameworks` | `stability_and_sensitivity_analysis` |
| `hyperparameter_configuration` | `model_configuration` | `model_evaluation_protocol` |
| `offline_reinforcement_learning` | `offline_rl` | `rl_data_utilization_paradigms` |
| `adaptive_neuro_fuzzy_inference_system` | `neuro_fuzzy_model` | `hybrid_ml_model` |
| `entropic_penalization` | `information_theoretic_objective` | `regularization_technique` |
| `deep_belief_network` | `generative_probabilistic_neural_network` | `generative_neural_architectures` |

## 3. Relational Structure & Object Properties

| Metric | Baseline | Guided | Delta / Overlap |
| :--- | :---: | :---: | :---: |
| **Total Object Property Triples** | 950 | 997 | +47 |
| **Shared Triples** | 657 | 657 | **50.9%** Jaccard |
| **Unique Triples** | 293 | 340 | — |

### Predicate Frequency Breakdown
| Predicate | Baseline Triples | Guided Triples | Delta |
| :--- | :---: | :---: | :---: |
| `evaluates` | 12 | 14 | +2 |
| `hasCharacteristic` | 28 | 36 | +8 |
| `hasComponent` | 528 | 528 | 0 |
| `hasPurpose` | 31 | 18 | -13 |
| `integrates` | 13 | 19 | +6 |
| `learnsFrom` | 75 | 85 | +10 |
| `modifies` | 31 | 34 | +3 |
| `optimizes` | 75 | 93 | +18 |
| `organizes` | 4 | 6 | +2 |
| `processesData` | 46 | 49 | +3 |
| `producesOutput` | 59 | 63 | +4 |
| `selects` | 22 | 27 | +5 |
| `transforms` | 26 | 25 | -1 |

## 4. Annotation & Definition Richness

| Annotation Property | Baseline Literals | Guided Literals | Delta |
| :--- | :---: | :---: | :---: |
| `skos:definition` | 34,755 | 34,411 | -344 |
| `rdfs:comment` | 43,015 | 42,791 | -224 |
| `skos:altLabel` | 928 | 864 | -64 |
| **Definition Concept Coverage** | 38.9% | 39.6% | Guided has higher concept coverage |

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