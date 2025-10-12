# back/app/routers/qa.py
# -----------------------------------------------------------------------------
# 기능:
#  - /qa/ask : 질문(q)을 받아 벡터검색 후 상위 청크를 간단 요약으로 답변(결제 전 모드)
#  - /qa/search : 키워드(q)로 벡터검색 결과 리스트 반환
#  - 임베딩은 embeddings_factory를 통해 로컬/OPENAI 전환 가능(.env로 스위치)
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.embeddings_factory import get_embeddings_client
from app.services.rag_service import retrieve_context
from app.schemas import AskRequest, AnswerResponse, SearchRequest

router = APIRouter(tags=["qa"])
EMB = get_embeddings_client()

def answer_question(db, question, policy_type=None, top_k=5):
    qv = EMB.embed([question], is_query=True)[0]  # 쿼리 프리픽스 적용
    passages = search_top_k(db, query_vec=qv, policy_type=policy_type, top_k=top_k)
    prompt = build_prompt(question, passages)
    # (결제 전이면 LLM 호출 없이 passages만 반환 or 로컬 규칙기반 답변)
    return {"passages": passages, "prompt": prompt}


@router.post("/ask", response_model=AnswerResponse)
async def ask(req: AskRequest, db: Session = Depends(get_db)) -> AnswerResponse:
    """
    결제 전 모드:
    - LLM 호출 없이, 벡터검색 상위 청크 1~2개를 간단 요약 형태로 합쳐서 답변.
    - 결제 후에는 build_prompt()로 프롬프트 만들고 OpenAIService.chat() 호출로 교체 가능.
    """
    try:
        # 임베딩 쿼리 벡터
        qvec = _emb.embed([req.q])[0]

        # 벡터 검색
        hits = search_top_k(
            db,
            query_vec=qvec,
            policy_type=req.policy_type,
            top_k=req.top_k,
        )

        # 간단 요약(상위 2개 청크)
        snippets: List[str] = []
        for h in hits[:2]:
            c = (h.get("content") or "").strip()
            if not c:
                continue
            snippets.append(c if len(c) <= 600 else (c[:600] + "…"))

        if snippets:
            answer = "결제 전 모드: 검색 근거 요약\n\n" + "\n\n".join(snippets)
        else:
            answer = "관련 문서를 찾지 못했습니다."

        # 근거 소스 가공
        sources: List[Dict[str, Any]] = []
        for h in hits:
            sources.append(
                {
                    "doc_id": h.get("doc_id"),
                    "chunk_id": h.get("chunk_id"),
                    "clause_title": h.get("clause_title"),
                    "content": h.get("content", ""),
                    "score": h.get("score"),
                }
            )

        return AnswerResponse(answer=answer, sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        # 서버 에러로 래핑
        raise HTTPException(status_code=500, detail=f"질의 실패: {e}")


@router.post("/search")
async def search(req: SearchRequest, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    키워드(q)로 벡터검색하여 스니펫/점수와 함께 반환.
    """
    try:
        qvec = _emb.embed([req.q])[0]

        hits = search_top_k(
            db,
            query_vec=qvec,
            policy_type=req.policy_type,
            top_k=req.top_k,
        )

        items: List[Dict[str, Any]] = []
        for h in hits:
            snippet = (h.get("content", "") or "")
            if len(snippet) > 240:
                snippet = snippet[:240] + "…"
            items.append(
                {
                    "doc_id": h.get("doc_id"),
                    "chunk_id": h.get("chunk_id"),
                    "clause_title": h.get("clause_title"),
                    "content_snippet": snippet,
                    "score": h.get("score"),
                }
            )
        return items

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 실패: {e}")
