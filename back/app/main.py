# back/app/main.py
# FastAPI 앱 초기화 + CORS + 라우터 등록(health, qa, chat, report, chatlog) + /export/pdf

import os
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 라우터
from app.routers import health, qa
try:
    from app.routers import chat         # (있으면 사용, 내부 prefix="/chat" 가정)
except Exception:
    chat = None
try:
    from app.routers import report       # (있으면 사용, 내부 prefix="/qa" 가정)
except Exception:
    report = None
try:
    from app.routers import chatlog      # (있으면 사용, 내부 prefix="/chat" 가정)
except Exception:
    chatlog = None

# ReportLab (PDF)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

# =========================================
# 앱 & 정적 파일
# =========================================
app = FastAPI(
    title="Insurance RAG API",
    version="0.3.1",
    redirect_slashes=False,  # 🔧 /health 307 리다이렉트 방지
)

BASE_DIR = Path(__file__).resolve().parent.parent  # back/app -> back
FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "files")).resolve()
# 폴더가 없어도 기동되게 check_dir=False
app.mount("/files", StaticFiles(directory=str(FILES_DIR), check_dir=False), name="files")

# =========================================
# CORS (로컬 Streamlit 기본 허용)
# =========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:8502",
        "http://127.0.0.1:8502",
        "*",  # 필요시 제거 가능
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# =========================================
# 라우터 등록
#  - health: 라우터 내부에서 /health 및 /health/ 처리 → 여기서 prefix **추가 금지**
#  - qa:     내부에서 prefix="/qa" 사용 → 그대로 등록
#  - chat:   내부에서 prefix="/chat" 사용 → 그대로 등록
#  - report, chatlog: 있으면 등록
# =========================================
app.include_router(health.router)  # ✅ prefix 주지 마세요 (기존 /health/health 문제 원인)
app.include_router(qa.router)      # qa.py에 prefix="/qa"가 이미 있음
if chat:
    app.include_router(chat.router)
if report:
    app.include_router(report.router)
if chatlog:
    app.include_router(chatlog.router)

@app.get("/", include_in_schema=False)
def root():
    return {"ok": True, "service": "Insurance RAG API", "version": app.version}

# =========================================
# 폰트 등록 유틸
# =========================================
def _register_kopub_from_back_root() -> Optional[str]:
    """
    back/ 바로 아래에 둔 KoPubWorld Dotum Light/Bold 를 등록.
    Bold가 없으면 Light를 Bold alias로 재등록.
    """
    back_root = Path(__file__).resolve().parent.parent  # .../back
    regular_candidates = [
        back_root / "KoPubWorld Dotum Light.ttf",
        back_root / "KoPubWorldDotum-Light.ttf",
        back_root / "KoPubWorld_Dotum_Light.ttf",
    ]
    bold_candidates = [
        back_root / "KoPubWorld Dotum Bold.ttf",
        back_root / "KoPubWorldDotum-Bold.ttf",
        back_root / "KoPubWorld_Dotum_Bold.ttf",
    ]
    reg = next((p for p in regular_candidates if p.exists()), None)
    if not reg:
        return None
    pdfmetrics.registerFont(TTFont("KoPubDotum", str(reg)))

    bold = next((p for p in bold_candidates if p.exists()), None)
    if bold and bold.exists():
        pdfmetrics.registerFont(TTFont("KoPubDotum-Bold", str(bold)))
    else:
        pdfmetrics.registerFont(TTFont("KoPubDotum-Bold", str(reg)))

    pdfmetrics.registerFontFamily(
        "KoPubDotum",
        normal="KoPubDotum",
        bold="KoPubDotum-Bold",
        italic="KoPubDotum",
        boldItalic="KoPubDotum-Bold",
    )
    return "KoPubDotum"

def _register_korean_fonts() -> str:
    """
    KoPubDotum 우선, 없으면 Noto/Nanum 탐색. 그래도 없으면 Helvetica(한글 □ 가능).
    """
    fam = _register_kopub_from_back_root()
    if fam:
        return fam

    FONT_DIRS = [
        BASE_DIR / "fonts",                         # back/fonts/
        Path("/usr/share/fonts/truetype/noto"),
        Path("/usr/share/fonts/opentype/noto"),
        Path("/usr/share/fonts/truetype/nanum"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
    ]
    candidates = [
        ("NotoSansKR", "NotoSansKR-Regular.otf", "NotoSansKR-Bold.otf"),
        ("NanumGothic", "NanumGothic.ttf", "NanumGothicBold.ttf"),
    ]
    for base in FONT_DIRS:
        try:
            for fam_name, reg, bold in candidates:
                reg_p, bold_p = base / reg, base / bold
                if reg_p.exists() and bold_p.exists():
                    pdfmetrics.registerFont(TTFont(fam_name, str(reg_p)))
                    pdfmetrics.registerFont(TTFont(f"{fam_name}-Bold", str(bold_p)))
                    pdfmetrics.registerFontFamily(
                        fam_name,
                        normal=fam_name,
                        bold=f"{fam_name}-Bold",
                        italic=fam_name,
                        boldItalic=f"{fam_name}-Bold",
                    )
                    return fam_name
        except Exception:
            continue
    return "Helvetica"

_KR_FONT = _register_korean_fonts()

# =========================================
# PDF 생성 보조 함수들
# =========================================
PAGE_W, PAGE_H = A4
MARGIN_X = 40
CURSOR_BOTTOM = 40

def _wrap_lines(text: str, font: str, size: int, max_width: float) -> List[str]:
    """폰트 실제 폭 기준 줄바꿈."""
    if not text:
        return [""]
    lines: List[str] = []
    for raw in text.splitlines() or [""]:
        buf = ""
        for ch in raw:
            if stringWidth(buf + ch, font, size) <= max_width:
                buf += ch
            else:
                lines.append(buf)
                buf = ch
        lines.append(buf)
    return lines or [""]

def _heading_font() -> str:
    return f"{_KR_FONT}-Bold" if _KR_FONT != "Helvetica" else "Helvetica-Bold"

def _draw_heading(c: canvas.Canvas, text: str, y: float):
    c.setFont(_heading_font(), 14)
    c.drawString(MARGIN_X, y, text);  y -= 18
    return y

def _draw_sep(c: canvas.Canvas, y: float, char: str = "-"):
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
    for s in items or []:
        lines = _wrap_lines(s, _KR_FONT, font_size, max_w)
        c.drawString(MARGIN_X, y, bullet)
        c.drawString(MARGIN_X + 12, y, lines[0]); y -= 16
        for cont in lines[1:]:
            c.drawString(MARGIN_X + 12, y, cont); y -= 16
        if y < CURSOR_BOTTOM:
            c.showPage(); y = PAGE_H - 50; c.setFont(_KR_FONT, font_size)
    return y

def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: int = 90):
    q = qr.QrCodeWidget(url)
    b = q.getBounds(); w = b[2] - b[0]; h = b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(q)
    renderPDF.draw(d, c, x, y)

