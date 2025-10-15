# back/app/routers/qa.py
from __future__ import annotations

from io import BytesIO
from datetime import datetime
from typing import List, Optional, Dict, Any, Iterable
import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# PDF (Platypus 기반으로 1페이지 템플릿 생성)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing

router = APIRouter(prefix="/qa", tags=["qa"])

# ----------------------------------------------------------------------
# Brand Profiles (보험사별 색/QR/면책)
# ----------------------------------------------------------------------
INSURER_PROFILE: Dict[str, Dict[str, Any]] = {
    "현대해상": {
        "brand_color": "#003366",
        "qr_url": "https://www.hi.co.kr/service/customer",
        "footer_note": "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 현대해상 약관 및 심사 결과에 따릅니다.",
    },
    "DB손해보험": {
        "brand_color": "#0C7E4B",
        "qr_url": "https://www.idbins.com/service/main",
        "footer_note": "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 DB손해보험 약관 및 심사 결과에 따릅니다.",
    },
    "삼성화재": {
        "brand_color": "#0055A5",
        "qr_url": "https://www.samsungfire.com/",
        "footer_note": "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 삼성화재 약관 및 심사 결과에 따릅니다.",
    },
    # 기타 보험사 기본 프로필(색/QR/문구는 현대 스타일로 대체)
}

ALIAS = [
    (r"현대\s*해상|현대해상|HI", "현대해상"),
    (r"DB\s*손해보험|DB\s*손해|동부화재|DB\s*Insurance", "DB손해보험"),
    (r"삼성\s*화재|삼성화재|Samsung\s*Fire", "삼성화재"),
]

def normalize_insurer_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    for pat, canon in ALIAS:
        if re.search(pat, name, flags=re.I):
            return canon
    return name.strip()

def detect_insurer(question: str = "", metas: Optional[Iterable[str]] = None) -> Optional[str]:
    text = question or ""
    if metas:
        text += " " + " ".join([m or "" for m in metas])
    for pat, canon in ALIAS:
        if re.search(pat, text, flags=re.I):
            return canon
    return None

def get_insurer_profile(insurer: Optional[str]) -> Dict[str, Any]:
    canon = normalize_insurer_name(insurer) if insurer else None
    if not canon:
        canon = "현대해상"
    prof = INSURER_PROFILE.get(canon)
    if not prof:
        # 기본값: 현대해상 스타일
        prof = INSURER_PROFILE["현대해상"].copy()
        prof["footer_note"] = "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사 약관 및 심사 결과에 따릅니다."
    prof = prof.copy()
    prof["name"] = canon
    return prof

# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def _register_korean_font() -> str:
    candidates = [
        os.getenv("PDF_FONT_PATH"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.otf",
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
    fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(fb):
        pdfmetrics.registerFont(TTFont("Fallback", fb))
        return "Fallback"
    return "Helvetica"

def _split_blocks(ctx_text: str) -> List[str]:
    """
    컨텍스트를 여러 블록으로 분리.
    기본 구분자 실패 시, 두 줄 이상의 공백 뒤에 번호/괄호/헤더 패턴으로도 분리한다.
    """
    if not ctx_text:
        return []

    # 1) 권장 구분자
    parts = [b for b in ctx_text.split("\n\n---\n\n") if b.strip()]
    if len(parts) > 1:
        return parts

    # 2) 대안 분리: 두 줄 이상 공백 뒤에 "1. ", "(...)", "### "로 시작하는 블록
    tokens = re.split(r"\n{2,}(?=(\d+\.\s|\(|###\s))", ctx_text)
    rebuilt: List[str] = []
    buf = ""
    for tk in tokens:
        if re.match(r"^(\d+\.\s|\(|###\s)", tk or ""):
            if buf.strip():
                rebuilt.append(buf)
            buf = tk
        else:
            buf += tk
    if buf.strip():
        rebuilt.append(buf)

    # 3) 최종 클린업: 공백 제거 후 반환
    out = [b.strip() for b in rebuilt if b and b.strip()]
    return out or [ctx_text.strip()]

def _blocks_to_references(ctx_text: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    blocks = _split_blocks(ctx_text)
    for i, b in enumerate(blocks, 1):
        lines = b.splitlines()
        title = (lines[0] if lines else f"근거 {i}")[:200]
        page = None
        score = None
        m = re.search(r"[pP]\.?\s*(\d{1,4})", title)
        if m:
            try:
                page = int(m.group(1))
            except Exception:
                page = None
        ms = re.search(r"(score|점수)\s*[:=]\s*([0-9.]+)", title)
        if ms:
            try:
                score = float(ms.group(2))
            except Exception:
                score = None
        snippet = b if len(b) <= 2000 else (b[:2000] + "…")
        refs.append({"title": title, "page": page, "score": score, "snippet": snippet})
    return refs

def _llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))

# QR Flowable (QrCodeWidget → Drawing 래핑)
class QRFlowable(Flowable):
    def __init__(self, url: str, mm_size: float = 25):
        super().__init__()
        widget = qr.QrCodeWidget(url)
        x1, y1, x2, y2 = widget.getBounds()
        w, h = float(x2 - x1), float(y2 - y1)
        size = mm_size * mm
        sx, sy = size / w, size / h
        self.drawing = Drawing(size, size, transform=[sx, 0, 0, sy, 0, 0])
        self.drawing.add(widget)
        self.width = size
        self.height = size
    def draw(self):
        renderPDF.draw(self.drawing, self.canv, 0, 0)

# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
class AskReq(BaseModel):
    query: str
    policy_type: Optional[str] = None  # 보험사 힌트(현대해상/DB손해보험/삼성화재 등)
    top_k: int = 5
    max_tokens: int = 512
    temperature: float = 0.3

class SearchReq(BaseModel):
    query: str
    policy_type: Optional[str] = None
    top_k: int = 10

# ----------------------------------------------------------------------
# Core RAG helpers
# ----------------------------------------------------------------------
def _retrieve_context(query: str, insurer: Optional[str], top_k: int) -> str:
    from app.services.rag_service import retrieve_context  # lazy import
    return retrieve_context(query, insurer=insurer, top_k=top_k)

def _make_prompt(query: str, ctx: str, insurer: Optional[str]) -> str:
    return (
        "당신은 보험 약관/청구 안내 전문 어시스턴트입니다. 아래 컨텍스트만을 근거로 한국어로 간결하고 정확하게 답변하세요.\n"
        "모호하면 '추가 서류 확인 필요' 등으로 한계를 명시하고, 허위 추론은 금지합니다.\n\n"
        f"[보험사] {insurer or '미지정'}\n"
        f"[질문]\n{query}\n\n"
        f"[컨텍스트]\n{ctx}\n\n"
        "답변:"
    )

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------
@router.post("/ask")
def ask(req: AskReq):
    # retrieval
    try:
        ctx_text = _retrieve_context(req.query, req.policy_type, req.top_k)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"retrieval_failed: {e}"}, status_code=200)

    references = _blocks_to_references(ctx_text)

    if _llm_available():
        try:
            # 프로젝트 래퍼 우선
            try:
                from app.services.openai_service import OpenAIService  # type: ignore
            except Exception:
                OpenAIService = None
            if OpenAIService is not None:
                client = OpenAIService()
                prompt = _make_prompt(req.query, ctx_text, req.policy_type)
                result = client.chat(prompt=prompt, max_tokens=req.max_tokens)
                answer = (result[0] if isinstance(result, (list, tuple)) and result else str(result))
            else:
                import openai  # type: ignore
                openai.api_key = os.environ["OPENAI_API_KEY"]
                messages = [{"role": "user", "content": _make_prompt(req.query, ctx_text, req.policy_type)}]
                resp = openai.ChatCompletion.create(
                    model=os.getenv("CHAT_MODEL", "gpt-4o-mini"),
                    messages=messages,
                    max_tokens=req.max_tokens,
                    temperature=req.temperature,
                )
                answer = resp["choices"][0]["message"]["content"]
        except Exception as e:
            first = (_split_blocks(ctx_text) + [""])[0]
            answer = f"(LLM 호출 실패로 요약 제공) {first[:1000]}  // error: {e}"
    else:
        first = (_split_blocks(ctx_text) + [""])[0]
        answer = f"(LLM 비활성화) 근거 요약:\n{first[:1000]}"

    return {
        "ok": True,
        "answer": answer,
        "context": ctx_text,
        "references": references,
        "requested_top_k": req.top_k,
        "returned_refs": len(references),
    }

