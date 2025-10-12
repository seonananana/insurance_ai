# back/app/routers/chat.py
from typing import Any, Dict, List, Optional, Literal
import inspect

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

# 기존 서비스 함수(동기 함수)
from app.services.openai_service import chat as chat_llm

router = APIRouter(prefix="/chat", tags=["chat"])

# ---- Pydantic 모델: schemas.py에 없음 → 여기서 정의 ----
class ChatMsg(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMsg] = Field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 512

class ChatResponse(BaseModel):
    reply: str

SYSTEM_PROMPT = "당신은 간결하고 정확한 한국어 어시스턴트입니다."

def _coerce_messages(msgs: List[Any]) -> List[Dict[str, Any]]:
    """Pydantic 모델/딕셔너리 섞여도 안전하게 dict 리스트로 변환."""
    out: List[Dict[str, Any]] = []
    for m in msgs:
        if hasattr(m, "model_dump"):              # Pydantic v2
            out.append(m.model_dump())
        elif isinstance(m, dict):
            out.append(m)
        else:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
            if role is None or content is None:
                raise ValueError(f"invalid message item: {m!r}")
            out.append({"role": role, "content": content})
    return out

async def _run_chat(
    msgs: List[Dict[str, Any]],
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> str:
    """chat_llm이 sync/async 어떤 형태여도 동작하도록 래핑."""
    if inspect.iscoroutinefunction(chat_llm):
        return await chat_llm(msgs, temperature=temperature, max_tokens=max_tokens)
    return await run_in_threadpool(chat_llm, msgs, temperature, max_tokens)

@router.post("/completion", response_model=ChatResponse)
async def completion(req: ChatRequest):
    try:
        msgs = _coerce_messages(req.messages)
        if not any(m.get("role") == "system" for m in msgs):
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs
        out = await _run_chat(msgs, temperature=req.temperature, max_tokens=req.max_tokens)
        return ChatResponse(reply=out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")

# 프론트 호환용 별칭(/chat/complete도 허용)
@router.post("/complete", response_model=ChatResponse)
async def completion_alias(req: ChatRequest):
    return await completion(req)
