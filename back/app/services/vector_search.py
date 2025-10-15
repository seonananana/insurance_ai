# back/app/services/vector_search.py
from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

# ─────────────────────────────────────────────────────────────
# 벡터 → PostgreSQL literal 변환
# ─────────────────────────────────────────────────────────────
def _to_vector_literal(vec: List[float]) -> str:
    """리스트 → '[0.123, 0.456, ...]' 형식 문자열"""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

# ─────────────────────────────────────────────────────────────
# 보험사명 정규화 (DB 저장 명칭과 맞춤)
# ─────────────────────────────────────────────────────────────
def _norm_insurer_py(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = str(name).strip().lower().replace(" ", "")
    mapping = {
        "db손해": "db손해보험",
        "db손해보험": "db손해보험",
        "db": "db손해보험",
        "동부화재": "db손해보험",
        "현대해상": "현대해상",
        "현대해상화재": "현대해상",
        "삼성화재": "삼성화재",
        "한화손해보험": "한화손해보험",
        "kb손해보험": "kb손해보험",
        "공통": "공통",
        "표준": "공통",
        "표준약관": "공통",
    }
    return mapping.get(s, s)

# ─────────────────────────────────────────────────────────────
# 핵심 검색 함수
# ─────────────────────────────────────────────────────────────
def retrieve_context_base(
    db: Session,
    query_vec: List[float],
    top_k: int = 20,
    insurer: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    보험사별 RAG 검색 (pgvector)
    - 해당 보험사 source 우선 검색
    - 없으면 공통 문서
    - 그래도 없으면 fallback
    """
    qvec_lit = _to_vector_literal(query_vec)
    want = _norm_insurer_py(insurer)
    budget = max(int(top_k) * 6, 30)

    # ✅ 보험사 필터링 조건
    if want and want != "공통":
        sql = text("""
            SELECT
              doc_id,
              chunk_id,
              policy_type,
              clause_title,
              COALESCE(content, '')       AS content,
              COALESCE(file_name, doc_id) AS file_name,
              COALESCE(page, 0)           AS page,
              source,
              1 - (embedding <=> (:qvec)::vector) AS score
            FROM document_chunks
            WHERE source ILIKE '%' || :insurer || '%'
            ORDER BY embedding <-> (:qvec)::vector
            LIMIT :k
        """)
        params = {"qvec": qvec_lit, "k": budget, "insurer": want}
    else:
        sql = text("""
            SELECT
              doc_id,
              chunk_id,
              policy_type,
              clause_title,
              COALESCE(content, '')       AS content,
              COALESCE(file_name, doc_id) AS file_name,
              COALESCE(page, 0)           AS page,
              source,
              1 - (embedding <=> (:qvec)::vector) AS score
            FROM document_chunks
            ORDER BY embedding <-> (:qvec)::vector
            LIMIT :k
        """)
        params = {"qvec": qvec_lit, "k": budget}

    rows = db.execute(sql, params).mappings().all()
    if not rows:
        return []

    hits = [dict(r) for r in rows]

    # ✅ 1️⃣ 해당 보험사 문서 우선
    if want:
        want_hits = [h for h in hits if _norm_insurer_py(h.get("source")) == want]
        if want_hits:
            return want_hits[:top_k]

    # ✅ 2️⃣ 공통 문서 (표준약관)
    common_hits = [h for h in hits if _norm_insurer_py(h.get("source")) == "공통"]
    if common_hits:
        return common_hits[:top_k]

    # ✅ 3️⃣ 그래도 없으면 fallback
    return hits[:top_k]


# ─────────────────────────────────────────────────────────────
# 예시 출력 구조
# ─────────────────────────────────────────────────────────────
# 반환 예시:
# [
#   {
#     "doc_id": "현대암보험2504",
#     "chunk_id": 12,
#     "policy_type": "현대해상",
#     "clause_title": None,
#     "file_name": "현대암보험.pdf",
#     "page": 21,
#     "content": "암 진단시 지급 조건...",
#     "source": "현대해상",
#     "score": 0.93
#   },
#   ...
# ]
