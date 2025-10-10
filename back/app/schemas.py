#API 요청/응답에 쓰이는 Pydantic 스키마 정의.
#프론트-백 사이의 명확한 계약(필드명/타입/옵션) 제공.

from typing import Optional, List, Any
from pydantic import BaseModel, Field

class AskRequest(BaseModel):
    q: str = Field(..., description="질문 텍스트")          # ← 반드시 q
    policy_type: Optional[str] = Field(None, description="보험사/분류 필터")
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

# 검색전용 요청 (AskRequest와 동일 필드, max_tokens는 무시)
class SearchRequest(BaseModel):
    q: str
    policy_type: Optional[str] = None
    top_k: int = 10