@router.post("/search")
def search(req: SearchReq):
    """
    검색만 수행. 실패해도 500 대신 항상 200 JSON으로 에러 반환.
    """
    try:
        ctx_text = _retrieve_context(req.query, req.policy_type, req.top_k)
        blocks = _split_blocks(ctx_text)
        results = [{"rank": i + 1, "text": b} for i, b in enumerate(blocks)]
        return {"ok": True, "results": results, "count": len(results)}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"search_failed: {type(e).__name__}: {e}"}, status_code=200)

# ----------------------------------------------------------------------
# PDF Builder (1페이지 템플릿)
# ----------------------------------------------------------------------
def _build_onepage_pdf_bytes(
    title: str,
    insurer_name: str,
    question: str,
    brand_color: str,
    qr_url: str,
    footer_note: str,
    font_name: str,
) -> bytes:
    """
    A4 1페이지 안에 상/본/하단 블록을 배치하여 PDF 바이트를 반환.
    표/타임라인/체크리스트는 고정 길이로 구성해 1페이지 초과를 방지.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=15*mm
    )
    # 1페이지 고정: splitting 방지
    doc.allowSplitting = 0

    title_style = ParagraphStyle(name='Title', fontName=font_name, fontSize=20, leading=24, alignment=1, spaceAfter=6)
    subtitle_style = ParagraphStyle(name='Subtitle', fontName=font_name, fontSize=13, leading=18,
                                    textColor=colors.HexColor(brand_color), spaceAfter=6)
    body_style = ParagraphStyle(name='Body', fontName=font_name, fontSize=11, leading=16)

    elements: List[Any] = []

    # 상단
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 2))
    elements.append(Paragraph("사건 요약 / 청구 가능성", subtitle_style))
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_text = f"""
    보험사: {insurer_name}<br/>
    문의: {question[:120]}<br/>
    생성일: {created_at}<br/>
    최종 판단은 보험사 심사 결과에 따라 달라질 수 있습니다.
    """
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 6))

    # 본론 - 메트릭스 표 (고정 4행)
    elements.append(Paragraph("보험적용항목 (메트릭스)", subtitle_style))
    matrix_rows = [
        ["구분", "항목", "비고"],
        ["진단비", "암 진단비", "보장 가능성 있음"],
        ["입원비", "입원 치료 시 지급 가능", "약관 확인 필요"],
        ["수술비", "수술 치료 시 지급 가능", "약관에 따라 다름"],
    ]
    table = Table(matrix_rows, colWidths=[38*mm, 70*mm, 52*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(brand_color)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor("#F6F8FB")]),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 6))

    # 타임라인
    elements.append(Paragraph("보험청구 타임라인 (단계)", subtitle_style))
    timeline_text = "접수 \u2192 심사 \u2192 결과통보 \u2192 지급"
    elements.append(Paragraph(timeline_text, body_style))
    elements.append(Spacer(1, 6))

    # 체크리스트 (4개로 제한)
    elements.append(Paragraph("필요서류 체크항목란 (보험청구 관련)", subtitle_style))
    checklist_html = "<br/>".join(["☑ 진단서", "☑ 영수증", "☑ 입퇴원확인서", "☑ 신분증 사본"])
    elements.append(Paragraph(checklist_html, body_style))
    elements.append(Spacer(1, 8))

    # 하단 - QR + 면책
    elements.append(Paragraph(f"문의 QR → {insurer_name} 고객센터", subtitle_style))
    elements.append(QRFlowable(qr_url, mm_size=24))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(f'<font size="8">{footer_note}</font>', body_style))

    # 생성
    doc.build(elements)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes

# ----------------------------------------------------------------------
# /qa/answer_pdf : 보험사 자동 인식 + 브랜드 반영 + 1페이지 템플릿 + 자동 저장
#   - 기본: JSON 모드(자동 저장 후 file_url 반환)
#   - 옵션: return_mode="stream" 이면 바이너리 스트리밍
# ----------------------------------------------------------------------
@router.post("/answer_pdf")
async def answer_pdf(payload: Dict[str, Any]):
    """
    요청 예:
    {
      "question": "유방암 진단...",
      "policy_type": "현대해상" | "DB손해보험" | "삼성화재",
      "top_k": 5,
      "detect_metas": ["..."],
      "return_mode": "json" | "stream"   # 기본: json
    }
    """
    question = (payload.get("question") or "").strip()
    insurer_hint = payload.get("policy_type")
    top_k = int(payload.get("top_k") or 5)
    detect_metas = payload.get("detect_metas") or []
    return_mode = (payload.get("return_mode") or "json").lower()

    # 1) 컨텍스트 조회
    try:
        from app.services.rag_service import retrieve_context
        ctx_blocks_str: str = retrieve_context(
            question or "상담 리포트 생성", insurer=insurer_hint, top_k=top_k
        )
    except Exception as e:
        return JSONResponse(
            {"ok": False, "answer": "(검색 실패)", "sources": [], "error": f"retrieval_failed: {e}"},
            status_code=200,
        )

    # 2) 보험사 자동 인식
    detected = detect_insurer(question, [*detect_metas, ctx_blocks_str[:500]])
    insurer_name = normalize_insurer_name(insurer_hint) or detected or "현대해상"
    prof = get_insurer_profile(insurer_name)

    # 3) PDF 생성
    try:
        font_name = _register_korean_font()
        pdf_bytes = _build_onepage_pdf_bytes(
            title="보험 요약 한눈에",
            insurer_name=prof["name"],
            question=question or "—",
            brand_color=prof["brand_color"],
            qr_url=prof["qr_url"],
            footer_note=prof["footer_note"],
            font_name=font_name,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "answer": "PDF 생성 실패", "error": f"pdf_failed: {e}"}, status_code=200)

    # 4) 저장 위치 & URL
    BASE_DIR = Path(__file__).resolve().parents[2]
    FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "files")).resolve()
    REPORT_DIR = FILES_DIR / "reports"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"insurance_report_{ts}.pdf"
    out_path = (REPORT_DIR / fname)
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)

    # 5) 상대/절대 URL
    rel_url = f"/files/reports/{fname}"
    api_base = os.getenv("PUBLIC_API_BASE") or ""
    abs_url = f"{api_base}{rel_url}" if api_base else rel_url

    # 6) 헤더: ASCII만 (한글은 퍼센트 인코딩)
    insurer_enc = quote(prof["name"] or "", safe="")

    if return_mode == "stream":
        headers = {
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Access-Control-Expose-Headers": "Content-Disposition, X-File-URL, X-Abs-URL, X-Insurer-Encoded",
            "X-File-URL": rel_url,
            "X-Abs-URL": abs_url,
            "X-Insurer-Encoded": insurer_enc,
        }
        return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)

    # 기본: JSON 모드
    return JSONResponse(
        {
            "ok": True,
            "file_url": rel_url,          # 상대 URL
            "url": rel_url,               # 레거시 호환
            "absolute_url": abs_url,      # 절대 URL (PUBLIC_API_BASE가 설정된 경우)
            "file_path": str(out_path),
            "insurer": prof["name"],      # 한글 그대로
            "insurer_encoded": insurer_enc,
            "filename": fname,
        },
        headers={
            "Access-Control-Expose-Headers": "X-File-URL, X-Abs-URL, X-Insurer-Encoded",
            "X-File-URL": rel_url,
            "X-Abs-URL": abs_url,
            "X-Insurer-Encoded": insurer_enc,
        },
    )
