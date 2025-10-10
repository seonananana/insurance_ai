# # /qa/ask: 질문 → 임베딩 → 벡터검색 → LLM 응답(+근거)
# # /qa/search: 키워드 → 임베딩 → 벡터검색 결과 리스트
# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.orm import Session
# from pydantic import BaseModel
# from typing import Optional, List, Dict, Any

# from app.db import get_db
# from app.schemas import AskRequest, AnswerResponse, SourceItem
# from app.services.openai_service import OpenAIService
# from app.services.rag_service import search_top_k, build_prompt

# router = APIRouter()
# _openai = OpenAIService()

# @router.post("/ask", response_model=AnswerResponse)
# async def ask(req: AskRequest, db: Session = Depends(get_db)):
#     try:
#         qvec = await _openai.embed([req.question])
#         hits = search_top_k(db, query_vec=qvec[0], policy_type=req.policy_type, top_k=req.top_k)
#         prompt = build_prompt(req.question, hits)
#         answer, usage, model = await _openai.chat(prompt, max_tokens=req.max_tokens)
#         return AnswerResponse(answer=answer, sources=[SourceItem(**h) for h in hits])
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"처리 실패: {e}")

# class SearchReq(BaseModel):
#     q: str
#     policy_type: Optional[str] = None
#     top_k: int = 5

# @router.post("/search")
# async def search(req: SearchReq, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
#     try:
#         qvec = await _openai.embed([req.q])
#         hits = search_top_k(db, query_vec=qvec[0], policy_type=req.policy_type, top_k=req.top_k)
#         return [{
#             "doc_id": h["doc_id"],
#             "chunk_id": h["chunk_id"],
#             "clause_title": h.get("clause_title"),
#             "content_snippet": (h.get("content","")[:240] + ("…" if len(h.get("content",""))>240 else "")),
#             "score": h.get("score")
#         } for h in hits]
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"검색 실패: {e}")

# 결제 전 실행 코드 => 임베딩은 팩토리 사용, /ask는 간단 요약형으로 이미 동작하게
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.db import get_db
from app.schemas import AskRequest, AnswerResponse
from app.services.embeddings_factory import get_embeddings_client
from app.services.rag_service import search_top_k

router = APIRouter()
_emb = get_embeddings_client()

@router.post("/ask", response_model=AnswerResponse)
async def ask(req: AskRequest, db: Session = Depends(get_db)) -> AnswerResponse:
    try:
        qv = _emb.embed([req.question])[0]
        hits = search_top_k(db, query_vec=qv, policy_type=req.policy_type, top_k=req.top_k)
        snippets = []
        for h in hits[:2]:
            c = (h.get("content") or "").strip()
            if c:
                snippets.append(c if len(c) <= 500 else (c[:500] + "…"))
        answer = ("결제 전 모드: 검색 근거 요약\n\n" + "\n\n".join(snippets)) if snippets else "관련 문서를 찾지 못했습니다."
        sources = [{
            "doc_id": h.get("doc_id"),
            "chunk_id": h.get("chunk_id"),
            "clause_title": h.get("clause_title"),
            "content": h.get("content", ""),
            "score": h.get("score"),
        } for h in hits]
        return AnswerResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"질의 실패: {e}")

class SearchReq(AskRequest): ...
@router.post("/search")
async def search(req: SearchReq, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        qv = _emb.embed([req.question])[0]
        hits = search_top_k(db, query_vec=qv, policy_type=req.policy_type, top_k=req.top_k)
        return [{
            "doc_id": h["doc_id"],
            "chunk_id": h["chunk_id"],
            "clause_title": h.get("clause_title"),
            "content_snippet": (h.get("content","")[:240] + ("…" if len(h.get("content",""))>240 else "")),
            "score": h.get("score")
        } for h in hits]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 실패: {e}")
