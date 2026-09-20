"""Production chat endpoint with guardrails, session memory, and telemetry."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from backend.middleware.guardrails import validate_chat_input, validate_chat_output
from backend.models.schemas import ChatRequest, ChatResponse
from backend.services.agent_service import ReliabilityAgent

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """Main copilot chat endpoint with guardrails and session memory.

    Pipeline:
      1. Input validation (injection detection, rate limiting)
      2. Agent multi-step reasoning (RAG + logs + anomaly + risk + RCA)
      3. Output validation (PII check, citation verification)
      4. Return structured ChatResponse
    """
    # Extract client ID from headers or IP
    client_id = http_request.headers.get(
        "X-Client-ID",
        http_request.client.host if http_request.client else "anonymous",
    )

    # ── Input Guardrails ──────────────────────────────────────────────────────
    input_check = validate_chat_input(
        query=request.query,
        service_name=request.service_name,
        region=request.region,
        client_id=client_id,
    )
    if not input_check.passed:
        logger.warning("Input guardrail blocked: %s", input_check.reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "guardrail_violation",
                "message": input_check.reason,
                "violations": input_check.violations,
            },
        )

    # Use sanitised query if available
    effective_query = input_check.sanitized_input or request.query

    # ── Agent Execution ───────────────────────────────────────────────────────
    agent = ReliabilityAgent()
    result = agent.answer(
        query=effective_query,
        service_name=request.service_name,
        region=request.region,
        time_window=request.time_window,
        session_id=request.session_id,
    )

    # ── Output Guardrails ─────────────────────────────────────────────────────
    output_check = validate_chat_output(result, query=effective_query)
    if not output_check.passed:
        logger.error("Output guardrail tripped: %s", output_check.reason)
        # Don't leak internal details — return a safe fallback
        result["answer"] = (
            "I encountered an issue generating the response. "
            "Please rephrase your query or contact support."
        )
        result["evidence"] = ["Response validation failed — fallback activated"]

    return ChatResponse(**result)
