# app/services/vector_search.py
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict, Any

def _to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"

def retrieve_context_base(db: Session, query_vec: List[float], top_k: int = 20) -> List[Dict[str, Any]]:
    qvec_lit = _to_vector_literal(query_vec)
    sql = text("""
    SELECT
      doc_id, chunk_id, policy_type, clause_title, content,
      (embedding <=> :qvec::vector) AS score
    FROM document_chunks
    ORDER BY embedding <=> :qvec::vector
    LIMIT :k
    """)
    rows = db.execute(sql, {"qvec": qvec_lit, "k": top_k}).mappings().all()
    return [dict(r) for r in rows]
