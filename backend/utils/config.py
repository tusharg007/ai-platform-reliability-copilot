"""Runtime configuration helpers for the reliability copilot."""

from functools import lru_cache
from pathlib import Path
import os


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
KNOWLEDGE_BASE_DIR = ROOT_DIR / "knowledge_base"
VECTOR_STORE_DIR = ROOT_DIR / ".chroma"


class Settings:
    app_name: str = "AI Platform Reliability Copilot"
    environment: str = os.getenv("APP_ENV", "local")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock").lower()
    embedding_model_name: str = os.getenv(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
