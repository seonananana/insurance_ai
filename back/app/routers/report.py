# back/app/routers/report.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ReportLab
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

router = APIRouter(prefix="/qa", tags=["report"])

# back/app/routers/report.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ReportLab
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

router = APIRouter(prefix="/qa", tags=["report"])

# ─────────────────────────────────────────────────────────────────────────────
# 폰트 등록 (KoPubWorld Dotum → 실패 시 CID 폰트로 폴백 → 최후 Helvetica)
# ─────────────────────────────────────────────────────────────────────────────
def _register_fonts() -> tuple[str, str]:
    """returns (regular_font_name, bold_font_name)"""
    # 1) KoPubWorld Dotum TTF 탐색
    back_root = Path(__file__).resolve().parents[2]  # .../back
    candidates_dirs = [
        back_root,
        back_root / "fonts",
        Path.cwd(),
        Path.cwd() / "fonts",
    ]
    regular_candidates = [
        "KoPubWorld Dotum Light.ttf",
        "KoPubWorldDotum-Light.ttf",
        "KoPubWorld_Dotum_Light.ttf",
        "KoPubWorld Dotum Medium.ttf",
        "KoPubWorldDotum-Medium.ttf",
    ]
    bold_candidates = [
        "KoPubWorld Dotum Bold.ttf",
        "KoPubWorldDotum-Bold.ttf",
        "KoPubWorld_Dotum_Bold.ttf",
    ]

    regular_path = None
    bold_path = None
    for d in candidates_dirs:
        for n in regular_candidates:
            p = d / n
            if p.exists():
                regular_path = p
                break
        for n in bold_candidates:
            p = d / n
            if p.exists():
                bold_path = p
                break
        if regular_path:
            break

    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont("KoPubDotum", str(regular_path)))
            pdfmetrics.registerFont(TTFont("KoPubDotum-Bold", str(bold_path or regular_path)))
            return "KoPubDotum", "KoPubDotum-Bold"
    except Exception:
        # TTF 로드 실패 → 아래 CID 폰트로 폴백
        pass

    # 2) CID 폰트(내장) – 한글 출력 안정
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        # CID 폰트는 Bold 변형이 별도로 없어서 동일 폰트 사용
        return "HYSMyeongJo-Medium", "HYSMyeongJo-Medium"
    except Exception:
        pass

    # 3) 최후 폴백(영문 환경)
    return "Helvetica", "Helvetica-Bold"


_FONT_REG, _FONT_BOLD = _register_fonts()

# ─────────────────────────────────────────────────────────────────────────────
# 레이아웃 / 유틸
# ─────────────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_X = 40
CURSOR_BOTTOM = 40

def _wrap_lines(text: str, font: str, size: int, max_width: float) -> List[str]:
    """단어 단위로 줄바꿈, 초과 시 글자단위 폴백"""
    res: List[str] = []
    for raw in (text or "").splitlines() or [""]:
        words = raw.split(" ")
        line = ""
        for w in words:
            trial = (line + " " + w).strip() if line else w
            if stringWidth(trial, font, size) <= max_width:
                line = trial
            else:
                if not line:  # 단어 하나가 너무 길면 글자단위로 분해
                    buf = ""
                    for ch in w:
                        if stringWidth(buf + ch, font, size) <= max_width:
                            buf += ch
                        else:
                            if buf:
                                res.append(buf)
                            buf = ch
                    if buf:
                        line = buf
                    else:
                        line = ""
                else:
                    res.append(line)
                    line = w
        res.append(line)
    return res

def _ensure_page(c: canvas.Canvas, y: float, font: str, size: int) -> float:
    if y < CURSOR_BOTTOM:
        c.showPage()
        c.setFont(font, size)
        return PAGE_H - 50
    return y

def _draw_paragraph(c: canvas.Canvas, text: str, y: float, font: str, size: int = 11, leading: int = 16) -> float:
    c.setFont(font, size)
    max_w = PAGE_W - 2 * MARGIN_X
    for line in _wrap_lines(text, font, size, max_w):
        c.drawString(MARGIN_X, y, line)
        y -= leading
        y = _ensure_page(c, y, font, size)
    return y

