# back/app/main.py
# FastAPI 앱 초기화 + CORS + 라우터 등록(health, qa, chat, report, chatlog)

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routers import health, qa, chat, report
from io import BytesIO
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from textwrap import wrap
from typing import List, Optional
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

try:
    from app.routers import report          # /qa/... (report.py 내부 prefix="/qa")
except Exception:
    report = None
try:
    from app.routers import chatlog         # /chat/log (chatlog.py 내부 prefix="/chat")
except Exception:
    chatlog = None

app = FastAPI(title="Insurance RAG API", version="0.3.0")

# 정적 파일 마운트(폴더 없어도 기동되게)
BASE_DIR = Path(__file__).resolve().parent.parent  # back/app -> back
FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "files")).resolve()
app.mount("/files", StaticFiles(directory=str(FILES_DIR), check_dir=False), name="files")

# CORS (로컬 Streamlit 기본 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(health.router, prefix="/health", tags=["health"])  # health는 내부 prefix 없음 → 여기서 부여
app.include_router(qa.router,     prefix="/qa",     tags=["qa"])      # qa.py는 내부 prefix 없음 → 여기서 부여
app.include_router(chat.router)                                        # chat.py는 내부 prefix="/chat" 이미 있음
app.include_router(report.router)

if chatlog is not None:
    app.include_router(chatlog.router)                                 # chatlog.py 내부 prefix="/chat"
if report is not None:
    app.include_router(report.router)                                  # report.py 내부 prefix="/qa"

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}
    
class PdfPayload(BaseModel):
    title: str = "응답"
    content: str  # PDF로 내릴 본문 텍스트

def _register_korean_fonts():
    """프로젝트 내 fonts/ 또는 시스템 폰트에서 한글 폰트를 등록."""
    FONT_DIRS = [
        Path(__file__).resolve().parent.parent / "fonts",   # back/fonts/
        Path("/usr/share/fonts/truetype/noto"),
        Path("/usr/share/fonts/opentype/noto"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
    ]
    candidates = [
        ("NotoSansKR", "NotoSansKR-Regular.otf", "NotoSansKR-Bold.otf"),
        ("NanumGothic", "NanumGothic.ttf", "NanumGothicBold.ttf"),
    ]
    for base in FONT_DIRS:
        try:
            for fam, reg, bold in candidates:
                reg_p = base / reg
                bold_p = base / bold
                if reg_p.exists() and bold_p.exists():
                    pdfmetrics.registerFont(TTFont(f"{fam}", str(reg_p)))
                    pdfmetrics.registerFont(TTFont(f"{fam}-Bold", str(bold_p)))
                    # family 등록(볼드 전환)
                    pdfmetrics.registerFontFamily(
                        fam, normal=fam, bold=f"{fam}-Bold", italic=fam, boldItalic=f"{fam}-Bold"
                    )
                    return fam  # 사용 가능한 패밀리명 반환
        except Exception:
            continue
    # fallback (영문만): 한글은 깨질 수 있음
    return "Helvetica"

_KR_FONT = _register_korean_fonts()


# ---- 페이로드 스키마 (기존 title/content 호환 + 구조화 입력 지원) ----
class CoverageItem(BaseModel):
    item: str
    covered: Optional[bool] = None  # True/False/None
    note: Optional[str] = None

class TimelineStep(BaseModel):
    step: str
    when: Optional[str] = None
    note: Optional[str] = None

class PdfPayload(BaseModel):
    title: str = "상담 결과"
    # 자유 텍스트 (기존 호환)
    content: Optional[str] = None

    # 구조화 섹션(선택)
    summary: Optional[str] = None            # 사건 요약
    likelihood: Optional[str] = None         # 청구 가능성
    coverage_items: List[CoverageItem] = []  # 보험 적용 항목(메트릭스)
    timeline: List[TimelineStep] = []        # 청구 타임라인
    required_docs: List[str] = []            # 필요 서류 체크란
    qr_url: Optional[str] = None             # 문의 QR
    disclaimer: Optional[str] = None         # 하단 변책 고지

# ---- 도우미 ----
PAGE_W, PAGE_H = A4
MARGIN_X = 40
CURSOR_BOTTOM = 40

def _wrap_lines(text: str, font: str, size: int, max_width: float) -> List[str]:
    """폰트 실제 폭 기준 줄바꿈."""
    lines = []
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

def _draw_heading(c: canvas.Canvas, text: str, y: float):
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 14)
    c.drawString(MARGIN_X, y, text);  y -= 18
    return y

def _draw_sep(c: canvas.Canvas, y: float, char: str = "-"):
    # 요구사항: '-----' 또는 '=====' 형태로 구분선. 시각적 선도 함께 긋자.
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y+2, PAGE_W - MARGIN_X, y+2)
    c.setFont(_KR_FONT, 9)
    c.drawString(MARGIN_X, y, char * 80)
    return y - 14

def _draw_paragraph(c: canvas.Canvas, text: str, y: float, font_size: int = 11, leading: int = 16):
    c.setFont(_KR_FONT, font_size)
    max_w = PAGE_W - 2 * MARGIN_X
    for line in _wrap_lines(text, _KR_FONT, font_size, max_w):
        c.drawString(MARGIN_X, y, line);  y -= leading
        if y < CURSOR_BOTTOM:
            c.showPage(); y = PAGE_H - 50; c.setFont(_KR_FONT, font_size)
    return y

