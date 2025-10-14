# back/app/routers/report.py
from __future__ import annotations
import os, uuid, logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from functools import lru_cache

from app.db import get_db
from app.services.embeddings_factory import get_embeddings_client
from app.services.rag_service import retrieve_context as search_top_k   # ← 함수명에 맞춰 alias
from app.services.openai_service import chat as openai_chat
from app.services.pdf_report import build_pdf

log = logging.getLogger("uvicorn.error")  # uvicorn 콘솔에 찍힘

FILES_DIR = os.getenv("FILES_DIR", "files")
os.makedirs(FILES_DIR, exist_ok=True)

router = APIRouter(prefix="/qa", tags=["qa"])

# lazy-load: 첫 호출 때 1회 로드
@lru_cache
def get_emb():
    return get_embeddings_client()

# ---------- Schemas ----------
class AnswerPdfRequest(BaseModel):
    conv_id: Optional[str] = None
    question: Optional[str] = None
    policy_type: Optional[str] = None
    top_k: int = 3
    max_tokens: int = 800

class AnswerPdfResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    pdf_url: str

# ---------- Helpers ----------
def _load_history(db: Session, conv_id: str) -> List[Dict[str, str]]:
    rows = db.execute(
        text("""SELECT role, content
                FROM messages
                WHERE conv_id=:cid
                ORDER BY created_at ASC"""),
        {"cid": conv_id},
    ).mappings().all()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def _calc_confidence(scores: List[float]) -> int:
    if not scores: return 0
    avg = sum(scores) / len(scores)
    return max(0, min(100, int(avg * 100)))

# ---------- Endpoint ----------
@router.post("/answer_pdf", response_model=AnswerPdfResponse)
def answer_pdf(req: AnswerPdfRequest, db: Session = Depends(get_db)):
    try:
        # 0) 입력 정리
        question = (req.question or "").strip()
        history: List[Dict[str, str]] = []
        if not question and req.conv_id:
            history = _load_history(db, req.conv_id)
            for m in reversed(history):
                if m["role"] == "user":
                    question = m["content"].strip()
                    break
        if not question:
            raise HTTPException(status_code=400, detail="질문이 없습니다. conv_id 또는 question 중 하나는 필요합니다.")

        log.info("[answer_pdf] insurer=%s top_k=%s max_tokens=%s", req.policy_type, req.top_k, req.max_tokens)

        # 1) 임베딩 & 검색
        try:
            qvec = get_emb().embed([question])[0]
            hits = search_top_k(db, query_vec=qvec, policy_type=req.policy_type, top_k=req.top_k)
        except Exception as e:
            # 임베딩/검색 단계의 에러는 원인 로그 남기고 재전파
            log.exception("[answer_pdf] embedding/search failed")
            raise HTTPException(status_code=500, detail=f"embedding/search failed: {type(e).__name__}: {e}")

        contexts, scores = [], []
        for h in hits:
            c = (h.get("content") or "").strip()
            if c: contexts.append(c)
            s = h.get("score")
            if isinstance(s, (int, float)): scores.append(float(s))
        context_block = "\n\n---\n".join(contexts) if contexts else "관련 문서가 충분하지 않습니다."

        # 2) 프롬프트 & LLM
        sys = ("당신은 보험 문서 안내 전문가입니다. 반드시 제공된 근거(context) 범위 내에서만 답하세요. "
               "근거가 없으면 '근거 부족'이라고 답하세요.")
        convo_prefix = "\n".join([f"{m['role']}: {m['content']}" for m in history[-10:]]) if history else ""
        prompt = f"""[대화 일부]
{convo_prefix}

[사용자 질문]
{question}

[context: 검색된 근거]
{context_block}

요구사항:
- 한국어로 간결하고 정확하게 답하기
- 목록은 불릿으로
- 근거가 없으면 추측 금지
"""
        try:
            answer = openai_chat(
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=req.max_tokens,
            )
        except Exception as e:
            log.exception("[answer_pdf] LLM call failed")
            raise HTTPException(status_code=500, detail=f"llm failed: {type(e).__name__}: {e}")

        # 3) 신뢰도/적합성
        confidence = _calc_confidence(scores)
        if confidence >= 70:   fitness, reason = "ok",    "상위 근거와 일치도가 충분"
        elif confidence >= 40: fitness, reason = "check", "일부 항목 확인 필요"
        else:                  fitness, reason = "lack",  "근거 부족"

        required_docs = [k for k in ["진단서","영수증","신분증","청구서","처방전","계좌사본"] if k in answer]
        timeline = ["D+0 접수", "D+3 추가서류 확인", "D+7 지급"]

        # 4) PDF 생성/저장
        pdf_id = str(uuid.uuid4())[:8]
        pdf_path = os.path.join(FILES_DIR, f"answer_{pdf_id}.pdf")
        try:
            build_pdf({
                "conv_id": req.conv_id,
                "policy_type": req.policy_type,
                "top_k": req.top_k,
                "summary": answer,
                "fitness": fitness,
                "fitness_reason": reason,
                "confidence": confidence,
                "timeline": timeline,
                "required_docs": required_docs,
                "sources": hits,
                "links": {},
            }, pdf_path)
        except Exception as e:
            log.exception("[answer_pdf] PDF build failed")
            raise HTTPException(status_code=500, detail=f"pdf failed: {type(e).__name__}: {e}")

        # 5) 응답
        sources = [{
            "doc_id": h.get("doc_id"),
            "chunk_id": h.get("chunk_id"),
            "clause_title": h.get("clause_title"),
            "content": h.get("content", ""),
            "score": h.get("score"),
        } for h in hits]

        return AnswerPdfResponse(
            answer=answer,
            sources=sources,
            pdf_url=f"/files/{os.path.basename(pdf_path)}",
        )

    except HTTPException:
        # 이미 상태코드/메시지가 정해진 에러는 그대로 전달
        raise
    except Exception as e:
        # 마지막 안전망: 무엇이든 콘솔 스택과 타입/메시지를 detail로
        log.exception("answer_pdf failed")
        raise HTTPException(status_code=500, detail=f"answer_pdf failed: {type(e).__name__}: {e}")
