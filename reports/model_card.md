# Model Card

This repository uses lightweight analytics models rather than a large generative model by default.

- Primary ML component: Isolation Forest for anomaly scoring over hourly synthetic service metrics.
- Retrieval component: TF-IDF over markdown runbooks and incident records.
- Intended use: local, production-oriented prototype for AI-assisted reliability analytics using synthetic platform logs.
- Not intended for: autonomous incident response in real production systems without human review.
