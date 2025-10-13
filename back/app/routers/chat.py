# back/app/routers/chat.py
from typing import Any, Dict, List, Optional, Literal
import inspect
from functools import partial

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.services.openai_service import chat as openai_chat

router = APIRouter(prefix="/chat", tags=["chat"])

# ---------- 요청/응답 모델 ----------
class ChatMsg(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str

class ChatRequest(BaseModel):
    # 프론트 호환: 단일 message 또는 messages 리스트 모두 허용
    message: Optional[str] = None
    messages: List[ChatMsg] = Field(default_factory=list)

    # 선택 파라미터(있어도 없어도 동작)
    temperature: float = 0.3
    max_tokens: int = 512
    insurer: Optional[str] = None
    top_k: Optional[int] = None

class ChatResponse(BaseModel):
    reply: str
    # 프론트에서 answer 키를 읽는 경우까지 호환
    answer: Optional[str] = None

SYSTEM_PROMPT = "당신은 간결하고 정확한 한국어 어시스턴트입니다."

# ---------- 유틸 ----------
def _coerce_messages(req: ChatRequest) -> List[Dict[str, Any]]:
    """
    1) req.messages가 비었고 req.message가 있으면 → 리스트로 변환
    2) Pydantic/dict 혼재를 dict 리스트로 통일
    """
    msgs: List[Any] = req.messages or []
    if not msgs and (req.message is not None):
        msgs = [ChatMsg(role="user", content=req.message)]

    out: List[Dict[str, Any]] = []
    for m in msgs:
        if hasattr(m, "model_dump"):
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
    *,
    messages: List[Dict[str, Any]],
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> str:
    """openai_chat이 sync/async 어떤 형태여도 동작. 키워드 인자만 사용."""
    if inspect.iscoroutinefunction(openai_chat):
        return await openai_chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
    func = partial(openai_chat, messages=messages, temperature=temperature, max_tokens=max_tokens)
    return await run_in_threadpool(func)

# ---------- 엔드포인트 ----------
@router.post("/completion", response_model=ChatResponse)
async def completion(req: ChatRequest):
    try:
        msgs = _coerce_messages(req)

        # system 프롬프트 없으면 prepend
        if not any(m.get("role") == "system" for m in msgs):
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs

        out = await _run_chat(messages=msgs, temperature=req.temperature, max_tokens=req.max_tokens)

        text = (str(out) if out is not None else "").strip()
        if not text:
            raise HTTPException(status_code=502, detail="LLM returned empty response")

        return ChatResponse(reply=text, answer=text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")

@router.post("/complete", response_model=ChatResponse)
async def completion_alias(req: ChatRequest):
    return await completion(req)