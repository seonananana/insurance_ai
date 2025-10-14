# app/routers/report.py
from __future__ import annotations
import os, uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import get_db
from app.services.embeddings_factory import get_embeddings_client
from functools import lru_cache
from app.services.rag_service import search_top_k
from app.services.openai_service import chat as openai_chat
from app.services.pdf_report import build_pdf

# --------- settings ---------
FILES_DIR = os.getenv("FILES_DIR", "files")
os.makedirs(FILES_DIR, exist_ok=True)

router = APIRouter(prefix="/qa", tags=["qa"])

# ✅ 지연 로딩: 첫 요청에서만 임베딩 모델 로드 (부팅 시점 에러 방지)
@lru_cache
def get_emb():
    return get_embeddings_client()

# --------- schemas ----------
class AnswerPdfRequest(BaseModel):
    conv_id: Optional[str] = None        # conv가 있으면 최신 user 질문 사용
    question: Optional[str] = None       # 없으면 단일 질문으로 생성
    policy_type: Optional[str] = None
    top_k: int = 3
    max_tokens: int = 800

class AnswerPdfResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    pdf_url: str

# --------- helpers ----------
def _load_history(db: Session, conv_id: str) -> List[Dict[str,str]]:
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

# --------- endpoint ----------
@router.post("/answer_pdf", response_model=AnswerPdfResponse)
def answer_pdf(req: AnswerPdfRequest, db: Session = Depends(get_db)):
    try:
        # 0) 질문 확보 (단일 question 우선, 없으면 conv_id에서 최근 user 메시지)
        question = (req.question or "").strip()
        history: List[Dict[str,str]] = []
        if not question and req.conv_id:
            history = _load_history(db, req.conv_id)
            for m in reversed(history):
                if m["role"] == "user":
                    question = m["content"].strip()
                    break
        if not question:
            raise HTTPException(status_code=400, detail="질문이 없습니다. conv_id 또는 question 중 하나는 필요합니다.")

        # 1) 임베딩 & 검색 (요청 시 실제 임베딩 수행)
        qvec = get_emb().embed([question])[0]
        hits = search_top_k(db, query_vec=qvec, policy_type=req.policy_type, top_k=req.top_k)

        contexts, scores = [], []
        for h in hits:
            c = (h.get("content") or "").strip()
            if c: contexts.append(c)
            s = h.get("score")
            if isinstance(s, (int, float)):
                scores.append(float(s))
        context_block = "\n\n---\n".join(contexts) if contexts else "관련 문서가 충분하지 않습니다."

        # 2) 프롬프트 구성 & LLM 호출
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
        answer = openai_chat(
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=req.max_tokens,
        )

        # 3) 적합성/신뢰도 계산
        confidence = _calc_confidence(scores)
        if confidence >= 70:
            fitness, reason = "ok", "상위 근거와 일치도가 충분"
        elif confidence >= 40:
            fitness, reason = "check", "일부 항목 확인 필요"
        else:
            fitness, reason = "lack", "근거 부족"

        required_docs = [k for k in ["진단서","영수증","신분증","청구서","처방전","계좌사본"] if k in answer]
        timeline = ["D+0 접수", "D+3 추가서류 확인", "D+7 지급"]

        # 4) PDF 생성 (디스크 저장)
        pdf_id = str(uuid.uuid4())[:8]
        pdf_path = os.path.join(FILES_DIR, f"answer_{pdf_id}.pdf")
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
        raise
    except Exception as e:
        # 임베딩/검색/LLM 어떤 단계든 실패 시 500 반환
        raise HTTPException(status_code=500, detail=f"answer_pdf failed: {e}")