def _draw_heading(c: canvas.Canvas, text: str, y: float, size: int = 14) -> float:
    c.setFont(_FONT_BOLD, size)
    c.drawString(MARGIN_X, y, text)
    y -= 18
    return y

def _draw_sep(c: canvas.Canvas, y: float) -> float:
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
    return y - 12

def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: int = 90) -> None:
    q = qr.QrCodeWidget(url)
    b = q.getBounds()
    w = b[2] - b[0]
    h = b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(q)
    renderPDF.draw(d, c, x, y)

# ─────────────────────────────────────────────────────────────────────────────
# 스키마
# ─────────────────────────────────────────────────────────────────────────────
class CoverageItem(BaseModel):
    item: str
    covered: Optional[bool] = None
    note: Optional[str] = None

class TimelineStep(BaseModel):
    step: str
    when: Optional[str] = None
    note: Optional[str] = None

class PdfPayload(BaseModel):
    title: str = "보험 청구 상담 결과"
    content: Optional[str] = None
    summary: Optional[str] = None
    likelihood: Optional[str] = None
    coverage_items: List[CoverageItem] = Field(default_factory=list)
    timeline: List[TimelineStep] = Field(default_factory=list)
    required_docs: List[str] = Field(default_factory=list)
    qr_url: Optional[str] = None
    disclaimer: Optional[str] = None
    meta: Optional[str] = None  # 모델/시간/Top-K 등 자유메타

class ChatMsg(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ChatlogPayload(BaseModel):
    title: str = "보험 상담 대화 요약"
    messages: List[ChatMsg] = Field(default_factory=list)
    qr_url: Optional[str] = None
    disclaimer: Optional[str] = None
    meta: Optional[str] = None

# ─────────────────────────────────────────────────────────────────────────────
# 엔드포인트: 폼 기반 PDF
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/answer_pdf")
def answer_pdf(payload: PdfPayload):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(_FONT_BOLD, 16)
    c.drawString(MARGIN_X, y, payload.title)
    y -= 26

    # 가이드(최대 8줄)
    guide = (
        "아래는 상담 내용을 요약한 문서입니다. 필요한 정보(사고/발병일, 진단/증상, 치료유형, "
        "입원일수/수술 여부, 진단/수술코드, 입·퇴원일/통원횟수, 가입특약, 서류 보유 여부 등)를 "
        "추가로 제공해 주시면 보다 정확한 안내가 가능합니다."
    )
    y = _draw_paragraph(c, guide, y, _FONT_REG, size=10, leading=14)
    y -= 4

    # 상단 요약
    if payload.summary or payload.likelihood or payload.meta:
        y = _draw_sep(c, y)
        y = _draw_heading(c, "사건 요약 / 청구 가능성", y)
        if payload.summary:
            y = _draw_paragraph(c, f"• 사건 요약: {payload.summary}", y, _FONT_REG)
        if payload.likelihood:
            y = _draw_paragraph(c, f"• 청구 가능성: {payload.likelihood}", y, _FONT_REG)
        if payload.meta:
            y = _draw_paragraph(c, f"• 메타: {payload.meta}", y, _FONT_REG)

    # 본론
    if payload.coverage_items or payload.timeline or payload.required_docs:
        y = _draw_sep(c, y)
        y = _draw_heading(c, "본론", y)

        if payload.coverage_items:
            c.setFont(_FONT_BOLD, 11)
            c.drawString(MARGIN_X, y, "보험 적용 항목(메트릭스)")
            y -= 16
            for it in payload.coverage_items:
                tag = "✅ 적용" if it.covered is True else ("❌ 비적용" if it.covered is False else "◻︎ 검토")
                line = f"- {it.item}  ({tag})" + (f" – {it.note}" if it.note else "")
                y = _draw_paragraph(c, line, y, _FONT_REG, size=11)
            y -= 4

        if payload.timeline:
            y -= 2
            c.setFont(_FONT_BOLD, 11)
            c.drawString(MARGIN_X, y, "보험 청구 타임라인")
            y -= 16
            for idx, stp in enumerate(payload.timeline, 1):
                head = f"{idx}. {stp.step}" + (f"  ({stp.when})" if stp.when else "")
                y = _draw_paragraph(c, head, y, _FONT_REG, size=11)
                if stp.note:
                    y = _draw_paragraph(c, f"   - {stp.note}", y, _FONT_REG, size=10, leading=14)
            y -= 4

        if payload.required_docs:
            y -= 2
            c.setFont(_FONT_BOLD, 11)
            c.drawString(MARGIN_X, y, "필요 서류 체크")
            y -= 16
            for d in payload.required_docs:
                y = _draw_paragraph(c, f"□ {d}", y, _FONT_REG, size=11)
            y -= 4

    # 부록
    if payload.content:
        y = _draw_sep(c, y)
        y = _draw_heading(c, "부록", y)
        y = _draw_paragraph(c, payload.content, y, _FONT_REG)

    # 하단
    y = _draw_sep(c, y)
    if payload.qr_url:
        _draw_qr(c, payload.qr_url, PAGE_W - MARGIN_X - 90, max(y - 90, 60))
        y = min(y, PAGE_H - 160)

    disclaimer = payload.disclaimer or "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사 약관 및 심사 결과에 따릅니다."
    y = _draw_paragraph(c, disclaimer, max(y, 40), _FONT_REG, size=9, leading=12)

    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="answer.pdf"'},
    )

