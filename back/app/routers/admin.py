# back/app/routers/admin.py
# -----------------------------------------------------------------------------
# 기능: 관리자용 라우터
#  - 문서 업로드(API)
#  - 텍스트 추출 및 청크화
#  - OpenAI 임베딩 생성
#  - PostgreSQL(document_chunks)에 적재
# -----------------------------------------------------------------------------

from fastapi import APIRouter, UploadFile, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.openai_service import embed_texts
from app.services.rag_service import get_engine
import uuid, os

router = APIRouter()

@router.post("/upload")
async def upload_doc(file: UploadFile):
    try:
        raw_text = (await file.read()).decode("utf-8", errors="ignore")
        chunks = [raw_text[i:i+1000] for i in range(0, len(raw_text), 1000)]  # 간단 청크
        embeddings = embed_texts(chunks)

        engine = get_engine()
        with engine.begin() as conn:
            for chunk, vec in zip(chunks, embeddings):
                conn.execute(text("""
                    INSERT INTO document_chunks (doc_id, chunk_id, policy_type, clause_title, content, embedding)
                    VALUES (:doc_id, :chunk_id, :ptype, :title, :content, :emb::vector)
                """).bindparams(
                    emb=str(vec).replace(" ", "")
                ), {
                    "doc_id": str(uuid.uuid4()),
                    "chunk_id": str(uuid.uuid4()),
                    "ptype": "자동차",
                    "title": file.filename,
                    "content": chunk,
                })

        return {"ok": True, "msg": f"{file.filename} 업로드 및 임베딩 완료", "chunks": len(chunks)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 실패: {e}")
