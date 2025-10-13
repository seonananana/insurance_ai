# back/app/routers/qa.py
# -----------------------------------------------------------------------------
# 기능:
#  - /qa/ask    : 프론트에서 온 질문을 유연하게(message/query/q) 받아 RAG 컨텍스트 생성 후 LLM 답변
#  - /qa/search : 프론트 검색용 간단 컨텍스트 미리보기(옵션)
#  - 의존성 최소화: DB/임베딩 팩토리 제거, rag_service + openai_service만 사용
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.rag_service import retrieve_context
from app.services.openai_service import chat_llm  # /chat/completion에서 쓰던 동일 함수 사용

router = APIRouter(tags=["qa"])


# ------------------------------
# 유연 입력 모델 (message / query / q 아무거나 허용)
# ------------------------------
class AskIn(BaseModel):
    message: Optional[str] = None
    query: Optional[str] = None
    q: Optional[str] = None
    insurer: Optional[str] = None
    top_k: Optional[int] = 3
    temperature: Optional[float] = 0.3
    max_tokens: Optional[int] = 512

    def text(self) -> str:
        return (self.message or self.query or self.q or "").strip()


class AnswerOut(BaseModel):
    answer: str
    context: Optional[str] = None
    citations: Optional[List[Dict[str, Any]]] = None
    # (PDF 기능을 붙이면 pdf_url 추가 가능)
    # pdf_url: Optional[str] = None


class SearchIn(BaseModel):
    message: Optional[str] = None
    query: Optional[str] = None
    q: Optional[str] = None
    insurer: Optional[str] = None
    top_k: Optional[int] = 5

    def text(self) -> str:
        return (self.message or self.query or self.q or "").strip()


# ------------------------------
# /qa/ask : 근거 기반 답변
# ------------------------------
@router.post("/ask", response_model=AnswerOut)
async def ask(req: AskIn) -> AnswerOut:
    question = req.text()
    if not question:
        raise HTTPException(status_code=422, detail="message / query / q 중 하나는 필수입니다.")

    insurer = (req.insurer or "DB손해").strip()
    top_k = max(1, int(req.top_k or 3))

    # 1) RAG 컨텍스트 수집
    context = retrieve_context(question, insurer=insurer, top_k=top_k)

    if not context:
        return AnswerOut(
            answer="문서에서 관련 근거를 찾지 못했습니다. 보험사 선택/Top-K/인덱스를 확인해주세요.",
            context=""
        )

    # 2) LLM에게 근거와 함께 질의
    sys = "너는 보험 약관/상품설명서 전문 어시스턴트다. 항상 한국어로 간결하고 사실 기반으로 답한다."
    user = (
        "아래 근거 문서를 토대로 질문에 답해줘.\n"
        "가능하면 목록으로 정리하고, 근거가 부족하면 '문서 근거가 충분치 않습니다'라고 말해.\n\n"
        f"[근거]\n{context}\n\n"
        f"[질문]\n{question}"
    )

    try:
        reply = chat_llm(
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": user}],
            temperature=float(req.temperature or 0.3),
            max_tokens=int(req.max_tokens or 512),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 호출 실패: {e}")

    # (간단한 citation 파싱: 파일명/페이지를 컨텍스트에서 추출)
    citations: List[Dict[str, Any]] = []
    # context가 "(파일 p.페이지)\n텍스트" 패턴으로 들어오므로 가볍게 분해
    for block in context.split("\n\n---\n\n"):
        header, *_ = block.split("\n", 1)
        # 예: "(DB실손보험2507.pdf p.19)"
        if header.startswith("(") and "p." in header:
            h = header.strip("()")
            fn, page = h.split(" p.")
            citations.append({"file": fn.strip(), "page": page.strip()})

    return AnswerOut(answer=reply, context=context, citations=citations)


# ------------------------------
# /qa/search : 미리보기용(옵션)
# ------------------------------
@router.post("/search")
async def search(req: SearchIn) -> List[Dict[str, Any]]:
    question = req.text()
    if not question:
        raise HTTPException(status_code=422, detail="message / query / q 중 하나는 필수입니다.")

    insurer = (req.insurer or "DB손해").strip()
    top_k = max(1, int(req.top_k or 5))

    context = retrieve_context(question, insurer=insurer, top_k=top_k)
    if not context:
        return []

    items: List[Dict[str, Any]] = []
    for block in context.split("\n\n---\n\n"):
        header, *rest = block.split("\n", 1)
        snippet = (rest[0] if rest else "").strip()
        if len(snippet) > 240:
            snippet = snippet[:240] + "…"

        file_name, page = None, None
        if header.startswith("(") and "p." in header:
            h = header.strip("()")
            file_name, page = h.split(" p.")
        items.append(
            {
                "file": (file_name or "").strip(),
                "page": (page or "").strip(),
                "snippet": snippet,
            }
        )
    return items