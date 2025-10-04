# pgvector 기반 벡터 검색(문서 조항 + 레퍼런스)을 수행하고, 상위 결과를 정규화.
# DB 스키마 컬럼/테이블 이름은 팀 표준에 맞춰 변경 가능하며, 해당 줄에 주석으로 표기.

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

def build_prompt(question: str, passages: List[Dict[str, Any]]) -> str:
    """
    검색된 문서 청크(passages)를 사용자 질문과 함께 LLM에 전달할 프롬프트로 구성.
    - passages: search_top_k() 결과 리스트
    """
    ctx_lines = []
    for p in passages:
        title = p.get("clause_title") or ""
        txt = p.get("content", "")
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

def _as_pgvector_literal(vec: List[float]) -> str:
    """
    psycopg2로 vector 파라미터 바인딩이 번거로운 점을 우회하기 위해
    '[1.0,2.0,...]' literal 형태로 캐스팅하여 SQL에 삽입.
    """
    return "[" + ",".join(str(float(x)) for x in vec) + "]"

def search_top_k(
    db: Session,
    *,
    query_vec: List[float],
    policy_type: Optional[str],
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    pgvector 유사도 검색:
      - embedding <-> query_vec 연산으로 유사도가 높은 문서 청크 Top-K 반환.
      - 반환 형식을 프론트/LLM 프롬프트에 바로 쓰기 좋게 정규화.
    테이블/컬럼:
      - document_chunks(팀 표준명으로 교체 가능)            # 테이블명
      - policy_type TEXT                                     # 제품/카테고리 구분 컬럼
      - clause_title TEXT                                    # 조항/섹션 제목
      - content TEXT                                         # 청크 텍스트
      - embedding vector(3072)                               # 임베딩 벡터
    """
    qvec_lit = _as_pgvector_literal(query_vec)

    sql = """
    SELECT
      doc_id,          -- 팀 표준: 문서 식별자 컬럼명 교체 가능
      chunk_id,        -- 팀 표준: 청크 식별자 컬럼명 교체 가능
      clause_title,    -- 팀 표준: 조항/섹션 제목 컬럼명 교체 가능
      content,         -- 팀 표준: 청크 본문 컬럼명 교체 가능
      (embedding <-> {qvec}) AS score
    FROM document_chunks     -- 팀 표준: 테이블명 교체 가능
    WHERE (:ptype IS NULL OR policy_type = :ptype)
    ORDER BY embedding <-> {qvec}
    LIMIT :k
    """.format(qvec=f"{qvec_lit}::vector")

    rows = db.execute(
        text(sql),
        {"ptype": policy_type, "k": top_k}
    ).fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        results.append({
            "doc_id": r.doc_id,
            "chunk_id": r.chunk_id,
            "clause_title": r.clause_title,
            "content": r.content,
            "score": float(r.score) if hasattr(r, "score") and r.score is not None else None,
        })
    return results
