# Concept-Level Analysis: Generated Ontology vs. ML Ontology (Humm 2026)

- **Generated ontology**: `scop_guided.owl` — 2112 data-derived concept classes (skeleton excluded).
- **Reference ontology**: `ML_Ontology.ttl` (Humm, *Applied Sciences* 2026) — 706 labelled concepts (9 categories + individuals).

> Note: the reference models ML approaches/tasks/metrics as *individuals*, whereas the generated ontology models them as *classes*. This comparison is therefore a **terminology/coverage** overlap, not a claim of structural (subsumption) equivalence.

## Overlap summary

| Match type | Count | % of generated | % of reference |
|---|---|---|---|
| Exact slug | 96 | 4.5% | 13.6% |
| Lexical (normalised) | 96 | 4.5% | 13.6% |
| Semantic (cos ≥ 0.8) | 210 | 9.9% | — |
| **Union (any match)** | **210** | **9.9%** | — |

## Terminology coverage metrics

- **Precision** (generated concepts that map to the reference): **0.099**
- **Recall** (reference concepts covered by the generated ontology): **0.156**
- **F1** (terminology overlap): **0.121**
- For context, Humm reports an F1 of 0.83 for the reference's own terminology correctness/completeness.

## Sample exact matches (shared canonical terms)

- Action Recognition
- Adaboost
- Agglomerative Clustering
- Anomaly Detection
- Artificial Neural Network
- Audio Classification
- Autoencoder
- Average Precision
- Bayesian Linear Regression
- Bayesian Neural Network
- Binary Classification
- Boosted Decision Tree
- Canonical Correlation Analysis
- Catboost
- Classification
- Clustering
- Collaborative Filtering
- Community Detection
- Conditional Random Field
- Convolutional Neural Network
- Cross Validation
- Decision Stump
- Decision Tree
- Exponential Smoothing
- F-Measure
- Feature Extraction
- Feature Selection
- Feed-Forward Neural Network
- Gated Recurrent Unit
- Gaussian Mixture Model
- Gaussian Process
- Generalized Linear Model
- Generative Adversarial Network
- Graph
- Hidden Markov Model
- Hierarchical Clustering
- Image
- Image Classification
- Image Segmentation
- Independent Component Analysis

## Reference concepts NOT covered by our ontology (596)

These are terms the curated reference has that our corpus-derived ontology lacks (recall gaps):

- ATM
- AWS Sagemaker Autopilot
- Adanet
- Adjusted Rand Score
- Alphad3m
- Analytics Zoo Chronos
- Arsenal ensemble
- Auto-Weka
- AutoCVE
- AutoML solution
- AutoTS
- Auto_TimeSeries
- Autogluon
- Autokeras
- Autopytorch
- Autosklearn
- Azure AutoML
- Bag-of-SFA-Symbols
- Bernoulli naive bayes
- BlendSearch
- Calinski Harabasz Index
- Canonical Interval Forest
- Canonical Time-series Characteristics
- Check class instance
- Check predicate declared
- Check predicates with domain and range datatypes
- Check unique class
- Configuration item
- Contractable BOSS
- Coverage
- DataRobot
- Databricks
- Datetime Featurizer
- Davies Bouldin Index
- Deep Convolutional LSTM
- Diverse Representation Canonical Interval Forest
- Elastic Ensemble
- Email Featurizer
- Enum
- EvalML
- F-measure macro
- F-measure micro
- F-measure samples
- F-measure weighted
- FEDOT
- FLAML
- Fastai
- Fresh PRINCE
- Frugal Optimization for Costrelated Hyperparameters
- GAMA
- Gaussian naives bayes
- GluonTS
- Google AutoML
- GreyKite
- H2O
- H2O Automl
- Hierarchical Vote Collective of Transformation-based Ensembles V1
- Hierarchical Vote Collective of Transformation-based Ensembles V2
- IBM AutoAI
- IBM Snap ML
- … and 536 more.

## Our concepts NOT in the reference (1902)

These are concepts our corpus surfaced that the reference does not list — a mix of genuine novelty (fine-grained/recent ML terms) and potential noise:

- 3D Convolutional Neural Network
- 3D Object Detection
- A3C
- Abductive Reasoning
- Abstractive Summarization
- Accelerated Gradient Descent
- Acoustic Scene Classification
- Acquisition Function
- Acquisitionfunction
- Activation Function
- Activation Sparsity
- Activation Unit
- Active Inference
- Active Learning
- Actor Critic Framework
- Actor-Critic Algorithm
- Actor-Critic Method
- Actor-Critic Rl
- Actorcriticmethod
- Adaptive Boosting
- Adaptive Boosting Algorithm
- Adaptive Control
- Adaptive Iterative Optimization
- Adaptive Neuro-Fuzzy Inference System
- Adaptive Sampling
- Advanced Deployment And Robustness
- Adversarial Attack
- Adversarial Attack Method
- Adversarial Attack Types
- Adversarial Attacks
- Adversarial Autoencoder
- Adversarial Defense
- Adversarial Defense Mechanism
- Adversarial Domain Adaptation
- Adversarial Example
- Adversarial Example Detection
- Adversarial Imitation Learning
- Adversarial Inference
- Adversarial Input
- Adversarial Inverse Reinforcement Learning
- Adversarial Learning
- Adversarial Loss
- Adversarial Machine Learning
- Adversarial Ml
- Adversarial Ml Security
- Adversarial Ml Task
- Adversarial Models
- Adversarial Perturbation
- Adversarial Robustness
- Adversarial Robustness And Distributed Deployment
- Adversarial Sample
- Adversarial Training
- Adversarial Variants
- Adversarialmultiarmedbandit
- Affective Computing
- Affective Computing Analysis
- Agent Configuration Based Rl Algorithm
- Agent Learning Frameworks
- Agent Learning Protocols
- Aggregation Method
- … and 1842 more.
