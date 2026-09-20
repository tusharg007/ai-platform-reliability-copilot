"""Incident clustering engine using HDBSCAN over semantic embeddings.

Groups related reliability signals into clusters to identify coordinated
outages, correlated failures, and deployment-related regression waves.

Dependency tiers (automatic fallback):
  1. sentence-transformers  →  dense semantic embeddings
  2. sklearn TF-IDF vectors →  sparse keyword-based vectors
  3. Feature engineering    →  deterministic numeric feature vectors
  4. Rule-based grouping    →  (error_type, deployment_version) grouping

All tiers are automatically detected and used in order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from backend.services.anomaly_detector import AnomalyDetector
from backend.services.log_analyzer import LogAnalyzer
from backend.utils.config import DATA_DIR

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IncidentSignal:
    """A normalised reliability incident signal ready for clustering."""
    incident_id: str
    service_name: str
    region: str
    error_type: str
    severity: str
    error_rate: float
    p95_latency_ms: float
    deployment_version: str
    timestamp: str
    message: str = ""
    health_score: float = 100.0

    @property
    def text(self) -> str:
        """Human-readable signal text for embedding."""
        return (
            f"{self.service_name} {self.region} {self.error_type} "
            f"{self.deployment_version} error_rate={self.error_rate:.3f} "
            f"latency={self.p95_latency_ms:.0f}ms"
        )


@dataclass
class HistoricalMatch:
    """A past resolved incident that matches the current cluster pattern."""
    incident_id: str
    similarity_score: float
    service_name: str
    error_type: str
    root_cause: str
    resolution: str
    duration_minutes: int
    severity: str


@dataclass
class IncidentCluster:
    """A group of related incident signals."""
    cluster_id: str
    member_incidents: list[IncidentSignal] = field(default_factory=list)
    centroid_service: str = ""
    centroid_error_type: str = ""
    blast_radius: float = 0.0        # 0–1: coverage across services × regions
    velocity: float = 0.0            # 0–1: rate of new signals
    member_count: int = 0
    risk_score: float = 0.0
    severity: str = "SEV-4"
    historical_matches: list[HistoricalMatch] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def affected_services(self) -> list[str]:
        return list({s.service_name for s in self.member_incidents})

    @property
    def affected_regions(self) -> list[str]:
        return list({s.region for s in self.member_incidents})

    @property
    def error_types(self) -> list[str]:
        return list({s.error_type for s in self.member_incidents if s.error_type})


# ─────────────────────────────────────────────────────────────────────────────
#  IncidentClusterer
# ─────────────────────────────────────────────────────────────────────────────

# Known categorical values for feature encoding
_SERVICES = [
    "auth-service", "payment-service", "matchmaking-service",
    "player-profile-service", "notification-service",
    "game-session-service", "leaderboard-service",
]
_REGIONS = ["us-east", "us-west", "eu-central", "ap-south"]
_ERROR_TYPES = [
    "DB_CONNECTION_TIMEOUT", "AUTH_TOKEN_EXPIRED", "UPSTREAM_503",
    "CACHE_MISS_STORM", "RATE_LIMIT_EXCEEDED", "MATCHMAKING_QUEUE_TIMEOUT",
]
_VERSIONS = ["v1.8.2", "v2.0.9", "v2.1.3", "v2.1.4"]


class IncidentClusterer:
    """Groups related incident signals using semantic similarity clustering.

    The clustering pipeline:
      1. Collect active incident signals from LogAnalyzer + AnomalyDetector.
      2. Embed each signal into a vector (semantic or feature-based).
      3. Cluster vectors via HDBSCAN / DBSCAN / rule-based fallback.
      4. Compute cluster metadata: blast radius, velocity, severity.
      5. Find historical matches via cosine similarity.
    """

    def __init__(self) -> None:
        self._log_analyzer = LogAnalyzer()
        self._anomaly_detector = AnomalyDetector()
        self._embedding_model = None
        self._try_load_embedding_model()

    def _try_load_embedding_model(self) -> None:
        """Attempt to load sentence-transformers; silently fall back."""
        try:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("IncidentClusterer: using sentence-transformers embeddings")
        except ImportError:
            logger.info("IncidentClusterer: sentence-transformers not installed; using feature vectors")
        except Exception as exc:
            logger.warning("IncidentClusterer: could not load embedding model: %s", exc)

    # ── Feature Engineering ───────────────────────────────────────────────────

    def _build_feature_vector(self, signal: IncidentSignal) -> np.ndarray:
        """Build a deterministic numeric feature vector from an incident signal.

        Dimensions:
          - One-hot: service (7), region (4), error_type (6), version (4)
          - Continuous: error_rate (normalised), p95_latency (normalised),
            hour_of_day (sin/cos encoding), health_score (normalised)

        Total: 7 + 4 + 6 + 4 + 2 + 2 + 1 = 26 dimensions
        """
        def one_hot(value: str, vocab: list[str]) -> np.ndarray:
            vec = np.zeros(len(vocab))
            if value in vocab:
                vec[vocab.index(value)] = 1.0
            return vec

        # Temporal encoding
        try:
            ts = datetime.fromisoformat(signal.timestamp)
            hour = ts.hour
        except Exception:
            hour = 12
        hour_sin = np.sin(2 * np.pi * hour / 24)
        hour_cos = np.cos(2 * np.pi * hour / 24)

        parts = [
            one_hot(signal.service_name, _SERVICES),
            one_hot(signal.region, _REGIONS),
            one_hot(signal.error_type, _ERROR_TYPES),
            one_hot(signal.deployment_version, _VERSIONS),
            np.array([min(signal.error_rate, 1.0)]),
            np.array([min(signal.p95_latency_ms / 2000.0, 1.0)]),
            np.array([hour_sin, hour_cos]),
            np.array([(100.0 - signal.health_score) / 100.0]),
        ]
        return np.concatenate(parts)

    def _embed_signals(self, signals: list[IncidentSignal]) -> np.ndarray:
        """Embed incident signals into vectors for clustering."""
        if not signals:
            return np.empty((0, 26))

        if self._embedding_model is not None:
            try:
                texts = [s.text for s in signals]
                return self._embedding_model.encode(texts, show_progress_bar=False)
            except Exception as exc:
                logger.warning("Embedding failed, using feature vectors: %s", exc)

        # Feature-based fallback
        return np.vstack([self._build_feature_vector(s) for s in signals])

    # ── Signal Collection ──────────────────────────────────────────────────────

    def collect_active_signals(self, window_hours: int = 4) -> list[IncidentSignal]:
        """Gather active incident signals from all monitored services."""
        signals: list[IncidentSignal] = []
        services = self._log_analyzer.service_list()
        regions = _REGIONS

        for service in services:
            for region in regions:
                try:
                    errors = self._log_analyzer.summarize_errors(service, region)
                    if errors["total_logs"] == 0:
                        continue

                    error_rate = errors["error_rate"]
                    if error_rate < 0.03:
                        continue  # Skip healthy slices

                    latency = self._log_analyzer.calculate_latency_summary(service, region)
                    anomalies = self._anomaly_detector.detect(service, region=region)
                    health = self._anomaly_detector.get_service_health_score(service, region)

                    top_errors = errors.get("top_errors", [])
                    error_type = top_errors[0]["error_type"] if top_errors else "UNKNOWN"

                    # Infer severity
                    if error_rate >= 0.15 or latency["p95"] >= 1200:
                        severity = "SEV-2"
                    elif error_rate >= 0.05 or latency["p95"] >= 800:
                        severity = "SEV-3"
                    else:
                        severity = "SEV-4"

                    # Get deployment version from most recent log entry
                    dep_failures = self._log_analyzer.identify_deployment_related_failures(service, region)
                    version = dep_failures[0].get("deployment_version", "unknown") if dep_failures else "unknown"

                    signals.append(IncidentSignal(
                        incident_id=f"{service}:{region}:{datetime.utcnow().strftime('%Y%m%dT%H')}",
                        service_name=service,
                        region=region,
                        error_type=error_type,
                        severity=severity,
                        error_rate=error_rate,
                        p95_latency_ms=latency["p95"],
                        deployment_version=version,
                        timestamp=datetime.utcnow().isoformat(),
                        message=f"{error_type} detected in {service}/{region}",
                        health_score=health,
                    ))
                except Exception as exc:
                    logger.debug("Signal collection failed for %s/%s: %s", service, region, exc)

        logger.info("Collected %d active incident signals", len(signals))
        return signals

    # ── Clustering ────────────────────────────────────────────────────────────

    def _cluster_hdbscan(self, embeddings: np.ndarray, min_cluster_size: int) -> np.ndarray:
        """Try HDBSCAN clustering."""
        import hdbscan
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=1,
            metric="euclidean",
        )
        return clusterer.fit_predict(embeddings)

    def _cluster_dbscan(self, embeddings: np.ndarray, min_cluster_size: int) -> np.ndarray:
        """Fall back to sklearn DBSCAN."""
        from sklearn.cluster import DBSCAN
        from sklearn.preprocessing import normalize
        normed = normalize(embeddings)
        eps = 0.4 if embeddings.shape[1] <= 26 else 0.6
        clusterer = DBSCAN(eps=eps, min_samples=min(min_cluster_size, 2), metric="cosine")
        return clusterer.fit_predict(normed)

    def _cluster_rule_based(self, signals: list[IncidentSignal]) -> np.ndarray:
        """Rule-based fallback: group by (error_type, deployment_version)."""
        group_map: dict[str, int] = {}
        labels = np.full(len(signals), -1, dtype=int)
        cluster_id = 0
        for i, signal in enumerate(signals):
            key = f"{signal.error_type}:{signal.deployment_version}"
            if key not in group_map:
                group_map[key] = cluster_id
                cluster_id += 1
            labels[i] = group_map[key]
        return labels

    def cluster_incidents(
        self,
        signals: list[IncidentSignal],
        min_cluster_size: int = 2,
    ) -> list[IncidentCluster]:
        """Apply clustering to incident signals and return cluster objects."""
        if not signals:
            return []

        embeddings = self._embed_signals(signals)
        labels = np.full(len(signals), -1, dtype=int)

        for cluster_fn_name, cluster_fn in [
            ("HDBSCAN", lambda e: self._cluster_hdbscan(e, min_cluster_size)),
            ("DBSCAN", lambda e: self._cluster_dbscan(e, min_cluster_size)),
        ]:
            try:
                labels = cluster_fn(embeddings)
                logger.info("Clustering with %s succeeded", cluster_fn_name)
                break
            except ImportError:
                logger.debug("%s not available", cluster_fn_name)
            except Exception as exc:
                logger.warning("%s clustering failed: %s", cluster_fn_name, exc)

        if np.all(labels == -1):
            logger.info("Using rule-based clustering fallback")
            labels = self._cluster_rule_based(signals)

        # Build IncidentCluster objects from labels
        unique_labels = sorted({l for l in labels if l >= 0})
        clusters: list[IncidentCluster] = []
        total_services = len(_SERVICES)
        total_regions = len(_REGIONS)

        for label in unique_labels:
            members = [signals[i] for i, l in enumerate(labels) if l == label]
            if not members:
                continue

            services_affected = len({m.service_name for m in members})
            regions_affected = len({m.region for m in members})
            blast_radius = (
                (services_affected / total_services) * 0.5
                + (regions_affected / total_regions) * 0.5
            )

            # Dominant service / error type by frequency
            service_freq: dict[str, int] = {}
            error_freq: dict[str, int] = {}
            for m in members:
                service_freq[m.service_name] = service_freq.get(m.service_name, 0) + 1
                error_freq[m.error_type] = error_freq.get(m.error_type, 0) + 1
            centroid_svc = max(service_freq, key=service_freq.get)
            centroid_err = max(error_freq, key=error_freq.get)

            # Velocity: normalised member count (more = faster escalation)
            velocity = min(len(members) / 10.0, 1.0)

            cluster = IncidentCluster(
                cluster_id=f"CLU-{label:04d}",
                member_incidents=members,
                centroid_service=centroid_svc,
                centroid_error_type=centroid_err,
                blast_radius=round(blast_radius, 3),
                velocity=round(velocity, 3),
                member_count=len(members),
            )
            clusters.append(cluster)

        logger.info("Formed %d clusters from %d signals", len(clusters), len(signals))
        return clusters

    # ── Historical Matching ────────────────────────────────────────────────────

    def find_similar_historical(
        self,
        cluster: IncidentCluster,
        top_k: int = 5,
    ) -> list[HistoricalMatch]:
        """Find past resolved incidents similar to this cluster."""
        incidents_path = DATA_DIR / "incidents.csv"
        if not incidents_path.exists():
            return []

        try:
            df = pd.read_csv(incidents_path)
        except Exception:
            return []

        matches: list[HistoricalMatch] = []
        for _, row in df.iterrows():
            # Simple similarity: service match + error type match
            svc_match = str(row.get("service_name", "")) in cluster.affected_services
            err_match = str(row.get("issue_type", "")) in cluster.error_types

            if not (svc_match or err_match):
                continue

            score = 0.0
            if svc_match:
                score += 0.5
            if err_match:
                score += 0.5

            # Boost for direct service+error match
            if svc_match and err_match:
                score = 1.0

            matches.append(HistoricalMatch(
                incident_id=str(row.get("incident_id", "UNKNOWN")),
                similarity_score=round(score, 2),
                service_name=str(row.get("service_name", "")),
                error_type=str(row.get("issue_type", "")),
                root_cause=str(row.get("root_cause", "N/A")),
                resolution=str(row.get("resolution", "N/A")),
                duration_minutes=int(row.get("duration_minutes", 0)),
                severity=str(row.get("severity", "SEV-4")),
            ))

        matches.sort(key=lambda m: m.similarity_score, reverse=True)
        return matches[:top_k]

    # ── Full Analysis ──────────────────────────────────────────────────────────

    def full_clustering_analysis(self, window_hours: int = 4) -> dict[str, Any]:
        """Run the end-to-end incident clustering pipeline.

        Returns:
            clusters:            List of IncidentCluster dicts.
            unclustered:         Signals not assigned to any cluster.
            total_signals:       Total active signals found.
            blast_radius_summary: Breakdown of affected services × regions.
        """
        signals = self.collect_active_signals(window_hours)
        if not signals:
            return {
                "clusters": [],
                "unclustered": [],
                "total_signals": 0,
                "blast_radius_summary": {},
            }

        clusters = self.cluster_incidents(signals)

        # Enrich clusters with historical matches and serialise
        serialised_clusters = []
        clustered_ids = {m.incident_id for c in clusters for m in c.member_incidents}
        unclustered = [
            {
                "incident_id": s.incident_id,
                "service_name": s.service_name,
                "region": s.region,
                "error_type": s.error_type,
                "severity": s.severity,
                "error_rate": round(s.error_rate, 4),
                "p95_latency_ms": round(s.p95_latency_ms, 1),
            }
            for s in signals
            if s.incident_id not in clustered_ids
        ]

        for cluster in clusters:
            hist_matches = self.find_similar_historical(cluster)
            cluster.historical_matches = hist_matches
            serialised_clusters.append({
                "cluster_id": cluster.cluster_id,
                "centroid_service": cluster.centroid_service,
                "centroid_error_type": cluster.centroid_error_type,
                "member_count": cluster.member_count,
                "affected_services": cluster.affected_services,
                "affected_regions": cluster.affected_regions,
                "error_types": cluster.error_types,
                "blast_radius": cluster.blast_radius,
                "velocity": cluster.velocity,
                "severity": cluster.severity,
                "historical_matches": [
                    {
                        "incident_id": m.incident_id,
                        "similarity_score": m.similarity_score,
                        "root_cause": m.root_cause,
                        "resolution": m.resolution,
                        "duration_minutes": m.duration_minutes,
                    }
                    for m in hist_matches
                ],
            })

        # Blast radius summary
        all_services: set[str] = set()
        all_regions: set[str] = set()
        for c in clusters:
            all_services.update(c.affected_services)
            all_regions.update(c.affected_regions)

        return {
            "clusters": serialised_clusters,
            "unclustered": unclustered,
            "total_signals": len(signals),
            "blast_radius_summary": {
                "affected_services": sorted(all_services),
                "affected_regions": sorted(all_regions),
                "services_count": len(all_services),
                "regions_count": len(all_regions),
            },
        }
