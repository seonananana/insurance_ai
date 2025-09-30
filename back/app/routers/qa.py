"""
파일 기능 요약
- /qa/ask 엔드포인트: 질문을 받아 임베딩 → 벡터검색 → LLM 생성 → 근거와 함께 응답.
- DB 스키마 컬럼/테이블은 rag_service에서 지정한(임의) 이름과 매칭됨.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from typing import List
from app.models.schemas import AskRequest, AnswerResponse, SourceItem
from app.services.openai_service import OpenAIService
from app.services.rag_service import search_top_k, build_prompt

router = APIRouter()

def get_services(req: Request) -> tuple[OpenAIService, any]:
    if not getattr(req.app.state, "db_pool", None):
        raise HTTPException(500, "DB pool not initialized")
    if not getattr(req.app.state, "openai_api_key", None):
        raise HTTPException(500, "OpenAI API key not configured")
    return OpenAIService(api_key=req.app.state.openai_api_key), req.app.state.db_pool

@router.post("/ask", response_model=AnswerResponse)
async def ask(body: AskRequest, svc=Depends(get_services)):
    openai_svc, pool = svc

    # 1) 질문을 임베딩
    [query_vec] = await openai_svc.embed([body.question])

    # 2) 벡터 검색 (RAG)
    passages = await search_top_k(pool, query_vec=query_vec, policy_type=body.policy_type, top_k=body.top_k)
    if not passages:
        raise HTTPException(404, "Relevant context not found")

    # 3) 프롬프트 구성 & LLM 호출
    prompt = build_prompt(body.question, passages)
    answer = await openai_svc.chat(prompt, max_tokens=body.max_tokens)

    # 4) 소스 축약(프론트 표시에 필요한 최소 메타)
    sources: List[SourceItem] = []
    for p in passages:
        sources.append(SourceItem(
            doc_id=int(p["doc_id"]) if p.get("doc_id") is not None else 0,
            chunk_id=str(p.get("chunk_id") or ""),
            section_path=p.get("section_path"),
            clause_title=p.get("clause_title"),
            version=p.get("version"),
            score=float(p.get("score") or 0.0),
        ))

    return AnswerResponse(answer=answer, sources=sources, model=openai_svc.chat_model)
