# back/app/services/openai_service.py
from __future__ import annotations

import os
from typing import List, Dict, Optional

from openai import OpenAI
from app.services.rag_service import retrieve_context, init_indices

# OpenAI 설정
client = OpenAI(timeout=60.0)  # 네트워크 지연 보호
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# 서버 초기화 시(임베딩/인덱스 준비). 불러만 놓고 실패해도 첫 요청 때 lazy-init됨.
try:
    init_indices()
except Exception as e:
    print(f"[OPENAI] RAG init warning: {e}")

def _extract_user_query(messages: List[Dict[str, str]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""

def _build_system_prompt(context_text: str) -> str:
    return (
        "당신은 '보험 문서 RAG 시스템'입니다. "
        "반드시 아래 [관련 문서 발췌]의 내용에 근거해서 한국어로 간결하고 정확하게 답하세요. "
        "발췌가 비어 있거나 충분한 근거가 없으면 '문서에서 근거를 찾지 못했습니다'라고 답하세요.\n\n"
        f"[관련 문서 발췌]\n{context_text}\n\n"
        "규칙:\n"
        "1) 문서에 명시된 사실만 사용\n"
        "2) 추측/환상 금지\n"
        "3) 필요한 경우 핵심 항목은 불릿으로 정리\n"
        "4) 답변 말미에 (파일명 p.xx) 형태로 근거 표기"
    )

def chat(
    *,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 512,
    insurer: Optional[str] = None,
    top_k: Optional[int] = 3,
    model: Optional[str] = None,
) -> str:
    model = model or DEFAULT_MODEL

    # 1) 사용자 질의
    user_query = _extract_user_query(messages)
    print(f"[RAG] query={user_query!r} insurer={insurer} top_k={top_k}")

    # 2) 컨텍스트 검색 (SBERT + FAISS)
    try:
        context_text = retrieve_context(user_query, insurer=insurer, top_k=top_k) or ""
        print(f"[RAG] context_len={len(context_text)}")
    except Exception as e:
        return f"문서 검색 중 오류가 발생했습니다: {e}"

    if not context_text.strip():
        return "문서에서 관련 근거를 찾지 못했습니다. 보험사 선택/Top-K/인덱스를 확인해주세요."

    # 3) system 프롬프트 구성 + 메시지 합치기
    system_prompt = _build_system_prompt(context_text)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # 4) LLM 호출
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content if resp.choices else ""
        return (content or "").strip()
    except Exception as e:
        return f"LLM 호출 중 오류가 발생했습니다: {e}"
