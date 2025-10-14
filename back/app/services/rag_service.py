# back/app/services/rag_service.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union
from contextlib import contextmanager
import os
import re

from sqlalchemy.orm import Session

from app.services.vector_search import retrieve_context_base
from app.services.embeddings_sbert import SBertEmbeddings


# ─────────────────────────────────────────────────────────────
# DB 세션 스코프
# ─────────────────────────────────────────────────────────────
@contextmanager
def _session_scope() -> Session:
    from app.db import SessionLocal  # 지연 import (순환 참조 방지)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# 전역 임베더 (싱글톤)
#   - use_e5_prefix=None  → 모델명이 e5/bge면 자동으로 query:/passage: 접두사 적용
#   - normalize=True      → 코사인 거리 일관성 확보
# ─────────────────────────────────────────────────────────────
_EMBEDDER: Optional[SBertEmbeddings] = None

def _get_embedder() -> SBertEmbeddings:
    global _EMBEDDER
    if _EMBEDDER is None:
        model_dir = os.getenv("SBERT_MODEL_DIR") or os.getenv("SBERT_MODEL_NAME", "intfloat/e5-base-v2")
        device = os.getenv("EMBED_DEVICE", "cpu")
        _EMBEDDER = SBertEmbeddings(
            model_dir,
            use_e5_prefix=None,   # e5/bge 자동 감지
            device=device,
            normalize=True,
        )
    return _EMBEDDER


# ─────────────────────────────────────────────────────────────
# 입력 정규화 & 질의 확장(동의어 부스트)
# ─────────────────────────────────────────────────────────────
_BRACKET_RE = re.compile(r"^[\[\(（【]+|[\]\)）】]+$")

def _clean_query(q: str) -> str:
    # 양 끝 대괄호/괄호 등 제거 + 공백 정리
    q = q.strip()
    # 바깥쪽 감싼 괄호만 제거
    while len(q) > 2 and _BRACKET_RE.match(q[0]) and _BRACKET_RE.match(q[-1]):
        q = q[1:-1].strip()
    return re.sub(r"\s+", " ", q)

def _expand_query(q: str) -> str:
    """
    Dense 검색이 약한 규정형 용어(청구/서류 등)를 보완하기 위해
    흔한 한국어 동의어/관련어를 붙여 신호를 강화.
    """
    base = _clean_query(q)
    kws = [
        "청구 서류", "구비서류", "제출 서류", "필요서류",
        "보험금 청구", "청구서", "진단서", "입퇴원확인서",
        "영수증", "신분증 사본", "보험증권", "통장사본"
    ]
    return base + " " + " ".join(kws)


