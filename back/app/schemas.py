#API 요청/응답에 쓰이는 Pydantic 스키마 정의.
#프론트-백 사이의 명확한 계약(필드명/타입/옵션) 제공.

from pydantic import BaseModel, Field
from typing import List, Optional, Any

class AskRequest(BaseModel):
    question: str
    policy_type: Optional[str] = Field(None, description="자동차/실손/화재 등")
    top_k: int = 5
    max_tokens: int = 600

class SourceItem(BaseModel):
    doc_id: Any
    chunk_id: Any
    clause_title: Optional[str] = None
    content: str
    score: Optional[float] = None

class AnswerResponse(BaseModel):
    answer: str
    sources: List[SourceItem] = []
