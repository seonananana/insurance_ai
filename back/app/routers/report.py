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
from app.services.rag_service import search_top_k, build_prompt
from app.services.openai_service import chat as openai_chat

# PDF
from fpdf import FPDF

FILES_DIR = os.getenv("FILES_DIR", "files")
os.makedirs(FILES_DIR, exist_ok=True)

router = APIRouter(prefix="/qa", tags=["qa"])
_emb = get_embeddings_client()

class AnswerPdfRequest(BaseModel):
    conv_id: str                  # 필수: 대화방 ID
    policy_type: Optional[str] = None
    top_k: int = 3
    max_tokens: int = 800

class AnswerPdfResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    pdf_url: str

def _load_history(db: Session, conv_id: str) -> List[Dict[str,str]]:
    rows = db.execute(
        text("""SELECT role, content
               FROM messages
               WHERE conv_id=:cid
               ORDER BY created_at ASC"""),
        {"cid": conv_id},
    ).mappings().all()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

@router.post("/answer_pdf", response_model=AnswerPdfResponse)
def answer_pdf(req: AnswerPdfRequest, db: Session = Depends(get_db)):
    try:
        history = _load_history(db, req.conv_id)
        if not history:
            raise HTTPException(status_code=400, detail="대화 이력이 없습니다.")

        # 최신 user 메시지를 질문으로 사용
        last_user = None
        for m in reversed(history):
            if m["role"] == "user":
                last_user = m["content"]
                break
        if not last_user:
            raise HTTPException(status_code=400, detail="사용자 질문이 없습니다.")

        # (1) 임베딩 쿼리
        qvec = _emb.embed([last_user])[0]

        # (2) 벡터 검색
        hits = search_top_k(
            db, query_vec=qvec, policy_type=req.policy_type, top_k=req.top_k
        )

        # (3) 근거 텍스트 정리
        contexts = []
        for h in hits:
            c = (h.get("content") or "").strip()
            if not c:
                continue
            contexts.append(c)
        context_block = "\n\n---\n".join(contexts) if contexts else "관련 문서가 충분하지 않습니다."

        # (4) 프롬프트 구성: 대화 맥락 + 근거
        sys = "당신은 보험 문서 안내 전문가입니다. 반드시 제공된 근거(context) 범위 내에서만 답하세요. 근거가 없으면 '근거 부족'이라고 말하세요."
        convo_prefix = "\n".join([f"{m['role']}: {m['content']}" for m in history[-10:]])
        prompt = f"""[대화 일부]
{convo_prefix}

[사용자 질문]
{last_user}

[context: 검색된 근거]
{context_block}

요구사항:
- 한국어로 간결하고 정확하게 답하기
- 목록은 불릿으로
- 근거가 없으면 추측 금지
"""

        # (5) LLM 호출
        answer = openai_chat(
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=req.max_tokens,
        )

        # (6) PDF 생성
        pdf_id = str(uuid.uuid4())[:8]
        pdf_path = os.path.join(FILES_DIR, f"answer_{pdf_id}.pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("Nanum", "", fname=None)  # 폰트 세팅이 필요하면 임베드
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 8, txt="보험 문서 RAG 답변", align='L')
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.multi_cell(0, 6, txt="질문", align='L')
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(0, 6, txt=last_user, align='L')
        pdf.ln(3)
        pdf.set_font("Arial", "B", 12)
        pdf.multi_cell(0, 6, txt="답변", align='L')
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(0, 6, txt=answer, align='L')
        pdf.ln(3)
        pdf.set_font("Arial", "B", 12)
        pdf.multi_cell(0, 6, txt="근거(요약)", align='L')
        pdf.set_font("Arial", "", 10)
        pdf.multi_cell(0, 5, txt="\n\n---\n".join([c[:800] for c in contexts]), align='L')
        pdf.output(pdf_path)

        # (7) 소스 가공
        sources = [
            {
                "doc_id": h.get("doc_id"),
                "chunk_id": h.get("chunk_id"),
                "clause_title": h.get("clause_title"),
                "content": h.get("content", ""),
                "score": h.get("score"),
            }
            for h in hits
        ]

        return AnswerPdfResponse(
            answer=answer,
            sources=sources,
            pdf_url=f"/files/{os.path.basename(pdf_path)}",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"answer_pdf failed: {e}")
