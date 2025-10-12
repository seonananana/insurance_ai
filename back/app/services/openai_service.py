# back/app/services/openai_service.py
"""
OpenAI LLM 호출 + RAG 결합 서비스.

- 마지막 user 메시지를 질의로 사용
- rag_service.retrieve_context()로 관련 문서 발췌 텍스트를 가져옴
- 문서 발췌를 system 프롬프트에 주입하여 Chat Completions 호출
- 항상 '문서 근거 기반' 답변을 유도, 근거가 없으면 명시적으로 알리도록 지시
"""

from __future__ import annotations

import os
from typing import List, Dict, Optional

from openai import OpenAI
from app.services.rag_service import retrieve_context  # RAG 검색 함수 사용

# ===== OpenAI 클라이언트/모델 설정 =====
# 환경변수 OPENAI_API_KEY 필요.
client = OpenAI()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _extract_user_query(messages: List[Dict[str, str]]) -> str:
    """가장 최근 user 메시지 content 추출."""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def _build_system_prompt(context_text: str) -> str:
    """
    문서 발췌를 포함한 system 프롬프트 생성.
    context_text가 비어 있어도 모델이 '근거 없음'을 분명히 말하도록 지시.
    """
    return (
        "당신은 '보험 문서 RAG 시스템'입니다. "
        "반드시 아래 [관련 문서 발췌]의 내용에 근거해서 한국어로 간결하고 정확하게 답하세요. "
        "만약 발췌가 비어 있거나 질문에 대한 근거가 없다면 "
        "'문서에서 근거를 찾지 못했습니다'라고 명확히 말하세요.\n\n"
        f"[관련 문서 발췌]\n{context_text}\n\n"
        "규칙:\n"
        "1) 문서에 명시된 사실만 사용\n"
        "2) 추측/환상 금지\n"
        "3) 필요한 경우 핵심 항목은 불릿으로 정리\n"
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
    """
    RAG + LLM 결합형 응답.
    - 인자는 반드시 키워드로 넘겨 사용(라우터에서 이미 그렇게 호출 중).
    - return: 모델의 최종 답변 텍스트(문자열).
    """
    model = model or DEFAULT_MODEL

    # 1) 질의 추출
    user_query = _extract_user_query(messages)

    # 2) 문서 검색 (insurer, top_k 반영)
    try:
        context_text = retrieve_context(user_query, insurer=insurer, top_k=top_k or 3) or ""
    except Exception as e:
        # 검색 단계에서의 오류는 모델 호출 전에 명시적으로 실패 알림
        # (필요하면 로깅/모니터링 추가)
        raise RuntimeError(f"RAG retrieval failed: {e}") from e

    # 3) system 프롬프트 구성 + 메시지 결합
    system_prompt = _build_system_prompt(context_text)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # 4) OpenAI Chat Completions 호출
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
        # 모델 호출 실패는 상위(라우터)에서 500/502로 처리
        raise RuntimeError(f"OpenAI chat failed: {e}") from e
