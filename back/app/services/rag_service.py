# back/app/services/rag_service.py
# -----------------------------------------------------------------------------
# 기능: pgvector 기반 벡터 검색(문서 조항 + 레퍼런스)과 프롬프트 빌드
#  - L2 거리(<->)로 정렬, 프론트에는 보기 쉬운 유사도 score = 1/(1+distance) 전달
#  - policy_type(보험사/분류) 필터 지원 (meta->>'policy_type')
#  - ETL 스키마에 맞춰 chunk_index / meta(JSON) 사용
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import List, Dict, Any, Optional
import os

from sqlalchemy import create_engine, event, text as sql
from sqlalchemy.engine import Connection

# ---------------------------
# 프롬프트 빌더
# ---------------------------
def build_prompt(question: str, passages: List[Dict[str, Any]]) -> str:
    """
    검색된 문서 청크(passages)를 사용자 질문과 함께 LLM에 전달할 프롬프트로 구성.
    passages: search_top_k() 결과 리스트
    """
    ctx_lines: List[str] = []
    for p in passages:
        title = p.get("clause_title") or ""
        txt = p.get("content", "") or ""
        if title:
            ctx_lines.append(f"[{title}]\n{txt}")
        else:
            ctx_lines.append(txt)

    instructions = (
        "- 보험 문서(약관/요약서/청구안내)에 근거하여 답하라.\n"
        "- 명확한 조항/서류명이 나오면 그대로 적어라.\n"
        "- 근거가 불충분하면 추측하지 말고 필요한 서류/절차를 안내하라.\n"
        "- 간결하게 항목별로 정리하라.\n"
    )

    prompt = f"""[지시]
{instructions}

[질문]
{question}

[근거 발췌]
{chr(10).join(ctx_lines)}
"""
    return prompt

# ---------------------------
# DB/pgvector 설정
# ---------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
ENGINE = create_engine(DATABASE_URL, future=True) if DATABASE_URL else None

try:
    from pgvector.psycopg import register_vector
except ImportError:
    register_vector = None  # 런타임에 없을 수도 있음

if ENGINE is not None and register_vector is not None:
    @event.listens_for(ENGINE, "connect")
    def _register_vector(dbapi_conn, conn_record):
        register_vector(dbapi_conn)

# ---------------------------
# 임베딩 로더 (팩토리 우선, 실패 시 ST 폴백)
# ---------------------------
def _make_embedder():
    # 1) 프로젝트 팩토리 우선 사용
    try:
        from app.services.embeddings_factory import get_embeddings_client as _get_emb
        emb_client = _get_emb()
        def _embed_query(q: str):
            # 팩토리는 is_query=True를 지원한다고 가정
            return emb_client.embed([q], is_query=True)[0]
        return _embed_query
    except Exception:
        pass

    # 2) 폴백: SentenceTransformer(e5-base-v2)
    from sentence_transformers import SentenceTransformer
    model_id = os.getenv("EMBED_MODEL", "intfloat/e5-base-v2")
    device   = os.getenv("EMBED_DEVICE", "cpu")
    st_model = SentenceTransformer(model_id, device=device)

    def _embed_query(q: str):
        # e5/BGE 계열 권장 프리픽스
        return st_model.encode([f"query: {q}"], normalize_embeddings=True).tolist()[0]

    return _embed_query

_embed_query = _make_embedder()

# ---------------------------
# 검색 함수
# ---------------------------
def _as_pgvector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

def search_top_k(db: Connection, *, query_vec: List[float], policy_type: Optional[str], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    db: SQLAlchemy Connection (ENGINE.begin() 등으로 생성)
    query_vec: 질문 임베딩 벡터
    policy_type: meta->>'policy_type' 필터 (None이면 전체)
    top_k: 상위 K개
    """
    qv = _as_pgvector_literal(query_vec)

    # ⚠️ ETL 스키마에 맞춘 SQL
    # - chunk_index 컬럼 사용
    # - clause_title은 meta JSON에서 가져옴
    # - policy_type 필터는 meta->>'policy_type'
    sqlq = """
    SELECT
      doc_id,
      chunk_index AS chunk_id,
      (meta->>'clause_title') AS clause_title,
      content,
      1.0 / (1.0 + (embedding <-> CAST(:qv AS vector))) AS score
    FROM document_chunks
    WHERE (:ptype IS NULL OR (meta->>'policy_type') = :ptype)
    ORDER BY embedding <-> CAST(:qv AS vector)
    LIMIT :k
    """

    rows = db.execute(
        sql(sqlq),
        {"qv": qv, "ptype": policy_type, "k": top_k}
    ).mappings().all()

    return [
        {
            "doc_id": r["doc_id"],
            "chunk_id": r["chunk_id"],
            "clause_title": r.get("clause_title"),
            "content": r["content"],
            "score": float(r["score"]) if r.get("score") is not None else None,
        }
        for r in rows
    ]

# ---------------------------
# Backward-compat shim
# ---------------------------
def retrieve_context(question: str, insurer: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    과거 라우터가 기대하는 API 시그니처.
    - question: 사용자 질문
    - insurer: 기존 코드에서 전달하던 필터 (policy_type과 동일 용도)
    - top_k: 반환 개수
    내부에서 질문 임베딩을 만들고, 자체 ENGINE으로 DB에 접속해 search_top_k 실행.
    """
    if ENGINE is None:
        raise RuntimeError("DATABASE_URL이 설정되지 않아 ENGINE을 생성할 수 없습니다.")

    query_vec = _embed_query(question)
    with ENGINE.begin() as conn:
        return search_top_k(conn, query_vec=query_vec, policy_type=insurer, top_k=top_k)
