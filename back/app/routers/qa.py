#/qa/ask 엔드포인트: 질문을 받아 임베딩 → 벡터검색 → LLM 생성 → 근거와 함께 응답.
#DB 스키마 컬럼/테이블은 rag_service에서 지정한(임의) 이름과 매칭됨.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.main import get_db
from app.schemas import AskRequest, AnswerResponse, SourceItem
from app.services.openai_service import OpenAIService
from app.services.rag_service import search_top_k, build_prompt

router = APIRouter()
_openai = OpenAIService()

@router.post("/ask", response_model=AnswerResponse)
async def ask(req: AskRequest, db: Session = Depends(get_db)):
    # 1) 질문 임베딩
    try:
        qvec = await _openai.embed([req.question])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"임베딩 생성 실패: {e}")

    # 2) pgvector 검색
    try:
        hits = search_top_k(db, query_vec=qvec[0], policy_type=req.policy_type, top_k=req.top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 검색 실패: {e}")

    # 3) 프롬프트 생성
    prompt = build_prompt(req.question, hits)

    # 4) ChatCompletion
    try:
        answer, usage, model = await _openai.chat(prompt, max_tokens=req.max_tokens)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI 호출 실패: {e}")

    # 5) 응답 변환
    sources = [SourceItem(**h) for h in hits]
    return AnswerResponse(answer=answer, sources=sources)
