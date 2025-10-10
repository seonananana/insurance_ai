#OpenAI API 호출 래퍼: (1) 임베딩 생성, (2) 챗/완성 생성.
#모델 버전을 한 곳에서 관리하고, 예외/리트라이 정책 연결 지점 제공.

import os
from typing import List, Tuple, Optional, Dict, Any
from openai import OpenAI

_EMBED_MODEL = "text-embedding-3-small"
_CHAT_MODEL  = "gpt-4o-mini"

class OpenAIService:
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY 환경변수가 필요합니다.")
        self.client = OpenAI(api_key=key)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model=_EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]

    async def chat(self, prompt: str, max_tokens: int = 600) -> Tuple[str, Optional[Dict[str, Any]], str]:
        resp = self.client.chat.completions.create(
            model=_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "보험 문서(약관/요약서/청구안내)에 근거해 답하세요. 근거가 없으면 추측하지 말고 필요한 문서를 안내하세요."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content.strip()
        usage = getattr(resp, "usage", None)
        return content, (usage.model_dump() if usage else None), resp.model

    @property
    def chat_model(self) -> str:
        return _CHAT_MODEL
