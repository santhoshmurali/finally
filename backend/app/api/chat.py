"""Chat route: one user message in, one complete structured reply out."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import ChatRequest
from app.chat import ChatService


def create_chat_router(chat: ChatService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["chat"])

    @router.post("/chat")
    async def post_chat(body: ChatRequest) -> dict:
        return await chat.reply(body.message)

    return router
