# ETL 한 방에 끝 — PDF → 청크 → 임베딩 → DB (768차원)
import os, re, json
from pathlib import Path
from typing import List
import fitz  # PyMuPDF
from sqlalchemy import create_engine, text as sql, event
from dotenv import load_dotenv

# 🔧 임베딩 클라이언트
from app.services.embeddings_factory import get_embeddings_client
from sentence_transformers import SentenceTransformer

# .env 명시적으로 로드 (REPL/모듈 모두 안전)
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"


# ❌ (삭제) 잘못된/중복 초기화
# EMB = get_embeddings_client(MODEL)

# --- DB 엔진 & pgvector 어댑터 등록 ---
# pip install pgvector (중요)
try:
    from pgvector.psycopg import register_vector
except ImportError:
    raise SystemExit("`pip install pgvector`를 먼저 실행하세요.")

ENGINE = create_engine(os.environ["DATABASE_URL"], future=True)

@event.listens_for(ENGINE, "connect")
def _register_vector(dbapi_conn, conn_record):
    # psycopg3 연결에 pgvector 어댑터 등록
    register_vector(dbapi_conn)

# --- 임베딩 클라이언트 준비 (기본: e5-base-v2 = 768차원) ---
# ✅ get_embeddings_client 는 model_name이 아니라 model 로 받습니다.
# --- 임베딩 클라이언트 준비 (e5-base-v2 = 768차원 강제) ---
MODEL_ID = os.getenv("EMBED_MODEL", "intfloat/e5-base-v2").split("#",1)[0].strip()
DEVICE   = os.getenv("EMBED_DEVICE", "cpu").split("#",1)[0].strip()

_model = SentenceTransformer(MODEL_ID, device=DEVICE)

class _EmbedWrapper:
    def embed(self, texts, is_query: bool):
        # e5 계열 권장 프리픽스
        if is_query:
            texts = [f"query: {t}" for t in texts]
        else:
            texts = [f"passage: {t}" for t in texts]
        # normalize_embeddings=True → cosine/L2 일관성
        return _model.encode(texts, normalize_embeddings=True).tolist()

EMB = _EmbedWrapper()


def extract_text(pdf_path: Path) -> str:
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text("text") for page in doc)

def simple_chunk(text: str, max_chars: int = 1400) -> List[str]:
    parts = re.split(r"(\n{2,}|[.!?])", text)
    chunks, buf = [], ""
    for p in parts:
        if len(buf) + len(p) > max_chars and buf:
            chunks.append(buf.strip()); buf = p
        else:
            buf += p
    if buf.strip():
        chunks.append(buf.strip())

    merged, acc = [], ""
    for c in chunks:
        if len(acc) + len(c) < max_chars // 2:
            acc += ("" if not acc else "\n") + c
        else:
            if acc: merged.append(acc); acc = ""
            merged.append(c)
    if acc:
        merged.append(acc)
    return [c for c in merged if len(c) >= 80]

def embed_passages(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    out: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        vecs = EMB.embed(batch, is_query=False)  # 패시지 임베딩
        if not vecs:
            raise RuntimeError("Embedding returned empty batch")
        out.extend(vecs)
    # 차원 확인(768)
    if out and len(out[0]) != 768:
        raise ValueError(f"Embedding dim {len(out[0])} != 768 (DB schema)")
    return out

def main():
    pdfs = sorted(DATA_DIR.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDFs under {DATA_DIR}")
        return

    with ENGINE.begin() as conn:
        for pdf in pdfs:
            policy_type = pdf.parent.name
            doc_id = pdf.stem
            print(f"[ingest] {pdf}")

            # documents 테이블 upsert(없으면 생성)
            conn.execute(sql("""
                INSERT INTO documents (doc_id, title, source_path, meta)
                VALUES (:doc_id, :title, :source_path, :meta)
                ON CONFLICT (doc_id) DO UPDATE
                SET title = EXCLUDED.title,
                    source_path = EXCLUDED.source_path
            """), {
                "doc_id": doc_id,
                "title": doc_id,
                "source_path": str(pdf),
                "meta": json.dumps({"policy_type": policy_type})
            })

            text = extract_text(pdf)
            if not text.strip():
                print("  -> empty text, skip")
                continue

            chunks = simple_chunk(text)
            if not chunks:
                print("  -> no chunks, skip")
                continue

            embs = embed_passages(chunks)

            # document_chunks 컬럼과 맞춤 (doc_id, chunk_index, content, embedding, meta)
            rows = []
            for i, (c, e) in enumerate(zip(chunks, embs)):
                rows.append({
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "content": c,
                    "embedding": e,  # pgvector 어댑터가 list -> vector 변환
                    "meta": json.dumps({
                        "policy_type": policy_type,
                        "clause_title": None
                    })
                })

            # ⚠️ 같은 doc_id를 재적재하면 중복될 수 있음 → 필요하면 아래 주석 해제해 선삭제
            # conn.execute(sql("DELETE FROM document_chunks WHERE doc_id = :doc_id"), {"doc_id": doc_id})

            conn.execute(sql("""
                INSERT INTO document_chunks
                  (doc_id, chunk_index, content, embedding, meta)
                VALUES
                  (:doc_id, :chunk_index, :content, :embedding, :meta)
            """), rows)

            print(f"  -> chunks={len(chunks)}")

if __name__ == "__main__":
    main()
