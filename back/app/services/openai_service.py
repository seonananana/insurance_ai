
#OpenAI API 호출 래퍼: (1) 임베딩 생성, (2) 챗/완성 생성.
#모델 버전을 한 곳에서 관리하고, 예외/리트라이 정책 연결 지점 제공.

import os
from typing import List
from openai import OpenAI

_EMBED_MODEL = "text-embedding-3-large"    # 임베딩 모델 (1536차원)
_CHAT_MODEL  = "gpt-4o-mini"               # 답변 생성 모델 (필요 시 교체)

class OpenAIService:
    def __init__(self, api_key: str | None = None):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    async def embed(self, texts: List[str]) -> List[List[float]]:
        # OpenAI SDK는 동기이지만 FastAPI에서 간단히 사용 가능
        # 고부하 시, to_thread로 오프로딩하거나 비동기 HTTP 클라이언트 커스텀 권장
        resp = self.client.embeddings.create(model=_EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]

    async def chat(self, prompt: str, max_tokens: int = 600) -> str:
        resp = self.client.chat.completions.create(
            model=_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that answers based on provided insurance policy context. Cite only if grounded in given context."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()

    @property
    def chat_model(self) -> str:
        return _CHAT_MODEL
