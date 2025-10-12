# back/app/routers/chat.py
from typing import Any, Dict, List, Optional, Literal
import inspect
from functools import partial

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

# ⚠️ 프로젝트의 실제 함수명에 맞추세요.
# openai_service.py에 chat 함수가 있다면 아래 import 그대로 사용.
# 만약 함수명이 chat_llm 등이라면 이 import 한 줄만 바꾸면 됩니다.
from app.services.openai_service import chat as openai_chat

router = APIRouter(prefix="/chat", tags=["chat"])

# -------------------- Pydantic 모델 --------------------
class ChatMsg(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMsg] = Field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 512

class ChatResponse(BaseModel):
    # 프론트/백엔드 양쪽 호환을 위해 두 키 모두 제공
    reply: str
    answer: Optional[str] = None

SYSTEM_PROMPT = "당신은 간결하고 정확한 한국어 어시스턴트입니다."

# -------------------- 유틸 --------------------
def _coerce_messages(msgs: List[Any]) -> List[Dict[str, Any]]:
    """Pydantic 모델/딕셔너리 혼재 시 안전하게 dict 리스트로 변환."""
    out: List[Dict[str, Any]] = []
    for m in msgs:
        if hasattr(m, "model_dump"):         # Pydantic v2
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
    """
    openai_chat이 sync/async 어떤 형태여도 동작하도록 래핑.
    ✅ 위치 인자 금지, 키워드 인자 강제로 시그니처 꼬임 방지.
    """
    if inspect.iscoroutinefunction(openai_chat):
        return await openai_chat(messages=msgs, temperature=temperature, max_tokens=max_tokens)

    func = partial(openai_chat, messages=msgs, temperature=temperature, max_tokens=max_tokens)
    return await run_in_threadpool(func)

# -------------------- 엔드포인트 --------------------
@router.post("/completion", response_model=ChatResponse)
async def completion(req: ChatRequest):
    try:
        msgs = _coerce_messages(req.messages)
        # system 프롬프트가 없으면 prepend
        if not any(m.get("role") == "system" for m in msgs):
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs

        out = await _run_chat(msgs, temperature=req.temperature, max_tokens=req.max_tokens)

        if not out or not str(out).strip():
            # 프론트에서 빈 응답으로 보이지 않게 502로 명확히 실패 처리
            raise HTTPException(status_code=502, detail="LLM returned empty response")

        text = str(out).strip()
        # reply/answer 모두 채워서 프론트 키명 불일치 문제 방지
        return ChatResponse(reply=text, answer=text)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")

# 프론트 호환용 별칭 (/chat/complete도 허용)
@router.post("/complete", response_model=ChatResponse)
async def completion_alias(req: ChatRequest):
    return await completion(req)
