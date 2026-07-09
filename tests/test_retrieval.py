from src.retrieval import search_documents


def test_retrieval_finds_database_timeout_context():
    results = search_documents("database timeout with upstream 504s", top_k=3)
    assert results
    joined = " ".join(item["title"] for item in results).lower()
    assert "database" in joined or "timeout" in joined
