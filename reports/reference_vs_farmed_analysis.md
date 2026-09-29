# Reference ML Ontology vs. Full Farmed Vocabulary (44k)

- Reference (Humm 2026): **710** labelled concepts.
- Farmed vocabulary (`gemma_payload.json`, pre-gate): **42938** unique concepts.
- Frequency gate used by the trunk: corpus_frequency > **10**.

## Coverage of reference concepts in the farmed vocabulary

| Category | Count | % of reference |
|---|---|---|
| Present AND high-frequency (kept by gate) | 67 | 9.4% |
| Present BUT low-frequency (gated out) | 66 | 9.3% |
| **Lexically present (any freq)** | **133** | **18.7%** |
| Additionally reachable semantically (cos ≥ 0.8) | 73 | 10.3% |
| **Total reachable (lexical ∪ semantic)** | **206** | **29.0%** |
| Not found at all | 504 | 71.0% |

### Interpretation

- **Present but gated out** = the reference term WAS farmed from the corpus but fell below the frequency threshold, so it is a *gating* choice, not a farming gap. Widening the gate would recover these.
- **Not found at all** = the term never appeared as a farmed core concept (genuine corpus/farming gap, or out-of-scope for arXiv ML abstracts, e.g. AutoML product names).

## Reference concepts present but GATED OUT (low frequency) — 66

Recoverable by lowering the frequency gate:

- agglomerative clustering  (farmed as “agglomerative clustering”, freq=10)
- Orthogonal Matching Pursuit  (farmed as “orthogonal matching pursuit”, freq=10)
- association rule learning  (farmed as “association rule learning”, freq=9)
- affinity propagation  (farmed as “affinity propagation”, freq=9)
- boosted decision tree  (farmed as “boosted decision tree”, freq=9)
- xgboost  (farmed as “XGBoost”, freq=9)
- XGBoost  (farmed as “XGBoost”, freq=9)
- k-means  (farmed as “k-means++”, freq=8)
- light gradient boosting machine  (farmed as “light gradient boosting machine”, freq=8)
- kernel approximation  (farmed as “kernel approximation”, freq=7)
- audio classification  (farmed as “audio classification”, freq=6)
- gradient boosting tree  (farmed as “gradient boosting tree”, freq=6)
- multivariate regression  (farmed as “multivariate regression”, freq=6)
- polynomial regression  (farmed as “polynomial regression”, freq=6)
- autoregressive integrated moving average  (farmed as “autoregressive integrated moving average”, freq=5)
- Quadratic Discriminant Analysis  (farmed as “quadratic discriminant analysis”, freq=5)
- stacking ensemble  (farmed as “stacking ensemble”, freq=5)
- temporal fusion transformer  (farmed as “temporal fusion transformer”, freq=5)
- Bayesian linear regression  (farmed as “bayesian linear regression”, freq=4)
- density-based spatial clustering of applications with noise  (farmed as “density-based spatial clustering of applications with noise”, freq=4)
- Markov model  (farmed as “markov model”, freq=4)
- kullback-leibler divergence  (farmed as “Kullback-Leibler divergence”, freq=4)
- video classification  (farmed as “video classification”, freq=3)
- F-measure  (farmed as “f-measure”, freq=3)
- normalized discounted cumulative gain  (farmed as “normalized discounted cumulative gain”, freq=3)
- TensorFlow  (farmed as “tensorflow”, freq=3)
- Multi-Scale Convolutional Neural Networks  (farmed as “multi-scale convolutional neural network”, freq=2)
- poisson regression  (farmed as “poisson regression”, freq=2)
- radial basis function kernel  (farmed as “radial basis function kernel”, freq=2)
- coefficient of determination  (farmed as “coefficient of determination”, freq=2)
- mean absolute error  (farmed as “mean absolute error”, freq=2)
- feature reduction  (farmed as “feature reduction”, freq=1)
- ranking  (farmed as “ranking”, freq=1)
- text regression  (farmed as “text regression”, freq=1)
- video object tracking  (farmed as “video object tracking”, freq=1)
- catboost  (farmed as “Catboost”, freq=1)
- conceptual clustering  (farmed as “conceptual clustering”, freq=1)
- ensemble  (farmed as “ensemble”, freq=1)
- exponential smoothing  (farmed as “exponential smoothing”, freq=1)
- extra tree  (farmed as “extra trees”, freq=1)
- k-modes  (farmed as “k-modes”, freq=1)
- kernel svm  (farmed as “kernel SVM”, freq=1)
- Lasso regression  (farmed as “lasso regression”, freq=1)
- local linear embedding  (farmed as “local linear embedding”, freq=1)
- Mean shift Clustering  (farmed as “mean shift clustering”, freq=1)
- prophet  (farmed as “prophet”, freq=1)
- Proximity Forest  (farmed as “proximity forest”, freq=1)
- decision stump  (farmed as “decision stump”, freq=1)
- RANdom SAmple Consensus  (farmed as “random sample consensus”, freq=1)
- Temporal Dictionary Ensemble  (farmed as “temporal dictionary ensemble”, freq=1)
- Time Series Combination of Heterogeneous and Integrated Embedding Forest  (farmed as “time series combination of heterogeneous and integrated embedding forest”, freq=1)
- Time series forest  (farmed as “time series forest”, freq=1)
- average precision  (farmed as “average precision”, freq=1)
- balanced accuracy  (farmed as “balanced accuracy”, freq=1)
- cosine similarity  (farmed as “cosine similarity”, freq=1)
- false discovery rate  (farmed as “false discovery rate”, freq=1)
- intersection over union  (farmed as “intersection over union”, freq=1)
- log loss  (farmed as “log loss”, freq=1)
- mean absolute percentage error  (farmed as “mean absolute percentage error”, freq=1)
- receiver operating characteristic curve  (farmed as “receiver operating characteristic curve”, freq=1)
- … and 6 more.

## Reference concepts NOT found in the farmed vocabulary — 504

- ATM
- AWS Sagemaker Autopilot
- Alphad3m
- Analytics Zoo Chronos
- Arsenal ensemble
- Auto-Weka
- AutoCVE
- AutoTS
- Auto_TimeSeries
- Autogluon
- Autokeras
- Autopytorch
- Azure AutoML
- Bag-of-SFA-Symbols
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
- Diverse Representation Canonical Interval Forest
- Elastic Ensemble
- Email Featurizer
- Enum
- EvalML
- F-measure macro
- F-measure micro
- FEDOT
- FLAML
- Fastai
- Fresh PRINCE
- Frugal Optimization for Costrelated Hyperparameters
- GAMA
- GluonTS
- GreyKite
- H2O
- H2O Automl
- Hierarchical Vote Collective of Transformation-based Ensembles V1
- Hierarchical Vote Collective of Transformation-based Ensembles V2
- IBM AutoAI
- IBM Snap ML
- Individual BOSS
- Inference rule broader inheritance
- Jaccard
- Jaccard macro
- Jaccard micro
- Jaccard samples
- Jaccard weighted
- Kats
- Keras
- Kohonen network
- … and 444 more.
