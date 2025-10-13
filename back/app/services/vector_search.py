# app/services/vector_search.py
from __future__ import annotations
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

def _to_vector_literal(vec: List[float]) -> str:
    # pgvector 텍스트 리터럴: "[v1,v2,...]"
    # 소수점 자릿수는 너무 길 필요 없고, 6~8자리면 충분
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"

def retrieve_context_base(db: Session, query_vec: List[float], top_k: int = 20) -> List[Dict[str, Any]]:
    qvec_lit = _to_vector_literal(query_vec)
    sql = text("""
    SELECT
      doc_id,
      chunk_id,
      policy_type,
      clause_title,
      content,
      (embedding <=> :qvec::vector) AS score   -- cosine distance (작을수록 유사)
    FROM document_chunks
    ORDER BY embedding <=> :qvec::vector
    LIMIT :k
    """)
    # 쿼리 파라미터로 문자열 전달 → ::vector 캐스팅
    rows = db.execute(sql, {"qvec": qvec_lit, "k": top_k}).mappings().all()
    return [dict(r) for r in rows]
