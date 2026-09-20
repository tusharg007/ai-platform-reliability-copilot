"""Production-grade RAG service with hybrid search and reranking.

Retrieval pipeline:
  1. BM25/TF-IDF sparse scoring  (always available, no dependencies)
  2. Dense vector search          (sentence-transformers, optional)
  3. Reciprocal Rank Fusion       (combines sparse + dense scores)
  4. Cross-encoder reranking      (optional, improves precision)
  5. LLM synthesis                (OpenAI / Groq / Gemini, optional)
  6. Extractive fallback          (deterministic, always works)

Every tier degrades gracefully — the service is always functional.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.utils.config import KNOWLEDGE_BASE_DIR, get_settings

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    source: str
    text: str
    section: str = ""   # Section heading the chunk belongs to
    score: float = 0.0


class RAGService:
    """Hybrid retrieval-augmented generation over runbook knowledge base.

    Retrieval is a three-stage pipeline:
      Stage 1: BM25 (sparse, always available) → top-20 candidates
      Stage 2: Vector search (dense, optional)  → top-20 candidates
      Stage 3: RRF merge + optional reranking   → top-k final results
    """

    def __init__(self, knowledge_base_dir: Path = KNOWLEDGE_BASE_DIR) -> None:
        self.knowledge_base_dir = knowledge_base_dir
        self._chunks: list[DocumentChunk] | None = None
        self._embedding_model = None
        self._embeddings_cache: Any = None
        self._reranker = None
        self._try_load_models()

    def _try_load_models(self) -> None:
        """Attempt to load sentence-transformers and cross-encoder reranker."""
        try:
            from sentence_transformers import SentenceTransformer, CrossEncoder
            self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("RAGService: loaded dense embedding model (all-MiniLM-L6-v2)")
            try:
                self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                logger.info("RAGService: loaded cross-encoder reranker")
            except Exception:
                logger.info("RAGService: cross-encoder reranker not available")
        except ImportError:
            logger.info("RAGService: sentence-transformers not installed; using BM25 only")
        except Exception as exc:
            logger.warning("RAGService: model load failed: %s", exc)

    # ── Document Loading & Chunking ────────────────────────────────────────────

    def load_documents(self) -> list[tuple[str, str]]:
        """Load all markdown runbooks from the knowledge base directory."""
        docs = []
        for path in sorted(self.knowledge_base_dir.glob("*.md")):
            docs.append((path.name, path.read_text(encoding="utf-8")))
        return docs

    def _extract_section(self, text: str, position: int, full_text: str) -> str:
        """Extract the nearest preceding section heading for a text position."""
        preceding = full_text[:position]
        headings = re.findall(r"^#{1,3}\s+(.+)$", preceding, re.MULTILINE)
        return headings[-1].strip() if headings else ""

    def chunk_text(
        self, source: str, text: str, chunk_size: int = 900, overlap: int = 120
    ) -> list[DocumentChunk]:
        """Chunk a document into overlapping windows, tracking section headings."""
        clean = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(clean) <= chunk_size:
            return [DocumentChunk(source=source, text=clean, section=source)]

        chunks = []
        start = 0
        while start < len(clean):
            end = min(start + chunk_size, len(clean))
            chunk_text = clean[start:end].strip()
            if chunk_text:
                section = self._extract_section(chunk_text, start, clean)
                chunks.append(DocumentChunk(source=source, text=chunk_text, section=section))
            start = max(end - overlap, end)
        return chunks

    def build_index(self) -> list[DocumentChunk]:
        """Build the chunk index from all knowledge base documents."""
        chunks: list[DocumentChunk] = []
        for source, text in self.load_documents():
            chunks.extend(self.chunk_text(source, text))

        self._chunks = chunks

        # Pre-compute dense embeddings if model is available
        if self._embedding_model is not None and chunks:
            try:
                texts = [c.text for c in chunks]
                self._embeddings_cache = self._embedding_model.encode(
                    texts, show_progress_bar=False, batch_size=32
                )
                logger.info("RAGService: pre-computed %d embeddings", len(chunks))
            except Exception as exc:
                logger.warning("RAGService: embedding pre-computation failed: %s", exc)

        return chunks

    @property
    def chunks(self) -> list[DocumentChunk]:
        if self._chunks is None:
            self.build_index()
        return self._chunks  # type: ignore[return-value]

    # ── BM25 Sparse Retrieval ──────────────────────────────────────────────────

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_%-]+", text.lower())

    def _bm25_retrieve(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        """BM25 retrieval — returns (chunk_index, score) pairs."""
        query_terms = self._tokens(query)
        if not query_terms:
            return []

        all_chunks = self.chunks
        N = len(all_chunks)
        if N == 0:
            return []

        # Document frequency
        df: dict[str, int] = {}
        for term in set(query_terms):
            df[term] = sum(1 for c in all_chunks if term in set(self._tokens(c.text)))

        # BM25 scoring
        k1, b = 1.5, 0.75
        avg_dl = sum(len(self._tokens(c.text)) for c in all_chunks) / N

        results: list[tuple[int, float]] = []
        for idx, chunk in enumerate(all_chunks):
            tokens = self._tokens(chunk.text)
            dl = len(tokens)
            score = 0.0
            for term in query_terms:
                if term not in df or df[term] == 0:
                    continue
                tf = tokens.count(term)
                idf = math.log((N - df[term] + 0.5) / (df[term] + 0.5) + 1)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
                score += idf * tf_norm
            if score > 0:
                results.append((idx, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # ── Dense Vector Retrieval ─────────────────────────────────────────────────

    def _dense_retrieve(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        """Dense semantic retrieval via cosine similarity."""
        if self._embedding_model is None or self._embeddings_cache is None:
            return []
        try:
            import numpy as np
            q_emb = self._embedding_model.encode([query], show_progress_bar=False)
            # Cosine similarity
            norms = np.linalg.norm(self._embeddings_cache, axis=1, keepdims=True)
            q_norm = np.linalg.norm(q_emb)
            if q_norm == 0:
                return []
            similarities = (self._embeddings_cache / (norms + 1e-8)) @ (q_emb / q_norm).T
            similarities = similarities.flatten()
            top_indices = np.argsort(similarities)[::-1][:top_k]
            return [(int(i), float(similarities[i])) for i in top_indices if similarities[i] > 0.1]
        except Exception as exc:
            logger.debug("Dense retrieval failed: %s", exc)
            return []

    # ── Reciprocal Rank Fusion ─────────────────────────────────────────────────

    @staticmethod
    def _rrf_merge(
        bm25_results: list[tuple[int, float]],
        dense_results: list[tuple[int, float]],
        k: int = 60,
    ) -> list[tuple[int, float]]:
        """Combine BM25 and dense results via Reciprocal Rank Fusion."""
        rrf_scores: dict[int, float] = {}

        for rank, (idx, _) in enumerate(bm25_results):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (k + rank + 1)

        for rank, (idx, _) in enumerate(dense_results):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (k + rank + 1)

        sorted_items = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_items

    # ── Cross-Encoder Reranking ────────────────────────────────────────────────

    def _rerank(self, query: str, candidates: list[DocumentChunk]) -> list[DocumentChunk]:
        """Optional cross-encoder reranking for improved precision."""
        if self._reranker is None or len(candidates) <= 1:
            return candidates
        try:
            pairs = [(query, c.text) for c in candidates]
            scores = self._reranker.predict(pairs)
            ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
            return [c for c, _ in ranked]
        except Exception as exc:
            logger.debug("Reranking failed, using RRF order: %s", exc)
            return candidates

    # ── Main Retrieve Method ───────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """Retrieve the top-k most relevant runbook chunks for a query.

        Pipeline: BM25 sparse + dense vector → RRF merge → cross-encoder rerank.
        Always returns results (BM25 fallback guaranteed).
        """
        t0 = time.perf_counter()
        bm25 = self._bm25_retrieve(query, top_k=20)
        dense = self._dense_retrieve(query, top_k=20)

        method = "bm25"
        if dense:
            merged = self._rrf_merge(bm25, dense)
            method = "hybrid_rrf"
        else:
            merged = bm25

        # Select top-20 candidates for reranking
        candidates = [
            self.chunks[idx] for idx, _ in merged[:min(20, len(merged))]
        ]
        candidates = self._rerank(query, candidates)
        top_candidates = candidates[:top_k]

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.debug("RAG retrieve: method=%s latency=%.1fms results=%d", method, latency_ms, len(top_candidates))

        # Try to record metrics if telemetry is set up
        try:
            from backend.telemetry import get_copilot_metrics
            get_copilot_metrics().record_rag_latency(latency_ms, method)
        except Exception:
            pass

        return [
            {
                "source": c.source,
                "section": c.section,
                "text": c.text,
                "score": round(c.score, 5),
                "method": method,
            }
            for c in top_candidates
        ]

    # ── Answer Generation ──────────────────────────────────────────────────────

    def answer(self, query: str, top_k: int = 4) -> dict[str, Any]:
        """Generate a grounded answer from retrieved runbook passages."""
        contexts = self.retrieve(query, top_k=top_k)
        if not contexts:
            return {
                "answer": (
                    "I could not find a matching runbook section. "
                    "Try including a service name, error type, or metric."
                ),
                "sources": [],
            }

        llm_answer = self._try_llm_answer(query, contexts)
        if llm_answer:
            return {"answer": llm_answer, "sources": contexts}

        # Extractive fallback: synthesise answer from top runbook bullets
        source_names = sorted({ctx["source"] for ctx in contexts})
        bullets = []
        for ctx in contexts[:3]:
            lines = [
                line.strip("-# ").strip()
                for line in ctx["text"].splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if lines:
                bullets.append(lines[0][:200])

        answer_text = (
            f"Based on {', '.join(source_names)}, the recommended troubleshooting path is: "
            + " | ".join(f"[{i+1}] {b}." for i, b in enumerate(bullets))
        )
        return {"answer": answer_text, "sources": contexts}

    def _try_llm_answer(self, query: str, contexts: list[dict[str, Any]]) -> str | None:
        """Attempt to synthesise an answer using a configured LLM provider."""
        settings = get_settings()
        if settings.llm_provider == "mock":
            return None

        context_text = "\n\n---\n\n".join(
            f"[{ctx['source']}]\n{ctx['text']}" for ctx in contexts
        )
        system_prompt = (
            "You are an expert Site Reliability Engineer. "
            "Answer the question using ONLY information from the provided runbook excerpts. "
            "Cite the specific runbook file for each claim. "
            "If the answer is not in the runbooks, say so explicitly — do not invent information."
        )
        user_prompt = f"Runbook excerpts:\n{context_text}\n\nQuestion: {query}"

        # Gemini
        if settings.llm_provider == "gemini" and settings.gemini_api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.gemini_api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                resp = model.generate_content(f"{system_prompt}\n\n{user_prompt}")
                return resp.text
            except Exception as exc:
                logger.warning("Gemini LLM failed: %s", exc)

        # OpenAI
        if settings.llm_provider == "openai" and settings.openai_api_key:
            try:
                import openai
                client = openai.OpenAI(api_key=settings.openai_api_key)
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=800,
                    temperature=0.1,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                logger.warning("OpenAI LLM failed: %s", exc)

        # Groq
        if settings.llm_provider == "groq" and settings.groq_api_key:
            try:
                from groq import Groq
                client = Groq(api_key=settings.groq_api_key)
                model_name = settings.resolved_model_name
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=800,
                    temperature=0.1,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                logger.warning("Groq LLM failed (model=%s): %s", settings.resolved_model_name, exc)

        return None


def search_docs(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """Convenience function for one-off runbook searches."""
    return RAGService().retrieve(query, top_k=top_k)