# ─────────────────────────────────────────────────────────────────────────────
# 엔드포인트: 대화 로그 기반 PDF
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/chatlog_pdf")
def chatlog_pdf(payload: ChatlogPayload):
    """
    messages = [{ "role": "user"/"assistant", "content": "..." }, ...]
    마지막 assistant 응답을 '핵심 답변'으로 강조.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(_FONT_BOLD, 16)
    c.drawString(MARGIN_X, y, payload.title)
    y -= 26

    if payload.meta:
        y = _draw_paragraph(c, f"메타: {payload.meta}", y, _FONT_REG, size=10, leading=14)
        y -= 2

    # 본문
    y = _draw_sep(c, y)
    y = _draw_heading(c, "대화 내용", y)

    last_assistant_idx = -1
    for i, m in enumerate(payload.messages):
        if m.role == "assistant":
            last_assistant_idx = i

    for i, m in enumerate(payload.messages):
        is_last_ans = (i == last_assistant_idx and m.role == "assistant")
        role_title = "👤 고객" if m.role == "user" else "🤖 상담봇"

        if is_last_ans:
            y = _draw_paragraph(c, "[핵심 답변]", y, _FONT_BOLD, size=12)
            y = _draw_paragraph(c, m.content, y, _FONT_REG, size=11, leading=16)
        else:
            y = _draw_paragraph(c, role_title, y, _FONT_BOLD, size=10)
            y = _draw_paragraph(c, m.content, y, _FONT_REG, size=10, leading=14)
        y -= 4

    # 하단
    y = _draw_sep(c, y)
    if payload.qr_url:
        _draw_qr(c, payload.qr_url, PAGE_W - MARGIN_X - 90, max(y - 90, 60))
        y = min(y, PAGE_H - 160)

    disclaimer = payload.disclaimer or "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사 약관 및 심사 결과에 따릅니다."
    y = _draw_paragraph(c, disclaimer, max(y, 40), _FONT_REG, size=9, leading=12)

    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename=\"chatlog.pdf\"'},
    )

# ─────────────────────────────────────────────────────────────────────────────
# 레이아웃 / 유틸
# ─────────────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_X = 40
CURSOR_BOTTOM = 40

def _wrap_lines(text: str, font: str, size: int, max_width: float) -> List[str]:
    """단어 단위로 줄바꿈, 초과 시 글자단위 폴백"""
    res: List[str] = []
    for raw in (text or "").splitlines() or [""]:
        words = raw.split(" ")
        line = ""
        for w in words:
            trial = (line + " " + w).strip() if line else w
            if stringWidth(trial, font, size) <= max_width:
                line = trial
            else:
                if not line:  # 단어 하나가 너무 길면 글자단위로 분해
                    buf = ""
                    for ch in w:
                        if stringWidth(buf + ch, font, size) <= max_width:
                            buf += ch
                        else:
                            if buf:
                                res.append(buf)
                            buf = ch
                    if buf:
                        line = buf
                    else:
                        line = ""
                else:
                    res.append(line)
                    line = w
        res.append(line)
    return res

def _ensure_page(c: canvas.Canvas, y: float, font: str, size: int) -> float:
    if y < CURSOR_BOTTOM:
        c.showPage()
        c.setFont(font, size)
        return PAGE_H - 50
    return y

def _draw_paragraph(c: canvas.Canvas, text: str, y: float, font: str, size: int = 11, leading: int = 16) -> float:
    c.setFont(font, size)
    max_w = PAGE_W - 2 * MARGIN_X
    for line in _wrap_lines(text, font, size, max_w):
        c.drawString(MARGIN_X, y, line)
        y -= leading
        y = _ensure_page(c, y, font, size)
    return y

def _draw_heading(c: canvas.Canvas, text: str, y: float, size: int = 14) -> float:
    c.setFont(_FONT_BOLD, size)
    c.drawString(MARGIN_X, y, text)
    y -= 18
    return y

def _draw_sep(c: canvas.Canvas, y: float) -> float:
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
    return y - 12

def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: int = 90) -> None:
    q = qr.QrCodeWidget(url)
    b = q.getBounds()
    w = b[2] - b[0]
    h = b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(q)
    renderPDF.draw(d, c, x, y)

# ─────────────────────────────────────────────────────────────────────────────
# 스키마
# ─────────────────────────────────────────────────────────────────────────────
class CoverageItem(BaseModel):
    item: str
    covered: Optional[bool] = None
    note: Optional[str] = None

class TimelineStep(BaseModel):
    step: str
    when: Optional[str] = None
    note: Optional[str] = None

class PdfPayload(BaseModel):
    title: str = "보험 청구 상담 결과"
    content: Optional[str] = None
    summary: Optional[str] = None
    likelihood: Optional[str] = None
    coverage_items: List[CoverageItem] = Field(default_factory=list)
    timeline: List[TimelineStep] = Field(default_factory=list)
    required_docs: List[str] = Field(default_factory=list)
    qr_url: Optional[str] = None
    disclaimer: Optional[str] = None
    meta: Optional[str] = None  # 모델/시간/Top-K 등 자유메타

class ChatMsg(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ChatlogPayload(BaseModel):
    title: str = "보험 상담 대화 요약"
    messages: List[ChatMsg] = Field(default_factory=list)
    qr_url: Optional[str] = None
    disclaimer: Optional[str] = None
    meta: Optional[str] = None

# ─────────────────────────────────────────────────────────────────────────────
# 엔드포인트: 폼 기반 PDF
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/answer_pdf")
def answer_pdf(payload: PdfPayload):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(_FONT_BOLD, 16)
    c.drawString(MARGIN_X, y, payload.title)
    y -= 26

    # 가이드(최대 8줄)
    guide = (
        "아래는 상담 내용을 요약한 문서입니다. 필요한 정보(사고/발병일, 진단/증상, 치료유형, "
        "입원일수/수술 여부, 진단/수술코드, 입·퇴원일/통원횟수, 가입특약, 서류 보유 여부 등)를 "
        "추가로 제공해 주시면 보다 정확한 안내가 가능합니다."
    )
    y = _draw_paragraph(c, guide, y, _FONT_REG, size=10, leading=14)
    y -= 4

    # 상단 요약
    if payload.summary or payload.likelihood or payload.meta:
        y = _draw_sep(c, y)
        y = _draw_heading(c, "사건 요약 / 청구 가능성", y)
        if payload.summary:
            y = _draw_paragraph(c, f"• 사건 요약: {payload.summary}", y, _FONT_REG)
        if payload.likelihood:
            y = _draw_paragraph(c, f"• 청구 가능성: {payload.likelihood}", y, _FONT_REG)
        if payload.meta:
            y = _draw_paragraph(c, f"• 메타: {payload.meta}", y, _FONT_REG)

    # 본론
    if payload.coverage_items or payload.timeline or payload.required_docs:
        y = _draw_sep(c, y)
        y = _draw_heading(c, "본론", y)

        if payload.coverage_items:
            c.setFont(_FONT_BOLD, 11)
            c.drawString(MARGIN_X, y, "보험 적용 항목(메트릭스)")
            y -= 16
            for it in payload.coverage_items:
                tag = "✅ 적용" if it.covered is True else ("❌ 비적용" if it.covered is False else "◻︎ 검토")
                line = f"- {it.item}  ({tag})" + (f" – {it.note}" if it.note else "")
                y = _draw_paragraph(c, line, y, _FONT_REG, size=11)
            y -= 4

        if payload.timeline:
            y -= 2
            c.setFont(_FONT_BOLD, 11)
            c.drawString(MARGIN_X, y, "보험 청구 타임라인")
            y -= 16
            for idx, stp in enumerate(payload.timeline, 1):
                head = f"{idx}. {stp.step}" + (f"  ({stp.when})" if stp.when else "")
                y = _draw_paragraph(c, head, y, _FONT_REG, size=11)
                if stp.note:
                    y = _draw_paragraph(c, f"   - {stp.note}", y, _FONT_REG, size=10, leading=14)
            y -= 4

        if payload.required_docs:
            y -= 2
            c.setFont(_FONT_BOLD, 11)
            c.drawString(MARGIN_X, y, "필요 서류 체크")
            y -= 16
            for d in payload.required_docs:
                y = _draw_paragraph(c, f"□ {d}", y, _FONT_REG, size=11)
            y -= 4

    # 부록
    if payload.content:
        y = _draw_sep(c, y)
        y = _draw_heading(c, "부록", y)
        y = _draw_paragraph(c, payload.content, y, _FONT_REG)

    # 하단
    y = _draw_sep(c, y)
    if payload.qr_url:
        _draw_qr(c, payload.qr_url, PAGE_W - MARGIN_X - 90, max(y - 90, 60))
        y = min(y, PAGE_H - 160)

    disclaimer = payload.disclaimer or "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사 약관 및 심사 결과에 따릅니다."
    y = _draw_paragraph(c, disclaimer, max(y, 40), _FONT_REG, size=9, leading=12)

    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="answer.pdf"'},
    )

# ─────────────────────────────────────────────────────────────────────────────
# 엔드포인트: 대화 로그 기반 PDF
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/chatlog_pdf")
def chatlog_pdf(payload: ChatlogPayload):
    """
    messages = [{ "role": "user"/"assistant", "content": "..." }, ...]
    마지막 assistant 응답을 '핵심 답변'으로 강조.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(_FONT_BOLD, 16)
    c.drawString(MARGIN_X, y, payload.title)
    y -= 26

    if payload.meta:
        y = _draw_paragraph(c, f"메타: {payload.meta}", y, _FONT_REG, size=10, leading=14)
        y -= 2

    # 본문
    y = _draw_sep(c, y)
    y = _draw_heading(c, "대화 내용", y)

    last_assistant_idx = -1
    for i, m in enumerate(payload.messages):
        if m.role == "assistant":
            last_assistant_idx = i

    for i, m in enumerate(payload.messages):
        is_last_ans = (i == last_assistant_idx and m.role == "assistant")
        role_title = "👤 고객" if m.role == "user" else "🤖 상담봇"

        if is_last_ans:
            y = _draw_paragraph(c, "[핵심 답변]", y, _FONT_BOLD, size=12)
            y = _draw_paragraph(c, m.content, y, _FONT_REG, size=11, leading=16)
        else:
            y = _draw_paragraph(c, role_title, y, _FONT_BOLD, size=10)
            y = _draw_paragraph(c, m.content, y, _FONT_REG, size=10, leading=14)
        y -= 4

    # 하단
    y = _draw_sep(c, y)
    if payload.qr_url:
        _draw_qr(c, payload.qr_url, PAGE_W - MARGIN_X - 90, max(y - 90, 60))
        y = min(y, PAGE_H - 160)

    disclaimer = payload.disclaimer or "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사 약관 및 심사 결과에 따릅니다."
    y = _draw_paragraph(c, disclaimer, max(y, 40), _FONT_REG, size=9, leading=12)

    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename=\"chatlog.pdf\"'},
    )
