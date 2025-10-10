# pgvector 기반 벡터 검색(문서 조항 + 레퍼런스)을 수행하고, 상위 결과를 정규화.
# DB 스키마 컬럼/테이블 이름은 팀 표준에 맞춰 변경 가능하며, 해당 줄에 주석으로 표기.

from typing import List, Dict, Any
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

    return f"""[지시]
{instructions}

[질문]
{question}

[근거 발췌]
{chr(10).join(ctx_lines)}
"""

def _as_pgvector_literal(vec: List[float]) -> str:
    """
    pgvector는 파라미터를 문자열 리터럴('[v1,v2,...]')로 받아야 함.
    """
    # 소수점은 과하지 않게; 필요하면 자리수 조정
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

def search_top_k(
    db: Session,
    *,
    query_vec: List[float],
    policy_type: Optional[str] = None,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    pgvector 유사도 검색:
      - embedding <-> query_vec 연산으로 유사도가 높은 문서 청크 Top-K 반환.
    현재 테이블/컬럼:
      - document_chunks                        # 테이블명
      - doc_id TEXT                            # 문서 식별자
      - chunk_id TEXT                          # 청크 식별자
      - clause_title TEXT                      # 조항/섹션 제목
      - content TEXT                           # 청크 텍스트
      - embedding vector(1536)                 # 임베딩 벡터 (text-embedding-3-small)
    """
    qv = _as_pgvector_literal(query_vec)  # '[...]' 형태

    sql = """
    SELECT
      doc_id,
      chunk_id,
      clause_title,
      content,
      (embedding <-> :qv::vector) AS score
    FROM document_chunks
    ORDER BY embedding <-> :qv::vector
    LIMIT :k
    """

    rows = db.execute(text(sql), {"qv": qv, "k": int(top_k)}).mappings().all()

    results: List[Dict[str, Any]] = []
    for r in rows:
        results.append({
            "doc_id": r.get("doc_id"),
            "chunk_id": r.get("chunk_id"),
            "clause_title": r.get("clause_title"),
            "content": r.get("content"),
            "score": float(r.get("score")) if r.get("score") is not None else None,
        })
    return results
