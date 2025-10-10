# back/app/services/rag_service.py
# -----------------------------------------------------------------------------
# 기능: pgvector 기반 벡터 검색(문서 조항 + 레퍼런스)과 프롬프트 빌드
#  - L2 거리(<->)로 정렬, 프론트에는 보기 쉬운 유사도 score = 1/(1+distance) 전달
#  - policy_type(보험사/분류) 필터 지원
#  - 테이블/컬럼명은 팀 표준에 맞게 바꿔도 무방 (주석 참고)
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text as sql


def build_prompt(question: str, passages: List[Dict[str, Any]]) -> str:
    """
    검색된 문서 청크(passages)를 사용자 질문과 함께 LLM에 전달할 프롬프트로 구성.
    passages: search_top_k() 결과 리스트
    """
    ctx_lines: List[str] = []
    for p in passages:
        title = p.get("clause_title") or ""
        txt = p.get("content", "") or ""
        if title:
            ctx_lines.append(f"[{title}]\n{txt}")
        else:
            ctx_lines.append(txt)

    instructions = (
        "- 보험 문서(약관/요약서/청구안내)에 근거하여 답하라.\n"
        "- 명확한 조항/서류명이 나오면 그대로 적어라.\n"
        "- 근거가 불충분하면 추측하지 말고 필요한 서류/절차를 안내하라.\n"
        "- 간결하게 항목별로 정리하라.\n"
    )

    prompt = f"""[지시]
{instructions}

[질문]
{question}

[근거 발췌]
{chr(10).join(ctx_lines)}
"""
    return prompt


# back/app/services/rag_service.py
from sqlalchemy import text as sql

def _as_pgvector_literal(vec):
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

def search_top_k(db, *, query_vec, policy_type: Optional[str], top_k: int = 5):
    qv = _as_pgvector_literal(query_vec)

    sqlq = """
    SELECT
      doc_id,
      chunk_id,
      clause_title,
      content,
      1.0 / (1.0 + (embedding <-> CAST(:qv AS vector))) AS score
    FROM document_chunks
    WHERE (CAST(:ptype AS text) IS NULL OR policy_type = CAST(:ptype AS text))
    ORDER BY embedding <-> CAST(:qv AS vector)
    LIMIT :k
    """

    rows = db.execute(
        sql(sqlq),
        {"qv": qv, "ptype": policy_type, "k": top_k}
    ).mappings().all()

    return [
        {
            "doc_id": r["doc_id"],
            "chunk_id": r["chunk_id"],
            "clause_title": r.get("clause_title"),
            "content": r["content"],
            "score": float(r["score"]) if r.get("score") is not None else None,
        }
        for r in rows
    ]
