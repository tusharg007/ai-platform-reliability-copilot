from backend.services.rag_service import RAGService


def test_rag_retrieval_returns_payment_runbook():
    results = RAGService().retrieve("payment-service DB_CONNECTION_TIMEOUT deployment v2.1.4", top_k=3)
    sources = {item["source"] for item in results}
    assert "payment_service_runbook.md" in sources
