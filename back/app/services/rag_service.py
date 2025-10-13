# app/services/rag_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import re

from sqlalchemy.orm import Session

# 기존의 "벡터 검색 쿼리" 순수 로직은 순환참조를 피하기 위해 별도 모듈로 분리해두세요.
# 예: app/services/vector_search.py 내에 retrieve_context_base(db, query_vec, top_k)
from app.services.vector_search import retrieve_context_base  # ← 새로 분리한 모듈

# ─────────────────────────────────────────────────────────────
# 보험사명 정규화: 공백 제거 + 소문자 + 대표명 매핑
# ─────────────────────────────────────────────────────────────
def _norm_insurer(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = re.sub(r"\s+", "", str(name)).lower()

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
# 보험사 필터 적용: 요청 보험사 + '공통' 포함
#   - 검색 히트 dict에 'policy_type' 키가 들어온다고 가정
# ─────────────────────────────────────────────────────────────
def _insurer_ok(chunk: Dict[str, Any], want: Optional[str]) -> bool:
    if not want:
        # 보험사 미지정 시 전부 허용
        return True
    # 히트 메타에서 우선적으로 policy_type 사용
    ins_raw = chunk.get("policy_type") or chunk.get("insurer") or chunk.get("company") or chunk.get("carrier")
    ins = _norm_insurer(ins_raw)
    return ins in {want, "공통"}

# ─────────────────────────────────────────────────────────────
# 공개 API: search_top_k
#   - 벡터 검색 상위 후보군을 넉넉히 뽑고(기본 top_k*4),
#     보험사 필터(요청 + '공통') 적용 후 최종 top_k 반환
#   - 모두 걸러질 경우 '공통'만이라도 폴백
# ─────────────────────────────────────────────────────────────
def search_top_k(
    db: Session,
    query_vec: List[float],
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Args:
        db: SQLAlchemy 세션
        query_vec: SBERT 쿼리 벡터 (차원 = 모델 차원)
        insurer: 사용자가 고른 보험사(예: 'DB손해', '현대해상', '삼성화재'). None이면 전체.
        top_k: 반환 개수

    Returns:
        보험사 필터 적용 후 상위 top_k 청크 목록(dict 리스트)
        (각 dict 예: {'doc_id','chunk_id','content','clause_title','policy_type','score',...})
    """
    # 1) 후보군 넉넉히 뽑기
    budget = max(top_k * 4, 20)
    raw_hits: List[Dict[str, Any]] = retrieve_context_base(db, query_vec, top_k=budget)

    want = _norm_insurer(insurer)

    # 2) 요청 보험사 + '공통' 허용 필터
    hits = [h for h in raw_hits if _insurer_ok(h, want)]

    # 3) 전부 걸러졌다면, 최소한 '공통'만이라도 반환
    if not hits:
        hits = [h for h in raw_hits if _norm_insurer(h.get("policy_type")) == "공통"]

    # 4) 최종 top_k 자르기
    return hits[:top_k]

# ─────────────────────────────────────────────────────────────
# 공개 API: retrieve_context (하위호환 프록시)
#   - 외부에서 이 경로를 이미 임포트하고 있다면 깨지 않도록 유지
# ─────────────────────────────────────────────────────────────
def retrieve_context(db: Session, query_vec: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """기존 시그니처 호환용 프록시"""
    return retrieve_context_base(db, query_vec, top_k=top_k)
