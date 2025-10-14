# ✅ vector_search.py (전체 교체)
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

# pgvector에 넘길 리터럴 포맷
def _to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

# document_chunks에서 보험사 구분 컬럼 자동 탐색
_CANDIDATE_COLS = [
    "insurer", "company", "provider", "namespace", "insurance_company", "policy_company"
]

def _detect_insurer_column(db: Session) -> Optional[str]:
    sql = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'document_chunks'
          AND column_name = ANY(:cols)
    """)
    rows = db.execute(sql, {"cols": _CANDIDATE_COLS}).fetchall()
    return rows[0][0] if rows else None

def _detect_vector_dims(db: Session) -> Optional[int]:
    # pgvector에 보통 vector_dims 함수가 있음(없으면 그냥 None 반환)
    try:
        dim = db.execute(
            text("SELECT vector_dims(embedding) FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1")
        ).scalar()
        return int(dim) if dim is not None else None
    except Exception:
        return None

def retrieve_context_base(
    db: Session, query_vec: List[float], top_k: int = 20, insurer: Optional[str] = None
) -> List[Dict[str, Any]]:
    # 차원 체크(가능할 때만)
    db_dim = _detect_vector_dims(db)
    if db_dim is not None and len(query_vec) != db_dim:
        raise ValueError(
            f"pgvector 차원 불일치: DB {db_dim}D vs 질의 {len(query_vec)}D. "
            f"임베딩 모델/ETL을 동일 차원으로 다시 생성하세요."
        )

    qvec_lit = _to_vector_literal(query_vec)
    insurer_col = _detect_insurer_column(db)

    where = "WHERE embedding IS NOT NULL"
    params: Dict[str, Any] = {"qvec": qvec_lit, "k": int(top_k)}

    if insurer and insurer_col:
        where += f" AND {insurer_col} = :insurer"
        params["insurer"] = insurer

    sql = text(f"""
        SELECT
          doc_id, chunk_id, policy_type, clause_title, content,
          COALESCE(file_name, doc_id) AS file_name,
          page AS page,
          1 - (embedding <=> (:qvec)::vector) AS score
        FROM document_chunks
        {where}
        ORDER BY embedding <=> (:qvec)::vector
        LIMIT :k
    """)

    rows = db.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]
