"""Lightweight retrieval over runbooks and incident history using TF-IDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.config import PREDICTIONS_DIR, RAW_DATA_DIR, RUNBOOKS_DIR


@dataclass
class RetrievalDocument:
    document_id: str
    title: str
    content: str
    source_type: str


def load_documents(runbooks_dir: Path | None = None, raw_dir: Path | None = None, predictions_dir: Path | None = None) -> list[RetrievalDocument]:
    docs: list[RetrievalDocument] = []
    books_dir = runbooks_dir or RUNBOOKS_DIR
    for path in sorted(books_dir.glob("*.md")):
        docs.append(RetrievalDocument(path.stem, path.name, path.read_text(encoding="utf-8"), "runbook"))

    raw_root = raw_dir or RAW_DATA_DIR
    known_path = raw_root / "known_incidents.csv"
    if known_path.exists():
        known_df = pd.read_csv(known_path)
        for row in known_df.to_dict(orient="records"):
            docs.append(
                RetrievalDocument(
                    document_id=str(row["incident_id"]),
                    title=f"{row['incident_id']} - {row['incident_type']}",
                    content=f"{row['description']} Affected services: {row['affected_services']}. Severity: {row['severity']}.",
                    source_type="known_incident",
                )
            )

    predicted_root = predictions_dir or PREDICTIONS_DIR
    predicted_path = predicted_root / "incidents.csv"
    if predicted_path.exists():
        predicted_df = pd.read_csv(predicted_path)
        for row in predicted_df.head(20).to_dict(orient="records"):
            docs.append(
                RetrievalDocument(
                    document_id=str(row["incident_id"]),
                    title=f"{row['incident_id']} - {row['suspected_root_cause']}",
                    content=f"{row['evidence_summary']} Next steps: {row['recommended_next_steps']}.",
                    source_type="predicted_incident",
                )
            )
    return docs


def search_documents(query: str, top_k: int = 5) -> list[dict[str, object]]:
    docs = load_documents()
    if not docs:
        return []
    texts = [doc.content for doc in docs]
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(texts + [query])
    similarities = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    ranked_indices = similarities.argsort()[::-1][:top_k]
    results = []
    for idx in ranked_indices:
        if similarities[idx] <= 0:
            continue
        doc = docs[idx]
        results.append(
            {
                "document_id": doc.document_id,
                "title": doc.title,
                "source_type": doc.source_type,
                "score": round(float(similarities[idx]), 5),
                "content": doc.content,
            }
        )
    return results


def main() -> None:
    query = "database timeout after deployment with elevated p95 latency"
    results = search_documents(query)
    print(f"Retrieved {len(results)} documents for sample query.")


if __name__ == "__main__":
    main()
