"""RAG over markdown runbooks with resilient local fallback retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
from typing import Any

from backend.utils.config import KNOWLEDGE_BASE_DIR, get_settings


@dataclass
class DocumentChunk:
    source: str
    text: str
    score: float = 0.0


class RAGService:
    def __init__(self, knowledge_base_dir: Path = KNOWLEDGE_BASE_DIR) -> None:
        self.knowledge_base_dir = knowledge_base_dir
        self._chunks: list[DocumentChunk] | None = None

    def load_documents(self) -> list[tuple[str, str]]:
        docs = []
        for path in sorted(self.knowledge_base_dir.glob("*.md")):
            docs.append((path.name, path.read_text(encoding="utf-8")))
        return docs

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
        clean = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(clean) <= chunk_size:
            return [clean]
        chunks = []
        start = 0
        while start < len(clean):
            end = min(start + chunk_size, len(clean))
            chunks.append(clean[start:end].strip())
            start = max(end - overlap, end)
        return [chunk for chunk in chunks if chunk]

    def build_index(self) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for source, text in self.load_documents():
            for chunk in self.chunk_text(text):
                chunks.append(DocumentChunk(source=source, text=chunk))
        self._chunks = chunks
        return chunks

    @property
    def chunks(self) -> list[DocumentChunk]:
        if self._chunks is None:
            return self.build_index()
        return self._chunks

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_%-]+", text.lower())

    def retrieve(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        query_terms = self._tokens(query)
        if not query_terms:
            return []
        scored: list[DocumentChunk] = []
        total_chunks = len(self.chunks) or 1
        document_frequency = {
            term: sum(1 for chunk in self.chunks if term in set(self._tokens(chunk.text))) for term in set(query_terms)
        }
        for chunk in self.chunks:
            tokens = self._tokens(chunk.text)
            if not tokens:
                continue
            token_set = set(tokens)
            score = 0.0
            for term in query_terms:
                if term in token_set:
                    tf = tokens.count(term) / len(tokens)
                    idf = math.log((1 + total_chunks) / (1 + document_frequency.get(term, 0))) + 1
                    score += tf * idf
            if score > 0:
                scored.append(DocumentChunk(source=chunk.source, text=chunk.text, score=score))
        return [
            {"source": item.source, "text": item.text, "score": round(item.score, 5)}
            for item in sorted(scored, key=lambda c: c.score, reverse=True)[:top_k]
        ]

    def answer(self, query: str, top_k: int = 4) -> dict[str, Any]:
        contexts = self.retrieve(query, top_k=top_k)
        if not contexts:
            return {
                "answer": "I could not find a matching runbook section. Try including a service name, error type, or metric.",
                "sources": [],
            }

        llm_answer = self._try_llm_answer(query, contexts)
        if llm_answer:
            return {"answer": llm_answer, "sources": contexts}

        source_names = sorted({ctx["source"] for ctx in contexts})
        bullets = []
        for ctx in contexts[:3]:
            first_lines = [line.strip("-# ") for line in ctx["text"].splitlines() if line.strip()]
            bullets.append(first_lines[0][:180] if first_lines else ctx["source"])
        answer = (
            f"Based on {', '.join(source_names)}, the likely troubleshooting path is to correlate the service symptoms "
            "with recent deployment changes, error types, and regional metrics. Key runbook evidence: "
            + " ".join(f"[{i + 1}] {bullet}." for i, bullet in enumerate(bullets))
        )
        return {"answer": answer, "sources": contexts}

    def _try_llm_answer(self, query: str, contexts: list[dict[str, Any]]) -> str | None:
        settings = get_settings()
        if settings.llm_provider == "mock":
            return None
        if not any([settings.openai_api_key, settings.groq_api_key, settings.gemini_api_key]):
            return None
        # Portfolio-friendly hook: production deployments can replace this with
        # provider-specific SDK calls while preserving the retrieval contract.
        return None


def search_docs(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    return RAGService().retrieve(query, top_k=top_k)
