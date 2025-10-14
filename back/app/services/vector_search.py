from sqlalchemy import text
from typing import List, Dict, Any
from sqlalchemy.orm import Session

def _to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

def retrieve_context_base(db: Session, query_vec: List[float], top_k: int = 20) -> List[Dict[str, Any]]:
    qvec_lit = _to_vector_literal(query_vec)
    sql = text("""
        SELECT
          doc_id, chunk_id, policy_type, clause_title, content,
          COALESCE(file_name, doc_id) AS file_name,
          COALESCE(page, page_no)     AS page,
          1 - (embedding <=> (:qvec)::vector) AS score
        FROM document_chunks
        ORDER BY embedding <=> (:qvec)::vector
        LIMIT :k
    """)
    rows = db.execute(sql, {"qvec": qvec_lit, "k": int(top_k)}).mappings().all()
    return [dict(r) for r in rows]
