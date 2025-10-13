# back/app/services/openai_service.py
# -----------------------------------------------------------------------------
# OpenAI API 호출 래퍼
#  - 임베딩 생성 (embeddings.create)
#  - 챗/완성 (chat.completions.create)
#  - 스트리밍/비스트리밍 모두 지원
#  - 환경변수 일원화: OPENAI_API_KEY, OPENAI_BASE_URL(또는 OPENAI_BASE), OPENAI_MODEL, OPENAI_EMBED_MODEL
#  - 과거 호환: chat(), complete() 별칭 및 OpenAIService 클래스 제공
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import List, Dict, Optional, Iterable, Union, Tuple, Any, Callable

import os
import time

try:
    from openai import OpenAI, AsyncOpenAI
    from openai import APIError, APIConnectionError, RateLimitError
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "The 'openai' package is required. Install with: pip install 'openai>=1.0.0'"
    ) from e


# =========================
# 환경변수/기본값
# =========================
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set in environment/.env")

# base URL: 우선순위 OPENAI_BASE_URL > OPENAI_BASE > (없으면 공백)
OPENAI_BASE_URL  = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_BASE")

# 모델 기본값
DEFAULT_CHAT_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_EMBED_MODEL  = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# 클라이언트 생성 인자
_client_kwargs = {"api_key": OPENAI_API_KEY}
if OPENAI_BASE_URL:
    _client_kwargs["base_url"] = OPENAI_BASE_URL

client = OpenAI(**_client_kwargs)
aclient = AsyncOpenAI(**_client_kwargs)  # 필요 시 async 사용


# =========================
# 공통 유틸
# =========================
def _normalize_messages(
    *,
    messages: Optional[List[Dict[str, str]]] = None,
    prompt: Optional[str] = None,
    system: Optional[str] = None
) -> List[Dict[str, str]]:
    """messages가 없으면 (system, prompt)로 구성"""
    if messages and len(messages) > 0:
        return messages
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    if prompt:
        msgs.append({"role": "user", "content": prompt})
    if not msgs:
        raise ValueError("Either `messages` or `prompt` must be provided.")
    return msgs


def _with_retries(fn: Callable[[], Any], *, retries: int = 2, backoff: float = 0.8):
    """간단한 재시도 래퍼 (429/일시적 네트워크 에러용)"""
    for i in range(retries + 1):
        try:
            return fn()
        except (RateLimitError, APIConnectionError, APIError) as e:
            if i >= retries:
                raise
            time.sleep(backoff * (2 ** i))


# =========================
# 임베딩: 동기/비동기
# =========================
def embed_texts(
    texts: List[str],
    *,
    model: Optional[str] = None
) -> List[List[float]]:
    """
    임베딩 생성 (동기). model 미지정 시 DEFAULT_EMBED_MODEL 사용.
    """
    m = model or DEFAULT_EMBED_MODEL
    resp = _with_retries(lambda: client.embeddings.create(model=m, input=texts))
    return [d.embedding for d in resp.data]


async def embed_texts_async(
    texts: List[str],
    *,
    model: Optional[str] = None
) -> List[List[float]]:
    """
    임베딩 생성 (비동기). model 미지정 시 DEFAULT_EMBED_MODEL 사용.
    """
    m = model or DEFAULT_EMBED_MODEL
    resp = await aclient.embeddings.create(model=m, input=texts)
    return [d.embedding for d in resp.data]


# =========================
# 챗 콜: 동기 (스트리밍/비스트리밍)
# =========================
def chat_llm(
    *,
    messages: Optional[List[Dict[str, str]]] = None,
    prompt: Optional[str] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 800,
    stream: bool = False,
) -> Union[str, Iterable[str]]:
    """
    - messages 또는 (prompt, system)로 호출
    - stream=False: 최종 문자열 반환
    - stream=True : 토큰 iterator[str] 반환
    """
    msgs = _normalize_messages(messages=messages, prompt=prompt, system=system)
    m = model or DEFAULT_CHAT_MODEL

    if stream:
        def _gen():
            resp = _with_retries(lambda: client.chat.completions.create(
                model=m,
                messages=msgs,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            ))
            for chunk in resp:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        return _gen()

    resp = _with_retries(lambda: client.chat.completions.create(
        model=m,
        messages=msgs,
        temperature=temperature,
        max_tokens=max_tokens,
    ))
    return resp.choices[0].message.content or ""


# =========================
# 챗 콜: 비동기 (원하면 사용)
# =========================
async def chat_llm_async(
    *,
    messages: Optional[List[Dict[str, str]]] = None,
    prompt: Optional[str] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 800,
) -> str:
    msgs = _normalize_messages(messages=messages, prompt=prompt, system=system)
    m = model or DEFAULT_CHAT_MODEL
    resp = await aclient.chat.completions.create(
        model=m,
        messages=msgs,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


# =========================
# 과거 호환: 함수 별칭
# =========================
def chat(*, messages=None, prompt=None, system=None, **kwargs):
    return chat_llm(messages=messages, prompt=prompt, system=system, **kwargs)

def complete(*, messages=None, prompt=None, system=None, **kwargs):
    return chat_llm(messages=messages, prompt=prompt, system=system, **kwargs)


# =========================
# 과거 호환: 클래스 래퍼 (동기)
#  - 기존 코드와 최대한 시그니처를 맞춤
# =========================
class OpenAIService:
    """
    과거 코드 호환용 서비스 래퍼 (동기).
    embed(), chat() 메서드 제공.
    """
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or OPENAI_API_KEY
        if not key:
            raise RuntimeError("OPENAI_API_KEY 환경변수가 필요합니다.")
        # 동일 전역 client를 그대로 씀

    def embed(self, texts: List[str]) -> List[List[float]]:
        return embed_texts(texts)

    def chat(self, prompt: str, max_tokens: int = 600) -> Tuple[str, Optional[Dict[str, Any]], str]:
        system = (
            "보험 문서(약관/요약서/청구안내)에 근거해 답하세요. "
            "근거가 없으면 추측하지 말고 필요한 문서를 안내하세요."
        )
        content = chat_llm(prompt=prompt, system=system, model=DEFAULT_CHAT_MODEL, max_tokens=max_tokens)
        # usage/model은 최신 SDK에서 resp 객체가 필요하지만, 간단 호환을 위해 None/기본값 반환
        return content.strip(), None, DEFAULT_CHAT_MODEL

    @property
    def chat_model(self) -> str:
        return DEFAULT_CHAT_MODEL
