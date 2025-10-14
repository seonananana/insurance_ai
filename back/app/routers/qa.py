# app/routers/qa.py  ✅ 전체 교체본
from io import BytesIO
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

router = APIRouter(prefix="/qa", tags=["qa"])

# ----------------- 유틸 -----------------
def _register_korean_font():
    candidates = [
        os.getenv("PDF_FONT_PATH"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont("KR", p))
                return "KR"
            except Exception:
                continue
    pdfmetrics.registerFont(TTFont("Fallback", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    return "Fallback"

def _wrap_text(text: str, max_chars=80):
    lines = []
    for para in text.splitlines():
        buf = ""
        for ch in para:
            buf += ch
            if len(buf) >= max_chars:
                lines.append(buf); buf = ""
        if buf:
            lines.append(buf)
    return lines or [""]

# ----------------- 스키마 -----------------
class AskReq(BaseModel):
    query: str
    policy_type: str | None = None
    top_k: int = 3
    max_tokens: int = 256

class SearchReq(BaseModel):
    query: str
    policy_type: str | None = None
    top_k: int = 5

# ----------------- RAG 엔드포인트 -----------------
@router.post("/ask")
def ask(req: AskReq):
    """검색 → (가능하면) LLM 생성까지 수행"""
    try:
        from app.services.rag_service import retrieve_context
        ctx_text: str = retrieve_context(req.query, insurer=req.policy_type, top_k=req.top_k)
    except Exception as e:
        return JSONResponse({"answer":"", "sources": [], "error": f"retrieval_failed: {e}"}, status_code=200)

    # OpenAIService가 있으면 생성, 실패하면 근거 요약으로 폴백
    try:
        from app.services.openai_service import OpenAIService  # 레포에 없으면 except로 이동
        svc = OpenAIService()
        prompt = (
            "다음 질문에 대해 제공된 근거만 사용하여 한국어로 간결하고 정확하게 답변하세요.\n\n"
            f"[질문]\n{req.query}\n\n"
            f"[근거]\n{ctx_text}\n\n"
            "규정/면책은 원문 표현을 유지하고, 가능하면 항목화하세요."
        )
        answer, *_ = svc.chat(prompt, max_tokens=req.max_tokens)
        return {"answer": answer, "context": ctx_text}
    except Exception:
        first_block = (ctx_text.split("\n\n---\n\n") or [""])[0]
        return {
            "answer": f"(LLM 생성 비활성화) 아래 근거 발췌로 대신합니다:\n{first_block[:1000]}",
            "context": ctx_text,
        }

@router.post("/search")
def search(req: SearchReq):
    """검색만 수행: retrieve_context를 블럭 단위로 파싱해 리스트로 반환"""
    try:
        from app.services.rag_service import retrieve_context
        ctx_text: str = retrieve_context(req.query, insurer=req.policy_type, top_k=req.top_k)
        blocks = ctx_text.split("\n\n---\n\n") if ctx_text else []
        results = [{"rank": i + 1, "text": b} for i, b in enumerate(blocks) if b.strip()]
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"search_failed: {e}")

# ----------------- PDF 엔드포인트 -----------------
@router.post("/answer_pdf")
async def answer_pdf(payload: dict):
    question = (payload.get("question") or "").strip()
    insurer = payload.get("policy_type")
    top_k = int(payload.get("top_k") or 5)
    max_tok = int(payload.get("max_tokens") or 512)

    try:
        from app.services.rag_service import retrieve_context
        ctx_blocks_str: str = retrieve_context(question, insurer=insurer, top_k=top_k)
    except Exception as e:
        return JSONResponse(
            {"answer": "(검색 실패)", "sources": [], "error": f"retrieval_failed: {e}"},
            status_code=200,
        )

    try:
        font_name = _register_korean_font()
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setTitle("RAG Answer")
        c.setAuthor("Insurance RAG")

        width, height = A4
        x_margin, y_margin = 20 * mm, 20 * mm
        y = height - y_margin

        c.setFont(font_name, 14)
        c.drawString(x_margin, y, f"[질문] {question[:120]}"); y -= 10 * mm

        c.setFont(font_name, 12)
        c.drawString(x_margin, y, f"[보험사] {insurer or '미지정'}   [Top-K] {top_k}"); y -= 8 * mm

        c.setFont(font_name, 11)
        c.drawString(x_margin, y, "[근거]"); y -= 7 * mm

        for block in ctx_blocks_str.split("\n\n---\n\n"):
            for line in _wrap_text(block, max_chars=90):
                if y < 25 * mm:
                    c.showPage(); c.setFont(font_name, 11); y = height - y_margin
                c.drawString(x_margin, y, line); y -= 6 * mm
            y -= 4 * mm

        c.showPage(); c.save()
        pdf_bytes = buf.getvalue(); buf.close()

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="rag_answer.pdf"'},
        )
    except Exception as e:
        return JSONResponse(
            {"answer": "PDF 생성에 실패했습니다.", "sources": [], "error": f"pdf_failed: {e}"},
            status_code=200,
        )