# ─────────────────────────────────────────────────────────────
# 보험사 정규화/필터
# ─────────────────────────────────────────────────────────────
def _norm_insurer(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = re.sub(r"\s+", "", str(name)).lower()
    mapping = {
        "db손해": "db손해", "db손해보험": "db손해", "dbinsurance": "db손해",
        "현대해상": "현대해상", "현대해상화재": "현대해상", "hyundaemarine": "현대해상",
        "삼성화재": "삼성화재", "삼성화재해상": "삼성화재", "samsungfire": "삼성화재",
        "공통": "공통", "표준약관": "공통", "표준": "공통", "가이드": "공통",
    }
    return mapping.get(s, s)

def _insurer_ok(chunk: Dict[str, Any], want: Optional[str]) -> bool:
    """청크의 policy_type이 요청 보험사 또는 '공통'이면 통과."""
    if not want:
        return True
    ins_raw = chunk.get("policy_type") or chunk.get("insurer") or chunk.get("company") or chunk.get("carrier")
    ins = _norm_insurer(ins_raw)
    return ins in {want, "공통"}


# ─────────────────────────────────────────────────────────────
# 결과 정리/재랭크/포맷
# ─────────────────────────────────────────────────────────────
def _dedup_by_file_page(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 (파일, 페이지) 중복 제거."""
    seen, out = set(), []
    for h in hits:
        key = ((h.get("file_name") or h.get("doc_id") or "").strip(),
               str(h.get("page") or h.get("page_no") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out

# 키워드 보너스(간단 하이브리드 재랭킹)
_KEYWORDS = ["청구", "서류", "구비서류", "제출", "보험금", "신청서", "진단서", "영수증", "사본", "입원", "퇴원"]

def _keyword_score(text: str) -> int:
    t = text or ""
    return sum(1 for k in _KEYWORDS if k in t)

def _rerank_by_keywords(hits: List[Dict[str, Any]], bonus_per_match: float = 0.03) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for h in hits:
        base = float(h.get("score") or 0.0)
        bonus = bonus_per_match * _keyword_score(h.get("content") or "")
        hh = dict(h); hh["score"] = base + bonus
        out.append(hh)
    return sorted(out, key=lambda x: x["score"], reverse=True)

def _format_blocks(hits: List[Dict[str, Any]]) -> str:
    """
    라우터/프론트 호환 포맷:
      (파일명 p.페이지) · [조항]
      본문
      \n\n---\n\n 로 블록 구분
    """
    blocks: List[str] = []
    for h in hits:
        file_name = (h.get("file_name") or h.get("doc_id") or "document").strip()
        page = str(h.get("page") or h.get("page_no") or "?").strip()
        content = (h.get("content") or h.get("chunk_text") or "").strip()
        clause = (h.get("clause_title") or "").strip()
        head = f"({file_name} p.{page})"
        if clause:
            head += f" · {clause}"
        blocks.append(f"{head}\n{content}")
    return "\n\n---\n\n".join(blocks)


# ─────────────────────────────────────────────────────────────
# 저수준 검색 (이미 벡터를 가진 상태)
# ─────────────────────────────────────────────────────────────
def _search_top_k(
    db: Session,
    query_vec: Sequence[float],
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    - 먼저 넉넉히 검색(budget) 후 보험사 필터/중복 제거
    - 보험사 결과가 비면 '공통' 또는 무필터 폴백
    - 키워드 보너스로 재랭킹
    """
    want = _norm_insurer(insurer)
    budget = max(top_k * 4, 20)

    raw_hits: List[Dict[str, Any]] = retrieve_context_base(db, list(query_vec), top_k=budget)

    # 1차: 요청 보험사/공통
    hits = [h for h in raw_hits if _insurer_ok(h, want)]
    # 2차: 보험사 지정인데 결과가 완전 비면 '공통'만이라도
    if not hits and want:
        hits = [h for h in raw_hits if _norm_insurer(h.get("policy_type")) == "공통"]
    # 3차: 그래도 비면 무필터 그대로 사용(최소한의 근거라도)
    if not hits:
        hits = raw_hits

    hits = _dedup_by_file_page(hits)
    hits = _rerank_by_keywords(hits)   # ✅ 키워드 보너스 재랭크
    return hits[:top_k]

# 과거 호환 API (이미 벡터를 전달받는 버전)
def search_top_k(
    db: Session,
    query_vec: Sequence[float],
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    return _search_top_k(db, query_vec, insurer=insurer, top_k=top_k)


# ─────────────────────────────────────────────────────────────
# 텍스트 쿼리용 헬퍼 (프론트/라우터 편의)
# ─────────────────────────────────────────────────────────────
def search_text(
    query: str,
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    텍스트 질문 → (e5 접두사 포함) 쿼리 임베딩 → 상위 hits(dict) 리스트 반환
    """
    q = _expand_query(query)                 # ✅ 질의 확장
    vec = _get_embedder().embed([q], is_query=True)[0]  # e5면 자동 "query: " 접두사
    with _session_scope() as db:
        return _search_top_k(db, vec, insurer=insurer, top_k=top_k)


# ─────────────────────────────────────────────────────────────
# 공개 API: retrieve_context (폴리모픽) → 문자열 컨텍스트
#   A) retrieve_context(question: str, insurer=..., top_k=...)
#   B) retrieve_context(db: Session, query_vec: Sequence[float], insurer=..., top_k=...)
# ─────────────────────────────────────────────────────────────
def retrieve_context(
    arg1: Union[str, Session],
    arg2: Optional[Union[Sequence[float], str]] = None,
    *,
    top_k: int = 5,
    insurer: Optional[str] = None,
) -> str:
    # A) 질문 문자열로 호출
    if isinstance(arg1, str):
        question: str = arg1
        insurer_in = insurer if insurer is not None else (arg2 if isinstance(arg2, str) else None)
        q = _expand_query(question)                          # ✅ 질의 확장
        vec = _get_embedder().embed([q], is_query=True)[0]
        with _session_scope() as db:
            hits = _search_top_k(db, vec, insurer=insurer_in, top_k=top_k)
        return _format_blocks(hits)

    # B) (db 세션, 쿼리 벡터)로 호출
    if isinstance(arg1, Session) and isinstance(arg2, (list, tuple)):
        db: Session = arg1
        query_vec: Sequence[float] = arg2
        hits = _search_top_k(db, query_vec, insurer=insurer, top_k=top_k)
        return _format_blocks(hits)

    raise TypeError(
        "retrieve_context 사용법: "
        "A) retrieve_context(question: str, insurer: Optional[str]=None, top_k:int=5) 또는 "
        "B) retrieve_context(db: Session, query_vec: Sequence[float], *, insurer: Optional[str]=None, top_k:int=5)"
    )


# 외부 공개 심볼
__all__ = [
    "retrieve_context",   # 문자열 컨텍스트
    "search_top_k",       # (db, vec) 히트 목록
    "search_text",        # 텍스트 쿼리 히트 목록 (프론트/라우터 편의)
]
