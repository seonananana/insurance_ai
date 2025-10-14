# back/app/services/rag_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence, Union
import re
from contextlib import contextmanager
import os

from sqlalchemy.orm import Session
from app.services.vector_search import retrieve_context_base
from app.services.embeddings_sbert import SBertEmbeddings

# DB 세션 스코프
@contextmanager
def _session_scope() -> Session:
    from app.db import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

# 전역 싱글톤: SBertEmbeddings 인스턴스
_EMBEDDER: Optional[SBertEmbeddings] = None
def _get_embedder() -> SBertEmbeddings:
    global _EMBEDDER
    if _EMBEDDER is None:
        model_dir = os.getenv("SBERT_MODEL_DIR") or os.getenv("SBERT_MODEL_NAME", "intfloat/e5-base-v2")
        device = os.getenv("EMBED_DEVICE", "cpu")
        # use_e5_prefix=None → 자동감지(e5/bge면 prefix 사용)
        _EMBEDDER = SBertEmbeddings(model_dir, use_e5_prefix=None, device=device, normalize=True)
    return _EMBEDDER

# ─────────────────────────────────────────────────────────────
# 보험사명 정규화
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

# 보험사 필터: 요청 보험사 + '공통'
def _insurer_ok(chunk: Dict[str, Any], want: Optional[str]) -> bool:
    if not want:
        return True
    ins_raw = chunk.get("policy_type") or chunk.get("insurer") or chunk.get("company") or chunk.get("carrier")
    ins = _norm_insurer(ins_raw)
    return ins in {want, "공통"}

# 히트 → 문자열 블럭 포맷
def _format_blocks(hits: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for h in hits:
        # 파일/페이지 메타 추출(없으면 안전한 기본값)
        file_name = (h.get("file_name") or h.get("doc_id") or "document").strip()
        page = str(h.get("page") or h.get("page_no") or "?").strip()
        content = (h.get("content") or h.get("chunk_text") or "").strip()
        # 라우터가 기대하는 포맷: "(파일 p.페이지)\n텍스트"
        block = f"({file_name} p.{page})\n{content}"
        blocks.append(block)
    # 라우터에서 split 하는 구분자
    return "\n\n---\n\n".join(blocks)

# 상위 후보 뽑기 + 보험사 필터 (내부용)
def _search_top_k(
    db: Session,
    query_vec: Sequence[float],
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    budget = max(top_k * 4, 20)
    raw_hits: List[Dict[str, Any]] = retrieve_context_base(db, list(query_vec), top_k=budget)
    want = _norm_insurer(insurer)
    hits = [h for h in raw_hits if _insurer_ok(h, want)]
    if not hits:
        hits = [h for h in raw_hits if _norm_insurer(h.get("policy_type")) == "공통"]
    return hits[:top_k]

# 🔧 과거 호환용 공개 함수: 리스트[dict] 반환 (외부 모듈이 import 하던 심볼 복원)
def search_top_k(
    db: Session,
    query_vec: Sequence[float],
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Backward-compatible public API: return raw hits (list of dicts)."""
    return _search_top_k(db, query_vec, insurer=insurer, top_k=top_k)

# ─────────────────────────────────────────────────────────────
# 공개 API: retrieve_context (폴리모픽) → 문자열 컨텍스트 반환
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
    # A) 라우터에서 문자열 질문으로 호출된 경우
    if isinstance(arg1, str):
        question: str = arg1
        insurer_in = insurer if insurer is not None else (arg2 if isinstance(arg2, str) else None)
        query_vec = _get_embedder().embed([question], is_query=True)[0]
        with _session_scope() as db:
            hits = _search_top_k(db, query_vec, insurer=insurer_in, top_k=top_k)
        return _format_blocks(hits)

    # B) 저수준 (db + query_vec)
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

# 공개 심볼
__all__ = ["retrieve_context", "search_top_k"]
