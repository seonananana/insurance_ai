from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
from typing import List, Dict, Any

def _to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

def retrieve_context_base(db: Session, query_vec: List[float], top_k: int = 20) -> List[Dict[str, Any]]:
    qvec_lit = _to_vector_literal(query_vec)

    sql = text("""
        SELECT
          doc_id                                        AS doc_id,
          chunk_id                                      AS chunk_id,
          policy_type                                   AS policy_type,
          clause_title                                  AS clause_title,
          content                                       AS content,
          COALESCE(file_name, doc_id)                   AS file_name,
          COALESCE(page, page_no)                       AS page,
          1 - (embedding <=> (:qvec)::vector)           AS score
        FROM document_chunks
        ORDER BY embedding <=> (:qvec)::vector
        LIMIT :k
    """)

    # (선택) 바인드 명시적으로 선언하면 더 확실
    sql = sql.bindparams(
        bindparam("qvec"),
        bindparam("k", type_=int),
    )

    rows = db.execute(sql, {"qvec": qvec_lit, "k": int(top_k)}).mappings().all()
    return [dict(r) for r in rows]
