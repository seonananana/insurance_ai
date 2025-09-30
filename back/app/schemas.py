#API 요청/응답에 쓰이는 Pydantic 스키마 정의.
#프론트-백 사이의 명확한 계약(필드명/타입/옵션) 제공.

from pydantic import BaseModel, Field
from typing import List, Optional

class AskRequest(BaseModel):
    question: str = Field(..., description="사용자 질문(한국어 권장)")
    policy_type: Optional[str] = Field(None, description="보험 종류 예: 'auto'|'medical'|'home'")
    top_k: int = Field(8, ge=1, le=20, description="RAG 검색 상위 결과 개수")
    max_tokens: int = Field(600, ge=100, le=2000, description="LLM 답변 최대 토큰")

class SourceItem(BaseModel):
    doc_id: int
    chunk_id: str
    section_path: Optional[str] = None
    clause_title: Optional[str] = None
    version: Optional[str] = None
    score: float

class AnswerResponse(BaseModel):
    answer: str
    sources: List[SourceItem]
    model: str
