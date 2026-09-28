# Balanced CQ Benchmark

## objective
This benchmark is intentionally frequency-balanced and corpus-grounded so that high-frequency generic concepts do not dominate the evaluation of both ontology-generation runs.

## benchmark design
- benchmark_id: balanced_corpus_cq_v1
- total selected concepts: 50
- total generated questions: 300
- bands: high_frequency, medium_frequency, low_frequency_important
- question types: class_identity, hierarchy, relation, property, distinction, evidence

## selected concepts by band
### high_frequency (16)
- reinforcement learning (frequency=2113)
- time (frequency=2058)
- classification (frequency=2043)
- graph (frequency=2008)
- performance (frequency=1854)
- image (frequency=1471)
- target (frequency=1385)
- text (frequency=1104)
- accuracy (frequency=1089)
- used for (frequency=1056)

### medium_frequency (18)
- parameter (frequency=642)
- hardware (frequency=553)
- loss function (frequency=521)
- audio (frequency=496)
- time series (frequency=490)
- video (frequency=490)
- unsupervised learning (frequency=428)
- ensemble (frequency=404)
- group (frequency=340)
- sum (frequency=327)

### low_frequency_important (16)
- category (frequency=192)
- required (frequency=174)
- generative adversarial network (frequency=156)
- anomaly detection (frequency=150)
- scalable (frequency=146)
- categorical (frequency=146)
- feature selection (frequency=143)
- accurate (frequency=142)
- Gaussian process (frequency=133)
- autoencoder (frequency=131)

## sample questions

- class_identity | reinforcement learning | What is reinforcement learning in the ontology, and what distinguishes it from a closely related concept?
- hierarchy | reinforcement learning | Is reinforcement learning a type, subtype, or sibling of another concept in the ontology? Identify the most plausible parent or superordinate class.
- relation | reinforcement learning | Which relation or property most naturally connects reinforcement learning to time? Explain the semantic connection.
- property | reinforcement learning | Which property best characterizes reinforcement learning, and why is it more appropriate than neighboring terms in the same domain?
- distinction | reinforcement learning | How does reinforcement learning differ from time, and under what conditions would one be preferred over the other?
- evidence | reinforcement learning | Which corpus evidence or definitional support most strongly justifies including reinforcement learning in the ontology?

This pipeline is designed to keep the benchmark comparable across runs without letting the broad, exploratory baseline benefit from an evaluation set dominated by frequent generic concepts.