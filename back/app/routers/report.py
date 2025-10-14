# back/app/routers/report.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── ReportLab (PDF)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF


router = APIRouter(tags=["report"])

# ─────────────────────────────────────────────────────────
# 폰트 등록 (back/ 루트에 둔 KoPubWorld Dotum Light.ttf 사용)
# ─────────────────────────────────────────────────────────
def _register_kopub_from_back_root() -> str | None:
    """
    back/ 바로 아래 또는 back/fonts/ 에 둔 KoPubWorld Dotum 폰트 등록.
    Bold가 없으면 Light 파일을 Bold로도 등록해 호환 유지.
    """
    back_root = Path(__file__).resolve().parent.parent.parent  # .../back
    candidates_dirs = [back_root, back_root / "fonts"]

    reg_names = [
        "KoPubWorld Dotum Light.ttf",
        "KoPubWorldDotum-Light.ttf",
        "KoPubWorld_Dotum_Light.ttf",
    ]
    bold_names = [
        "KoPubWorld Dotum Bold.ttf",
        "KoPubWorldDotum-Bold.ttf",
        "KoPubWorld_Dotum_Bold.ttf",
    ]

    regular = None
    bold = None
    for d in candidates_dirs:
        for n in reg_names:
            p = d / n
            if p.exists():
                regular = p
                break
        for n in bold_names:
            p = d / n
            if p.exists():
                bold = p
                break
        if regular:
            break

    if not regular:
        return None

    pdfmetrics.registerFont(TTFont("KoPubDotum", str(regular)))
    if bold:
        pdfmetrics.registerFont(TTFont("KoPubDotum-Bold", str(bold)))
    else:
        # Bold가 없으면 Light로 대체 등록(두께는 같지만 코드 호환)
        pdfmetrics.registerFont(TTFont("KoPubDotum-Bold", str(regular)))

    pdfmetrics.registerFontFamily(
        "KoPubDotum",
        normal="KoPubDotum",
        bold="KoPubDotum-Bold",
        italic="KoPubDotum",
        boldItalic="KoPubDotum-Bold",
    )
    return "KoPubDotum"


# 한글 기본 폰트 패밀리명 (KoPub 우선, 없으면 Helvetica)
_KR_FONT = _register_kopub_from_back_root() or "Helvetica"


# ─────────────────────────────────────────────────────────
# 요청 포맷(기존 title/content + 확장 섹션)
# ─────────────────────────────────────────────────────────
class CoverageItem(BaseModel):
    item: str
    covered: Optional[bool] = None  # True/False/None
    note: Optional[str] = None


class TimelineStep(BaseModel):
    step: str
    when: Optional[str] = None
    note: Optional[str] = None


class PdfPayload(BaseModel):
    title: str = "보험 청구 상담 결과"
    # 자유 텍스트(호환)
    content: Optional[str] = None

    # 구조화 섹션
    summary: Optional[str] = None              # 사건 요약
    likelihood: Optional[str] = None           # 청구 가능성
    coverage_items: List[CoverageItem] = []    # 보험 적용 항목(메트릭스)
    timeline: List[TimelineStep] = []          # 보험 청구 타임라인
    required_docs: List[str] = []              # 필요 서류 체크란
    qr_url: Optional[str] = None               # 문의용 QR
    disclaimer: Optional[str] = None           # 하단 변책 고지


# ─────────────────────────────────────────────────────────
# PDF 그리기 유틸
# ─────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_X = 40
CURSOR_BOTTOM = 40


def _wrap_lines(text: str, font: str, size: int, max_width: float) -> List[str]:
    lines: List[str] = []
    for raw in (text or "").splitlines() or [""]:
        buf = ""
        for ch in raw:
            if stringWidth(buf + ch, font, size) <= max_width:
                buf += ch
            else:
                lines.append(buf)
                buf = ch
        lines.append(buf)
    return lines


def _draw_heading(c: canvas.Canvas, text: str, y: float) -> float:
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 14)
    c.drawString(MARGIN_X, y, text)
    return y - 18


def _draw_sep(c: canvas.Canvas, y: float, char: str = "-") -> float:
    # '-----' / '=====' 요구 + 실선
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y + 2, PAGE_W - MARGIN_X, y + 2)
    c.setFont(_KR_FONT, 9)
    c.drawString(MARGIN_X, y, char * 80)
    return y - 14


def _draw_paragraph(c: canvas.Canvas, text: str, y: float, font_size: int = 11, leading: int = 16) -> float:
    c.setFont(_KR_FONT, font_size)
    max_w = PAGE_W - 2 * MARGIN_X
    for line in _wrap_lines(text, _KR_FONT, font_size, max_w):
        c.drawString(MARGIN_X, y, line)
        y -= leading
        if y < CURSOR_BOTTOM:
            c.showPage()
            y = PAGE_H - 50
            c.setFont(_KR_FONT, font_size)
    return y


