# back/etl/ingest_pdfs_to_chunks.py
"""
PDF → (페이지/청크) → E5 임베딩(768) → document_chunks UPSERT

스키마 기대 컬럼 (document_chunks):
- id SERIAL (선택)
- doc_id TEXT
- chunk_id INT
- policy_type TEXT
- clause_title TEXT NULL
- page INT
- file_name TEXT
- content TEXT
- embedding VECTOR(768)  -- pgvector
※ (doc_id, chunk_id) UNIQUE 권장
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF
from dotenv import load_dotenv
from sqlalchemy import create_engine, text as sql, event
from pgvector.sqlalchemy import Vector

# ---- 환경 로드 ----
ROOT = Path(__file__).resolve().parents[1]  # back/
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR") or (ROOT / "data"))  # ex) back/data/현대해상/*.pdf
DATABASE_URL = os.environ["DATABASE_URL"]
MODEL_ID = (os.getenv("EMBED_MODEL") or "intfloat/e5-base-v2").split("#", 1)[0].strip()
DEVICE = (os.getenv("EMBED_DEVICE") or "cpu").split("#", 1)[0].strip()
BATCH = int(os.getenv("BATCH", "64"))

# ---- 임베딩 (e5 접두사 + normalize=True) ----
from sentence_transformers import SentenceTransformer
_model = SentenceTransformer(MODEL_ID, device=DEVICE)

def embed_passages(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    # e5 계열: passage 접두사
    tagged = [f"passage: {t}" for t in texts]
    vecs = _model.encode(
        tagged,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    out = vecs.tolist()
    if out and len(out[0]) != 768:
        raise ValueError(f"Embedding dim {len(out[0])} != 768 (DB schema)")
    return out

# ---- DB 엔진 ----
ENGINE = create_engine(DATABASE_URL, future=True)

@event.listens_for(ENGINE, "connect")
def _reg_vector(dbapi_conn, conn_record):
    register_vector(dbapi_conn)

# ---- PDF → 텍스트/청크 ----
def extract_pages(pdf_path: Path) -> List[Tuple[int, str]]:
    out = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            txt = page.get_text("text")  # 필요시 "blocks"로 바꿔 재조립
            # 청크 전에 불릿/점자 과다 제거
            txt = re.sub(r"[·•●·]+", " ", txt)
            txt = re.sub(r"\s{2,}", " ", txt)
            out.append((i, txt or ""))
    return out

def split_chunks(text: str, max_chars: int = 1400) -> List[str]:
    """
    문단/문장 경계 대략 존중하면서 max_chars 기준으로 청크
    """
    if not text.strip():
        return []
    # 문단 우선 → 문장/구두점 경계 보조
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for para in paras:
        # 문장 단위 보조 split
        segs = re.split(r"([.!?]\s+)", para)
        # segs = [frag, sep, frag, sep, ...]
        merged = []
        cur = ""
        for s in segs:
            cur += s
            if re.match(r"[.!?]\s+$", s) or len(cur) > max_chars // 2:
                merged.append(cur.strip()); cur = ""
        if cur.strip():
            merged.append(cur.strip())
        # 머지된 문장 덩어리를 다시 큰 덩어리로 묶기
        for m in merged:
            if len(buf) + len(m) + 1 <= max_chars:
                buf = (buf + "\n" + m) if buf else m
            else:
                if buf:
                    chunks.append(buf.strip())
                buf = m
    if buf.strip():
        chunks.append(buf.strip())
    # 너무 짧은 조각 제거(잡음)
    return [c for c in chunks if len(c) >= 80]

# ---- 테이블/인덱스 보완 (최초 1회 유용) ----
DDL_UNIQUE = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE tablename='document_chunks' AND indexname='uq_doc_chunk'
  ) THEN
    BEGIN
      ALTER TABLE document_chunks
      ADD CONSTRAINT uq_doc_chunk UNIQUE (doc_id, chunk_id);
    EXCEPTION WHEN duplicate_table THEN
      -- 이미 존재
      NULL;
    END;
  END IF;
END $$;
"""

# 코사인 인덱스(권장) — 필요 시 수동 실행
# CREATE INDEX idx_doc_chunks_ivfflat ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);

UPSERT_SQL = """
INSERT INTO document_chunks
  (doc_id, chunk_id, policy_type, clause_title, page, file_name, content, embedding)
VALUES
  (:doc_id, :chunk_id, :policy_type, :clause_title, :page, :file_name, :content, :embedding)
ON CONFLICT (doc_id, chunk_id) DO UPDATE SET
  policy_type = EXCLUDED.policy_type,
  clause_title = EXCLUDED.clause_title,
  page        = EXCLUDED.page,
  file_name   = EXCLUDED.file_name,
  content     = EXCLUDED.content,
  embedding   = EXCLUDED.embedding;
"""

DOCS_UPSERT = """
INSERT INTO documents (doc_id, title, source_path, meta)
VALUES (:doc_id, :title, :source_path, :meta)
ON CONFLICT (doc_id) DO UPDATE
SET title = EXCLUDED.title,
    source_path = EXCLUDED.source_path,
    meta = EXCLUDED.meta;
"""

def ingest_pdf(pdf: Path, conn) -> None:
    policy_type = pdf.parent.name  # 상위 폴더명을 보험사로
    doc_id = pdf.stem
    file_name = pdf.name

    print(f"[ingest] {pdf}")

    # documents upsert
    conn.execute(sql(DOCS_UPSERT), {
        "doc_id": doc_id,
        "title": doc_id,
        "source_path": str(pdf),
        "meta": json.dumps({"policy_type": policy_type})
    })

    pages = extract_pages(pdf)
    if not pages:
        print("  -> empty doc")
        return

    rows = []
    chunk_id = 0
    for page_no, page_text in pages:
        chunks = split_chunks(page_text)
        if not chunks:
            continue
        vecs = embed_passages(chunks, batch_size=BATCH)
        for txt, vec in zip(chunks, vecs):
            rows.append({
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "policy_type": policy_type,
                "clause_title": None,     # 필요 시 규칙으로 채우세요
                "page": page_no,
                "file_name": file_name,
                "content": txt,
                "embedding": vec,         # pgvector 어댑터가 변환
            })
            chunk_id += 1

    if not rows:
        print("  -> no chunks")
        return

    # 대량 upsert
    conn.execute(sql(UPSERT_SQL), rows)
    print(f"  -> chunks upserted: {len(rows)}")

def main():
    pdfs = sorted(DATA_DIR.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDFs under {DATA_DIR}")
        return

    with ENGINE.begin() as conn:
        # 최초 1회: (doc_id,chunk_id) UNIQUE 보장 시도
        try:
            conn.execute(sql(DDL_UNIQUE))
        except Exception:
            pass

        for pdf in pdfs:
            ingest_pdf(pdf, conn)

    print("[done] ingestion complete.")

if __name__ == "__main__":
    main()
