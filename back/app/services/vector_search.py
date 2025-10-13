# app/services/vector_search.py
# 코사인 유사도
from __future__ import annotations
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

# query_vec: 768 차원 SBERT 쿼리 벡터
def retrieve_context_base(db: Session, query_vec: List[float], top_k: int = 20) -> List[Dict[str, Any]]:
    sql = text("""
    SELECT
      doc_id,
      chunk_id,
      policy_type,
      clause_title,
      content,
      (embedding <=> :qvec) AS score  -- cosine distance (lower is better)
    FROM document_chunks
    ORDER BY embedding <=> :qvec
    LIMIT :k
    """)
    rows = db.execute(sql, {"qvec": query_vec, "k": top_k}).mappings().all()
    # dict 리스트로 반환
    return [dict(r) for r in rows]