# =========================================
# PDF 페이로드 스키마
# =========================================
class CoverageItem(BaseModel):
    item: str
    covered: Optional[bool] = None
    note: Optional[str] = None

class TimelineStep(BaseModel):
    step: str
    when: Optional[str] = None
    note: Optional[str] = None

class PdfPayload(BaseModel):
    title: str = "상담 결과"
    content: Optional[str] = None           # 부록(자유 텍스트)
    summary: Optional[str] = None           # 사건 요약
    likelihood: Optional[str] = None        # 청구 가능성
    coverage_items: List[CoverageItem] = [] # 보험 적용 항목
    timeline: List[TimelineStep] = []       # 청구 타임라인
    required_docs: List[str] = []           # 필요 서류 체크
    qr_url: Optional[str] = None            # 하단 QR
    disclaimer: Optional[str] = None        # 면책 고지

# =========================================
# /export/pdf : 프론트에서 바로 다운로드 버튼 띄우는 용도
# =========================================
@app.post("/export/pdf")
def export_pdf(payload: PdfPayload):
    """
    - title/content만 던져도 동작
    - summary/likelihood/coverage_items/timeline/required_docs/qr_url/disclaimer 지원
    - 한글 폰트 자동 등록
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(payload.title)

    y = PAGE_H - 50

    # 제목
    c.setFont(_heading_font(), 16)
    c.drawString(MARGIN_X, y, payload.title); y -= 24

    # 상단: 사건 요약/청구 가능성
    if payload.summary or payload.likelihood:
        y = _draw_sep(c, y, "=")
        y = _draw_heading(c, "사건 요약 / 청구 가능성", y)
        if payload.summary:
            y = _draw_paragraph(c, f"사건 요약: {payload.summary}", y)
        if payload.likelihood:
            y = _draw_paragraph(c, f"청구 가능성: {payload.likelihood}", y)

    # 본론: 적용 항목/타임라인/필요서류
    if payload.coverage_items or payload.timeline or payload.required_docs:
        y = _draw_sep(c, y, "-")
        y = _draw_heading(c, "본론", y)

        if payload.coverage_items:
            c.setFont(_heading_font(), 11)
            c.drawString(MARGIN_X, y, "보험 적용 항목"); y -= 16
            for it in payload.coverage_items:
                tag = "✅ 적용" if it.covered is True else ("❌ 비적용" if it.covered is False else "◻︎")
                line = f"- {it.item}  ({tag})" + (f" – {it.note}" if it.note else "")
                y = _draw_paragraph(c, line, y, font_size=11)
            y -= 6

        if payload.timeline:
            y -= 4
            c.setFont(_heading_font(), 11)
            c.drawString(MARGIN_X, y, "보험 청구 타임라인"); y -= 16
            for idx, stp in enumerate(payload.timeline, 1):
                head = f"{idx}. {stp.step}" + (f"  ({stp.when})" if stp.when else "")
                y = _draw_paragraph(c, head, y, font_size=11)
                if stp.note:
                    y = _draw_paragraph(c, f"   - {stp.note}", y, font_size=10)
            y -= 6

        if payload.required_docs:
            y -= 4
            c.setFont(_heading_font(), 11)
            c.drawString(MARGIN_X, y, "필요 서류 체크"); y -= 16
            for d in payload.required_docs:
                y = _draw_paragraph(c, f"□ {d}", y, font_size=11)
            y -= 6

    # 부록(자유 텍스트)
    if payload.content:
        y = _draw_sep(c, y, "-")
        y = _draw_heading(c, "부록", y)
        y = _draw_paragraph(c, payload.content, y)

    # 하단: QR + 면책 고지
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

# =========================================
# Startup: SBERT 임베더 프리워밍 (첫 요청 지연/에러 완화)
# =========================================
@app.on_event("startup")
def _warmup():
    try:
        from app.services.rag_service import _get_embedder  # type: ignore
        _ = _get_embedder()
        print("[startup] ✅ SBERT embedder loaded")
    except Exception as e:
        print("[startup] ⚠️ Embedder warmup failed:", e)

# =========================================
# 로컬 실행 헬퍼 (python app/main.py 로 실행 시)
# =========================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "1") == "1",
    )