def _draw_list(c: canvas.Canvas, items: List[str], y: float, bullet: str = "•", font_size: int = 11):
    c.setFont(_KR_FONT, font_size)
    max_w = PAGE_W - 2 * MARGIN_X - 14
    for s in items:
        lines = _wrap_lines(s, _KR_FONT, font_size, max_w)
        c.drawString(MARGIN_X, y, bullet)
        c.drawString(MARGIN_X + 12, y, lines[0]); y -= 16
        for cont in lines[1:]:
            c.drawString(MARGIN_X + 12, y, cont); y -= 16
        if y < CURSOR_BOTTOM:
            c.showPage(); y = PAGE_H - 50; c.setFont(_KR_FONT, font_size)
    return y

def _draw_coverage(c: canvas.Canvas, items: List[CoverageItem], y: float):
    # 간단한 메트릭스: [항목] [적용여부/메모]
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 11)
    c.drawString(MARGIN_X, y, "보험 적용 항목"); y -= 16
    c.setFont(_KR_FONT, 11)
    for it in items:
        tag = "✅ 적용" if it.covered is True else ("❌ 비적용" if it.covered is False else "◻︎")
        line = f"- {it.item}  ({tag})"
        if it.note:
            line += f" – {it.note}"
        y = _draw_paragraph(c, line, y, font_size=11)
        if y < CURSOR_BOTTOM:
            c.showPage(); y = PAGE_H - 50
    return y

def _draw_timeline(c: canvas.Canvas, steps: List[TimelineStep], y: float):
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 11)
    c.drawString(MARGIN_X, y, "보험 청구 타임라인"); y -= 16
    c.setFont(_KR_FONT, 11)
    for idx, stp in enumerate(steps, 1):
        head = f"{idx}. {stp.step}"
        if stp.when: head += f"  ({stp.when})"
        y = _draw_paragraph(c, head, y, font_size=11)
        if stp.note:
            y = _draw_paragraph(c, f"   - {stp.note}", y, font_size=10)
        if y < CURSOR_BOTTOM:
            c.showPage(); y = PAGE_H - 50
    return y

def _draw_required_docs(c: canvas.Canvas, docs: List[str], y: float):
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 11)
    c.drawString(MARGIN_X, y, "필요 서류 체크"); y -= 16
    c.setFont(_KR_FONT, 11)
    for d in docs:
        y = _draw_paragraph(c, f"□ {d}", y, font_size=11)
        if y < CURSOR_BOTTOM:
            c.showPage(); y = PAGE_H - 50
    return y

def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: int = 90):
    q = qr.QrCodeWidget(url)
    b = q.getBounds(); w = b[2] - b[0]; h = b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(q)
    renderPDF.draw(d, c, x, y)

# ---- 교체할 엔드포인트 ----
@app.post("/export/pdf")
def export_pdf(payload: PdfPayload):
    """
    - 기존: title/content만 받아 본문 출력
    - 확장: 구조화 필드를 주면 섹션 레이아웃으로 생성
    - 한글 폰트 내장, 구분선, QR, 하단 고지 포함
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold", 16)
    c.drawString(MARGIN_X, y, payload.title); y -= 24

    # ===== 상단: 사건 요약, 청구 가능성 =====
    if payload.summary or payload.likelihood:
        y = _draw_sep(c, y, "=")
        y = _draw_heading(c, "사건 요약 / 청구 가능성", y)
        if payload.summary:
            y = _draw_paragraph(c, f"사건 요약: {payload.summary}", y)
        if payload.likelihood:
            y = _draw_paragraph(c, f"청구 가능성: {payload.likelihood}", y)

    # ===== 본론: 적용 항목/타임라인/필요서류 =====
    if payload.coverage_items or payload.timeline or payload.required_docs:
        y = _draw_sep(c, y, "-")
        y = _draw_heading(c, "본론", y)

        if payload.coverage_items:
            y = _draw_coverage(c, payload.coverage_items, y);  y -= 6

        if payload.timeline:
            y -= 4
            y = _draw_timeline(c, payload.timeline, y);  y -= 6

        if payload.required_docs:
            y -= 4
            y = _draw_required_docs(c, payload.required_docs, y);  y -= 6

    # 자유 텍스트(content)도 들어오면 맨 끝에 부록처럼 추가
    if payload.content:
        y = _draw_sep(c, y, "-")
        y = _draw_heading(c, "부록", y)
        y = _draw_paragraph(c, payload.content, y)

    # ===== 하단: QR + 변책 고지 =====
    y = _draw_sep(c, y, "=")
    if payload.qr_url:
        _draw_qr(c, payload.qr_url, PAGE_W - MARGIN_X - 90, max(y - 90, 60))
        y = min(y, PAGE_H - 160)

    disclaimer = payload.disclaimer or "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 보험사/약관에 따릅니다."
    c.setFont(_KR_FONT, 9)
    for line in _wrap_lines(disclaimer, _KR_FONT, 9, PAGE_W - 2*MARGIN_X):
        c.drawString(MARGIN_X, max(y, 40), line);  y -= 12

    c.save()
    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="answer.pdf"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)
