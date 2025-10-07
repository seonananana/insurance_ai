# /qa/ask: 질문 → 임베딩 → 벡터검색 → LLM 응답(+근거)
# /qa/search: 키워드 → 임베딩 → 벡터검색 결과 리스트
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.db import get_db
from app.schemas import AskRequest, AnswerResponse, SourceItem
from app.services.openai_service import OpenAIService
from app.services.rag_service import search_top_k, build_prompt

router = APIRouter()
_openai = OpenAIService()

@router.post("/ask", response_model=AnswerResponse)
async def ask(req: AskRequest, db: Session = Depends(get_db)):
    try:
        qvec = await _openai.embed([req.question])
        hits = search_top_k(db, query_vec=qvec[0], policy_type=req.policy_type, top_k=req.top_k)
        prompt = build_prompt(req.question, hits)
        answer, usage, model = await _openai.chat(prompt, max_tokens=req.max_tokens)
        return AnswerResponse(answer=answer, sources=[SourceItem(**h) for h in hits])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"처리 실패: {e}")

class SearchReq(BaseModel):
    q: str
    policy_type: Optional[str] = None
    top_k: int = 5

@router.post("/search")
async def search(req: SearchReq, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        qvec = await _openai.embed([req.q])
        hits = search_top_k(db, query_vec=qvec[0], policy_type=req.policy_type, top_k=req.top_k)
        return [{
            "doc_id": h["doc_id"],
            "chunk_id": h["chunk_id"],
            "clause_title": h.get("clause_title"),
            "content_snippet": (h.get("content","")[:240] + ("…" if len(h.get("content",""))>240 else "")),
            "score": h.get("score")
        } for h in hits]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 실패: {e}")
