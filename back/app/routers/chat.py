# app/routers/chat.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
from app.services.openai_service import chat as chat_llm

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatMsg(BaseModel):
    role: Literal["system","user","assistant"] = "user"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMsg] = Field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 512

class ChatResponse(BaseModel):
    reply: str

@router.post("/completion", response_model=ChatResponse)
async def completion(req: ChatRequest):
    try:
        # 기본 system 프롬프트(선택)
        msgs = req.messages
        if not any(m.role == "system" for m in msgs):
            msgs = [{"role":"system","content":"당신은 간결하고 정확한 한국어 어시스턴트입니다."}] + [m.model_dump() for m in msgs]
        out = chat_llm(msgs, temperature=req.temperature, max_tokens=req.max_tokens)
        return ChatResponse(reply=out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")
