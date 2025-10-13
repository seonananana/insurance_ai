# back/etl/embed_and_load_chunks.py
# 목적: curated JSONL → SBERT 임베딩(파인튜닝 모델) → document_chunks 테이블 업서트
# 전제:
#   - document_chunks: (doc_id TEXT NOT NULL, chunk_id TEXT NOT NULL UNIQUE ON doc_id,chunk_id)
#   - embedding: vector(768)  -- SBERT 차원과 일치
#   - policy_type, clause_title, content 컬럼 존재
# 권장:
#   - 인덱스: ivfflat (embedding vector_cosine_ops) WITH (lists=100)

import os
import json
import gzip
from pathlib import Path
from typing import List, Dict, Any, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError, OperationalError
from sentence_transformers import SentenceTransformer

# -----------------------------------------------------------------------------
# 환경 변수
# -----------------------------------------------------------------------------
DATABASE_URL = os.environ["DATABASE_URL"]
SBERT_MODEL_PATH = os.getenv("SBERT_MODEL_PATH", "back/models/ins-match-embed").strip()
BATCH_SIZE = int(os.getenv("ETL_BATCH", "64"))

# -----------------------------------------------------------------------------
# 경로 보정 및 리소스 초기화
# -----------------------------------------------------------------------------
# 상대경로가 들어왔을 때 현재 파일(back/) 기준으로 보정
if not (SBERT_MODEL_PATH.startswith("/") or "://" in SBERT_MODEL_PATH):
    SBERT_MODEL_PATH = str((Path(__file__).resolve().parent.parent / SBERT_MODEL_PATH).resolve())

print(f"[embed] Using SBERT model: {SBERT_MODEL_PATH}")
MODEL = SentenceTransformer(SBERT_MODEL_PATH)

ENGINE = create_engine(DATABASE_URL)

# curated/<policy_type>/<file>.jsonl(.gz) 구조 가정
JSON_DIR = (Path(__file__).resolve().parent.parent / "data" / "curated").resolve()


# -----------------------------------------------------------------------------
# 유틸
# -----------------------------------------------------------------------------
def _open_jsonl(path: Path) -> Iterable[str]:
    if str(path).endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                yield line
    else:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                yield line


def embed_passages(texts: List[str]) -> List[List[float]]:
    # normalize_embeddings=True → cosine 거리와 잘 맞음 (DB 인덱스 vector_cosine_ops 권장)
    embs = MODEL.encode(texts, normalize_embeddings=True, convert_to_numpy=True, batch_size=BATCH_SIZE)
    return [e.astype(float).tolist() for e in embs]


# -----------------------------------------------------------------------------
# 사전 준비: 제약/인덱스 없으면 만들기(권한 없으면 건너뜀)
# -----------------------------------------------------------------------------
PREP_SQL = [
    # SBERT 차원으로 컬럼이 안 맞는 경우를 대비해 안내 (권한 없으면 실패할 수 있음)
    # 실제 ALTER는 DBA가 선행했어야 안전. 여기서는 존재 확인/생성 시도만.
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1
        FROM   pg_indexes
        WHERE  schemaname = 'public'
        AND    indexname = 'idx_doc_chunks_ivfflat'
      ) THEN
        BEGIN
          CREATE INDEX idx_doc_chunks_ivfflat
            ON document_chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        EXCEPTION WHEN others THEN
          -- 권한 없거나 타입 불일치면 무시
          NULL;
        END;
      END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint
        WHERE  conname = 'uq_document_chunks_doc_chunk'
      ) THEN
        BEGIN
          ALTER TABLE document_chunks
            ADD CONSTRAINT uq_document_chunks_doc_chunk UNIQUE (doc_id, chunk_id);
        EXCEPTION WHEN others THEN
          NULL;
        END;
      END IF;
    END $$;
    """,
]

UPSERT_SQL = text("""
INSERT INTO document_chunks
  (doc_id, chunk_id, policy_type, clause_title, content, embedding)
VALUES
  (:doc_id, :chunk_id, :policy_type, :clause_title, :content, :embedding)
ON CONFLICT (doc_id, chunk_id) DO UPDATE SET
  policy_type  = EXCLUDED.policy_type,
  clause_title = EXCLUDED.clause_title,
  content      = EXCLUDED.content,
  embedding    = EXCLUDED.embedding
""")

def upsert_rows(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with ENGINE.begin() as conn:
        conn.execute(UPSERT_SQL, rows)


def run_preparation():
    with ENGINE.begin() as conn:
        for sql in PREP_SQL:
            try:
                conn.execute(text(sql))
            except (ProgrammingError, OperationalError):
                # 권한/타입 이슈시 무시하고 진행
                pass


# -----------------------------------------------------------------------------
# 메인
# -----------------------------------------------------------------------------
def main():
    assert JSON_DIR.exists(), f"JSON_DIR not found: {JSON_DIR}"

    run_preparation()

    # *.jsonl 와 *.jsonl.gz 모두 처리
    files = sorted(list(JSON_DIR.rglob("*.jsonl")) + list(JSON_DIR.rglob("*.jsonl.gz")))
    if not files:
        print(f"[embed] No JSONL files under: {JSON_DIR}")
        return

    for jf in files:
        # 예: .../curated/<policy_type>/<file>.jsonl
        # <policy_type> 디렉터리명을 그대로 사용
        try:
            policy_type = jf.parts[-2]
        except IndexError:
            policy_type = "unknown"

        doc_id = jf.stem.replace(".jsonl", "")  # .jsonl.gz 고려
        if doc_id.endswith(".gz"):
            doc_id = doc_id[:-3]

        texts: List[str] = []
        metas: List[Dict[str, Any]] = []

        for i, line in enumerate(_open_jsonl(jf)):
            c = json.loads(line)
            body = (c.get("body") or "").strip()
            if not body:
                continue
            clause_title = c.get("clause_no") or c.get("title") or None

            texts.append(body)
            metas.append({
                "doc_id": doc_id,
                "chunk_id": str(i),        # Neon 스키마: TEXT
                "policy_type": policy_type,
                "clause_title": clause_title,
                "content": body,
            })

            if len(texts) >= BATCH_SIZE:
                vecs = embed_passages(texts)
                rows = [{**m, "embedding": v} for m, v in zip(metas, vecs)]
                upsert_rows(rows)
                texts.clear()
                metas.clear()

        # 잔여분 처리
        if texts:
            vecs = embed_passages(texts)
            rows = [{**m, "embedding": v} for m, v in zip(metas, vecs)]
            upsert_rows(rows)

        print(f"[OK] {jf} → doc_id={doc_id}, policy_type={policy_type}")

if __name__ == "__main__":
    main()