def _draw_list(c: canvas.Canvas, items: List[str], y: float, bullet: str = "•", font_size: int = 11) -> float:
    c.setFont(_KR_FONT, font_size)
    max_w = PAGE_W - 2 * MARGIN_X - 14
    for s in items:
        lines = _wrap_lines(s, _KR_FONT, font_size, max_w)
        c.drawString(MARGIN_X, y, bullet)
        c.drawString(MARGIN_X + 12, y, lines[0])
        y -= 16
        for cont in lines[1:]:
            c.drawString(MARGIN_X + 12, y, cont)
            y -= 16
        if y < CURSOR_BOTTOM:
            c.showPage()
            y = PAGE_H - 50
            c.setFont(_KR_FONT, font_size)
    return y


def _draw_coverage(c: canvas.Canvas, items: List[CoverageItem], y: float) -> float:
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 11)
    c.drawString(MARGIN_X, y, "보험 적용 항목")
    y -= 16
    c.setFont(_KR_FONT, 11)
    for it in items:
        tag = "✅ 적용" if it.covered is True else ("❌ 비적용" if it.covered is False else "◻︎")
        line = f"- {it.item}  ({tag})"
        if it.note:
            line += f" – {it.note}"
        y = _draw_paragraph(c, line, y, font_size=11)
        if y < CURSOR_BOTTOM:
            c.showPage()
            y = PAGE_H - 50
    return y


def _draw_timeline(c: canvas.Canvas, steps: List[TimelineStep], y: float) -> float:
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 11)
    c.drawString(MARGIN_X, y, "보험 청구 타임라인")
    y -= 16
    c.setFont(_KR_FONT, 11)
    for idx, stp in enumerate(steps, 1):
        head = f"{idx}. {stp.step}"
        if stp.when:
            head += f"  ({stp.when})"
        y = _draw_paragraph(c, head, y, font_size=11)
        if stp.note:
            y = _draw_paragraph(c, f"   - {stp.note}", y, font_size=10)
        if y < CURSOR_BOTTOM:
            c.showPage()
            y = PAGE_H - 50
    return y


def _draw_required_docs(c: canvas.Canvas, docs: List[str], y: float) -> float:
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 11)
    c.drawString(MARGIN_X, y, "필요 서류 체크")
    y -= 16
    c.setFont(_KR_FONT, 11)
    for d in docs:
        y = _draw_paragraph(c, f"□ {d}", y, font_size=11)
        if y < CURSOR_BOTTOM:
            c.showPage()
            y = PAGE_H - 50
    return y


def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: int = 90) -> None:
    q = qr.QrCodeWidget(url)
    b = q.getBounds()
    w = b[2] - b[0]
    h = b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(q)
    renderPDF.draw(d, c, x, y)


# ─────────────────────────────────────────────────────────
# 라우트: /export/pdf
# ─────────────────────────────────────────────────────────
@router.post("/export/pdf")
def export_pdf(payload: PdfPayload):
    """
    - 한글 폰트를 KoPubWorld Dotum으로 임베드
    - 섹션 레이아웃:
      상단(사건 요약, 청구 가능성) ─ 본론(적용항목/타임라인/필요서류) ─ 하단(QR, 변책고지)
    - 구분선은 '=====', '-----' 텍스트 + 실선으로 표기
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 16)
    c.drawString(MARGIN_X, y, payload.title)
    y -= 24

    # ===== 상단: 사건 요약 / 청구 가능성 =====
    if payload.summary or payload.likelihood:
        y = _draw_sep(c, y, "=")
        y = _draw_heading(c, "사건 요약 / 청구 가능성", y)
        if payload.summary:
            y = _draw_paragraph(c, f"사건 요약: {payload.summary}", y)
        if payload.likelihood:
            y = _draw_paragraph(c, f"청구 가능성: {payload.likelihood}", y)

    # ===== 본론 =====
    if payload.coverage_items or payload.timeline or payload.required_docs:
        y = _draw_sep(c, y, "-")
        y = _draw_heading(c, "본론", y)

        if payload.coverage_items:
            y = _draw_coverage(c, payload.coverage_items, y)
            y -= 6

        if payload.timeline:
            y -= 4
            y = _draw_timeline(c, payload.timeline, y)
            y -= 6

        if payload.required_docs:
            y -= 4
            y = _draw_required_docs(c, payload.required_docs, y)
            y -= 6

    # (선택) 부록: 자유 텍스트 content
    if payload.content:
        y = _draw_sep(c, y, "-")
        y = _draw_heading(c, "부록", y)
        y = _draw_paragraph(c, payload.content, y)

    # ===== 하단: QR + 변책 고지 =====
    y = _draw_sep(c, y, "=")
    if payload.qr_url:
        _draw_qr(c, payload.qr_url, PAGE_W - MARGIN_X - 90, max(y - 90, 60))
        y = min(y, PAGE_H - 160)

    disclaimer = payload.disclaimer or "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사/약관 및 심사 결과에 따릅니다."
    c.setFont(_KR_FONT, 9)
    for line in _wrap_lines(disclaimer, _KR_FONT, 9, PAGE_W - 2 * MARGIN_X):
        c.drawString(MARGIN_X, max(y, 40), line)
        y -= 12

    c.save()
    buf.seek(0)  # ★ 중요: 이거 없으면 0바이트 응답
    headers = {"Content-Disposition": 'attachment; filename="answer.pdf"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)
