from fastapi import APIRouter

from backend.models.schemas import ChatRequest, ChatResponse
from backend.services.agent_service import ReliabilityAgent


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    agent = ReliabilityAgent()
    return ChatResponse(**agent.answer(request.query, request.service_name, request.region, request.time_window))
