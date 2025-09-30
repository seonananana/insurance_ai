"""
파일 기능 요약
- pgvector 기반 벡터 검색(문서 조항 + 레퍼런스)을 수행하고, 상위 결과를 정규화.
- DB 스키마 컬럼/테이블 이름은 팀 표준에 맞춰 변경 가능하며, 해당 줄에 주석으로 표기.

주의:
- 아래 SQL은 pgvector의 cosine distance를 사용합니다.
- document_chunks / reference_items를 UNION으로 묶어 통합 검색 예시를 제공합니다.
"""

from typing import List, Dict, Any
from psycopg_pool import AsyncConnectionPool

# —— DB 컬럼/테이블 매핑(임의): 친구 스키마와 다르면 아래 이름을 변경하세요 ——
# document_chunks: id, doc_id, chunk_id, section_path, clause_title, clean_text, embedding, token_count, lang, created_at
# reference_items: id, ref_type, policy_type, title, content, embedding, created_at
# policy_documents: id, policy_type, title, source, source_path, version, issued_at, raw_text, created_at

async def search_top_k(pool: AsyncConnectionPool, *, query_vec: list[float], policy_type: str | None, top_k: int) -> List[Dict[str, Any]]:
    """
    query_vec: OpenAI 임베딩 벡터
    policy_type: 'auto'|'medical'|'home' 등 필터. None이면 전체
    반환: 통합 검색 결과 리스트 (문서/조항/스코어 등)
    """
    # pgvector 파라미터는 리스트→PG vector literal로 변환 필요
    vec = f"[{', '.join(map(str, query_vec))}]"

    # policy_type 필터를 document_chunks(doc→policy_documents join)와 reference_items 모두에 적용
    policy_filter_doc = "TRUE" if policy_type is None else "pd.policy_type = %(policy_type)s"
    policy_filter_ref = "TRUE" if policy_type is None else "ri.policy_type = %(policy_type)s"

    sql = f"""
    WITH chunk_search AS (
        SELECT
            dc.id          AS chunk_row_id,
            dc.doc_id      AS doc_id,
            dc.chunk_id    AS chunk_id,
            dc.section_path,
            dc.clause_title,
            pd.version     AS version,     -- —— DB 연결(임의): policy_documents.version
            1 - (dc.embedding <=> %(qvec)s::vector) AS score,  -- cosine similarity
            dc.clean_text  AS content
        FROM document_chunks dc
        JOIN policy_documents pd ON pd.id = dc.doc_id  -- —— DB 연결(임의)
        WHERE {policy_filter_doc}
        ORDER BY dc.embedding <=> %(qvec)s::vector
        LIMIT %(limit)s
    ),
    ref_search AS (
        SELECT
            ri.id          AS chunk_row_id,
            NULL::bigint   AS doc_id,
            ('ref-' || ri.id)::text AS chunk_id,
            NULL::text     AS section_path,
            ri.title       AS clause_title,
            NULL::text     AS version,
            1 - (ri.embedding <=> %(qvec)s::vector) AS score,
            ri.content     AS content
        FROM reference_items ri
        WHERE {policy_filter_ref}
        ORDER BY ri.embedding <=> %(qvec)s::vector
        LIMIT %(limit)s
    )
    SELECT * FROM (
        SELECT * FROM chunk_search
        UNION ALL
        SELECT * FROM ref_search
    ) u
    ORDER BY score DESC
    LIMIT %(limit)s;
    """

    params = {"qvec": vec, "limit": top_k}
    if policy_type is not None:
        params["policy_type"] = policy_type

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            cols = [c.name for c in cur.description]
            rows = await cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def build_prompt(question: str, passages: List[Dict[str, Any]]) -> str:
    """
    검색된 근거(passages)를 기반으로 LLM에 줄 프롬프트 생성.
    """
    ctx_lines = []
    for i, p in enumerate(passages, 1):
        meta = []
        if p.get("doc_id") is not None:
            meta.append(f"doc_id={p['doc_id']}")
        if p.get("chunk_id"):
            meta.append(f"chunk_id={p['chunk_id']}")
        if p.get("section_path"):
            meta.append(f"path={p['section_path']}")
        if p.get("version"):
            meta.append(f"ver={p['version']}")
        header = f"[{i}] ({', '.join(meta)}) score={p.get('score', 0):.3f}"
        ctx_lines.append(header + "\n" + (p.get("content") or "")[:2000])  # 안전 길이 제한

    instructions = (
        "아래 '근거'만을 사용해 사용자 질문에 답하세요.\n"
        "- 근거에 없는 내용은 추론하지 말고 '제공된 근거 범위에서 확인되지 않습니다'라고 답하세요.\n"
        "- 자동차/실손/화재 등 보험별 용어를 정확히 쓰세요.\n"
        "- 필요서류는 발급기관까지 명시하세요.\n"
        "- 마지막에 '근거 출처'로 [번호]를 나열하세요.\n"
    )

    prompt = f"""[지시]
{instructions}

[질문]
{question}

[근거]
{chr(10).join(ctx_lines)}
"""
    return prompt
