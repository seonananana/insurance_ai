# app/services/rag_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import re

from sqlalchemy.orm import Session

# 프로젝트에 이미 있는 유틸들을 그대로 씁니다.
from app.services.embeddings_factory import get_embeddings_client
from app.services.rag_service import retrieve_context as _raw_retrieve_context  # ← 기존 벡터검색기(그대로 재사용)

# ─────────────────────────────────────────────────────────────
# 보험사명 정규화: 공백 제거 + 소문자 + 대표명 매핑
# ─────────────────────────────────────────────────────────────
def _norm_insurer(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = re.sub(r"\s+", "", str(name)).lower()

    # 흔히 나오는 표기들을 안전하게 대표키로 모음
    mapping = {
        # DB손해
        "db손해": "db손해",
        "db손해보험": "db손해",
        "dbinsurance": "db손해",
        # 현대해상
        "현대해상": "현대해상",
        "현대해상화재": "현대해상",
        "hyundaemarine": "현대해상",
        # 삼성화재
        "삼성화재": "삼성화재",
        "삼성화재해상": "삼성화재",
        "samsungfire": "삼성화재",
        # 공통(표준약관·가이드)
        "공통": "공통",
        "표준약관": "공통",
        "표준": "공통",
        "가이드": "공통",
    }
    return mapping.get(s, s)

# ─────────────────────────────────────────────────────────────
# 보험사 필터 적용: 요청 보험사 + '공통' 은 항상 포함
#   - chunk 사전(dict)에 insurer 메타가 없을 수도 있으니, 안전하게 처리
# ─────────────────────────────────────────────────────────────
def _insurer_ok(chunk: Dict[str, Any], want: Optional[str]) -> bool:
    if not want:
        # 보험사 미선택이면 전부 허용(공통 포함)
        return True
    ins = _norm_insurer(chunk.get("insurer") or chunk.get("company") or chunk.get("carrier"))
    return ins in {want, "공통"}

# ─────────────────────────────────────────────────────────────
# 공개 API: search_top_k
#   - 기존 retrieve_context를 그대로 호출하여 상위 후보군을 뽑고,
#     보험사 필터(요청 + '공통')를 적용한 뒤 top_k 개만 반환
#   - 필터로 모두 걸러지면 fallback: '공통'만이라도 살려서 반환
# ─────────────────────────────────────────────────────────────
def search_top_k(
    db: Session,
    query_vec: List[float],
    policy_type: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Args:
        db: SQLAlchemy 세션
        query_vec: SBERT 쿼리 벡터
        policy_type: 사용자가 고른 보험사(예: 'DB손해', '현대해상', '삼성화재')
        top_k: 반환 개수

    Returns:
        보험사 필터 적용 후 상위 top_k 청크 목록(dict 리스트)
        (각 dict 예시: {'doc_id', 'chunk_id', 'content', 'clause_title', 'insurer', 'score', ...})
    """
    # 1) 후보군 넉넉히 뽑기 (top_k의 3~4배 수준)
    #    내부 엔진은 기존 프로젝트의 retrieve_context를 그대로 사용
    budget = max(top_k * 4, 20)
    raw_hits: List[Dict[str, Any]] = _raw_retrieve_context(db, query_vec, top_k=budget)

    want = _norm_insurer(policy_type)

    # 2) 요청 보험사 + '공통' 허용 필터
    hits = [h for h in raw_hits if _insurer_ok(h, want)]

    # 3) 전부 걸러졌다면, 최소한 '공통'만이라도 반환(완전 빈 목록 방지)
    if not hits:
        hits = [h for h in raw_hits if _norm_insurer(h.get("insurer")) == "공통"]

    # 4) 최종 top_k 자르기
    return hits[:top_k]

# ─────────────────────────────────────────────────────────────
# 공개 API: retrieve_context (필요 시 외부에서 직접 쓰는 경우 호환 유지)
#   - 외부 코드가 import 하던 경로를 깨지 않기 위해 proxy 제공
# ─────────────────────────────────────────────────────────────
def retrieve_context(db: Session, query_vec: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """기존 엔진 직접 노출(하위호환 유지용)"""
    return _raw_retrieve_context(db, query_vec, top_k=top_k)
