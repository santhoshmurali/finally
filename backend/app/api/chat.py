"""Chat routes: `/api/chat`."""

from fastapi import APIRouter, HTTPException

from app.api.deps import StateDep
from app.llm.chat_service import handle_chat
from app.llm.errors import LLMError
from app.llm.schemas import ChatHistoryItem, ChatRequest, ChatResponse
from db.chat import list_chat_messages
from db.connection import transaction

router = APIRouter(prefix="/api/chat", tags=["chat"])

LLM_FAILED_DETAIL = "The assistant could not answer. Nothing was stored; try again."


@router.post("")
async def post_chat(body: ChatRequest, state: StateDep) -> ChatResponse:
    try:
        return await handle_chat(state, body.message)
    except LLMError as error:
        raise HTTPException(status_code=502, detail=LLM_FAILED_DETAIL) from error


@router.get("/history")
def get_chat_history() -> list[ChatHistoryItem]:
    with transaction() as conn:
        messages = list_chat_messages(conn)
    return [ChatHistoryItem.model_validate(m, from_attributes=True) for m in messages]
