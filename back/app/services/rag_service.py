# back/app/services/rag_service.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union
from contextlib import contextmanager
import os
import re

from sqlalchemy.orm import Session
from sqlalchemy import text

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
# ─────────────────────────────────────────────────────────────
_EMBEDDER: Optional[SBertEmbeddings] = None

def _get_embedder() -> SBertEmbeddings:
    global _EMBEDDER
    if _EMBEDDER is None:
        model_dir = os.getenv("SBERT_MODEL_DIR") or os.getenv("SBERT_MODEL_NAME", "intfloat/e5-base-v2")
        device = os.getenv("EMBED_DEVICE", "cpu")
        _EMBEDDER = SBertEmbeddings(
            model_dir,
            use_e5_prefix=None,  # e5/bge 자동 감지
            device=device,
            normalize=True,
        )
    return _EMBEDDER


# ─────────────────────────────────────────────────────────────
# 질의 전처리
# ─────────────────────────────────────────────────────────────
_BRACKET_RE = re.compile(r"^[\[\(（【]+|[\]\)）】]+$")

def _clean_query(q: str) -> str:
    q = q.strip()
    while len(q) > 2 and _BRACKET_RE.match(q[0]) and _BRACKET_RE.match(q[-1]):
        q = q[1:-1].strip()
    return re.sub(r"\s+", " ", q)

def _expand_query(q: str) -> str:
    base = _clean_query(q)
    kws = [
        "청구 서류", "구비서류", "제출 서류", "필요서류",
        "보험금 청구", "청구서", "진단서", "입퇴원확인서",
        "영수증", "신분증 사본", "보험증권", "통장사본",
        "보장 제외", "면책", "특약", "자기부담금", "약관", "지급 기준"
    ]
    return base + " " + " ".join(kws)


# ─────────────────────────────────────────────────────────────
# 보험사 정규화
# ─────────────────────────────────────────────────────────────
def _norm_insurer(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = re.sub(r"\s+", "", str(name))
    mapping = {
        "DB손해보험": "DB손해보험",
        "DB손해": "DB손해보험",
        "동부화재": "DB손해보험",
        "dbinsurance": "DB손해보험",
        "현대해상": "현대해상",
        "HI": "현대해상",
        "hyundaemarine": "현대해상",
        "삼성화재": "삼성화재",
        "SamsungFire": "삼성화재",
        "공통": "공통",
        "표준": "공통",
        "가이드": "공통",
    }
    return mapping.get(s, s)

def _insurer_ok(chunk: Dict[str, Any], want: Optional[str]) -> bool:
    if not want:
        return True
    ins_raw = (chunk.get("policy_type")
               or chunk.get("insurer")
               or chunk.get("company")
               or chunk.get("carrier"))
    ins = _norm_insurer(ins_raw) or "공통"
    return ins in {want, "공통"}


# ─────────────────────────────────────────────────────────────
# 재랭크 및 포맷
# ─────────────────────────────────────────────────────────────
def _dedup_by_file_page(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for h in hits:
        key = (
            (h.get("file_name") or h.get("doc_id") or "").strip(),
            str(h.get("page") or h.get("page_no") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out

_KEYWORDS = ["청구", "서류", "구비서류", "제출", "보험금", "신청서", "진단서", "영수증", "사본", "입원", "퇴원", "면책", "특약"]

def _keyword_score(text: str) -> int:
    t = text or ""
    return sum(1 for k in _KEYWORDS if k in t)

def _rerank_by_keywords(hits: List[Dict[str, Any]], bonus_per_match: float = 0.03) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for h in hits:
        base = float(h.get("score") or 0.0)
        bonus = bonus_per_match * _keyword_score(h.get("content") or h.get("chunk_text") or "")
        hh = dict(h)
        hh["score"] = base + bonus
        out.append(hh)
    return sorted(out, key=lambda x: x["score"], reverse=True)

def _format_blocks(hits: List[Dict[str, Any]]) -> str:
    """PDF 실제 원문과 페이지번호를 표시"""
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
# 핵심 검색 로직 (vector + insurer 필터 + page 반환)
# ─────────────────────────────────────────────────────────────
def _search_top_k(
    db: Session,
    query_vec: Sequence[float],
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    want = _norm_insurer(insurer)
    if not want:
        want = ""

    mult = int(os.getenv("RETRIEVAL_BUDGET_MULTIPLIER", "4"))
    base_min = int(os.getenv("RETRIEVAL_BUDGET_MIN", "20"))
    top_k = max(1, min(int(top_k), 50))
    budget = max(top_k * max(mult, 1), base_min)

    print(f"[DEBUG] insurer(raw)={insurer!r}, want(norm)={want!r}")

    # ✅ page, file_name, clause_title도 함께 조회
    if want:
        sql = text("""
            SELECT doc_id, chunk_id, content, source AS policy_type,
                   page, file_name, clause_title,
                   1 - (embedding <=> (:query_vec)::vector) AS score
            FROM document_chunks
            WHERE source ILIKE '%' || :insurer || '%'
            ORDER BY embedding <-> (:query_vec)::vector
            LIMIT :limit
        """)
        params = {"insurer": want.strip(), "query_vec": list(query_vec), "limit": budget}
    else:
        sql = text("""
            SELECT doc_id, chunk_id, content, source AS policy_type,
                   page, file_name, clause_title,
                   1 - (embedding <=> (:query_vec)::vector) AS score
            FROM document_chunks
            ORDER BY embedding <-> (:query_vec)::vector
            LIMIT :limit
        """)
        params = {"query_vec": list(query_vec), "limit": budget}

    rows = db.execute(sql, params).fetchall()

    raw_hits: List[Dict[str, Any]] = [
        {
            "doc_id": r.doc_id,
            "chunk_id": r.chunk_id,
            "content": r.content,
            "policy_type": r.policy_type,
            "page": r.page,
            "file_name": r.file_name,
            "clause_title": r.clause_title,
            "score": float(r.score),
        }
        for r in rows
    ]

    # 보험사 필터링 (공통 포함)
    hits = [h for h in raw_hits if _insurer_ok(h, want)]
    if not hits and want:
        hits = [h for h in raw_hits if _norm_insurer(h.get("policy_type")) == "공통"]
    if not hits:
        hits = raw_hits

    # 중복 페이지 제거 및 키워드 재랭크
    hits = _dedup_by_file_page(hits)
    hits = _rerank_by_keywords(hits)
    return hits[:top_k]


# ─────────────────────────────────────────────────────────────
# 텍스트 질의용 API
# ─────────────────────────────────────────────────────────────
def search_text(
    query: str,
    insurer: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    q = _expand_query(query)
    vec = _get_embedder().embed([q], is_query=True)[0]
    with _session_scope() as db:
        return _search_top_k(db, vec, insurer=insurer, top_k=top_k)


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────
def retrieve_context(
    arg1: Union[str, Session],
    arg2: Optional[Union[Sequence[float], str]] = None,
    *,
    top_k: int = 5,
    insurer: Optional[str] = None,
) -> str:
    """RAG용 컨텍스트 검색 (PDF 원문 기반)"""
    # A) 질문 문자열 입력
    if isinstance(arg1, str):
        question: str = arg1
        insurer_in = insurer if insurer is not None else (arg2 if isinstance(arg2, str) else None)
        q = _expand_query(question)
        vec = _get_embedder().embed([q], is_query=True)[0]
        with _session_scope() as db:
            hits = _search_top_k(db, vec, insurer=insurer_in, top_k=top_k)
        return _format_blocks(hits)

    # B) (db 세션, 쿼리 벡터) 입력
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


__all__ = ["retrieve_context", "search_text"]
