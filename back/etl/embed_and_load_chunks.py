# back/etl/embed_and_load_chunks.py
# 목적: curated JSONL → SBERT 임베딩(파인튜닝 모델) → document_chunks 테이블 적재
# 전제: document_chunks.embedding 컬럼은 pgvector(vector(768)) 등으로 생성되어 있어야 함.

import os
import json
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy import create_engine, text
from sentence_transformers import SentenceTransformer

# -----------------------------------------------------------------------------
# 환경 변수
# -----------------------------------------------------------------------------
DATABASE_URL = os.environ["DATABASE_URL"]
SBERT_MODEL_PATH = os.getenv("SBERT_MODEL_PATH", "back/models/ins-match-embed")  # 파인튜닝 산출물 경로
BATCH_SIZE = int(os.getenv("ETL_BATCH", "64"))

# -----------------------------------------------------------------------------
# 리소스 초기화
# -----------------------------------------------------------------------------
ENGINE = create_engine(DATABASE_URL)
MODEL = SentenceTransformer(SBERT_MODEL_PATH)

# curated/<insurer>/<file>.jsonl 구조 가정
JSON_DIR = (Path(__file__).resolve().parent.parent / "data" / "curated").resolve()

# -----------------------------------------------------------------------------
# 임베딩 함수 (패시지 모드: is_query=False)
#   - E5/BGE 계열에서 쿼리/패시지 접두어가 다르지만, 여기서는 문서 청크이므로 패시지 모드
# -----------------------------------------------------------------------------
def embed_passages(texts: List[str]) -> List[List[float]]:
    # SentenceTransformer는 리스트 입력을 배치로 처리
    embs = MODEL.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    # numpy → Python list (pgvector 바인딩 호환)
    return [e.astype(float).tolist() for e in embs]

# -----------------------------------------------------------------------------
# JSONL 로드 → 배치 임베딩 → UPSERT
#   - ON CONFLICT (doc_id, chunk_id) DO UPDATE 로 재적재/증분 적재에 안전
# -----------------------------------------------------------------------------
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

def main():
    assert JSON_DIR.exists(), f"JSON_DIR not found: {JSON_DIR}"

    for jf in sorted(JSON_DIR.rglob("*.jsonl")):
        # 예: .../curated/<policy_type>/<file>.jsonl
        policy_type = jf.parts[-2]
        doc_id = jf.stem

        texts: List[str] = []
        metas: List[Dict[str, Any]] = []

        with jf.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                c = json.loads(line)
                body = (c.get("body") or "").strip()
                if not body:
                    continue
                clause_title = c.get("clause_no") or c.get("title") or None

                texts.append(body)
                metas.append({
                    "doc_id": doc_id,
                    "chunk_id": str(i),
                    "policy_type": policy_type,
                    "clause_title": clause_title,
                    "content": body,
                })

                # 배치 모아서 임베딩 후 DB 업서트
                if len(texts) >= BATCH_SIZE:
                    vecs = embed_passages(texts)
                    rows = []
                    for m, v in zip(metas, vecs):
                        rows.append({**m, "embedding": v})
                    upsert_rows(rows)
                    texts.clear()
                    metas.clear()

        # 잔여분 처리
        if texts:
            vecs = embed_passages(texts)
            rows = []
            for m, v in zip(metas, vecs):
                rows.append({**m, "embedding": v})
            upsert_rows(rows)

        print(f"[OK] {jf} → doc_id={doc_id}, policy_type={policy_type}")

if __name__ == "__main__":
    main()
