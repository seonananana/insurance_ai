# back/app/utils/pdf_templates.py
from __future__ import annotations
import os, re, datetime
from io import BytesIO
from typing import List, Optional, Dict, Any, Iterable

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing

# ---------------- Brand profiles ----------------
INSURER_PROFILE: Dict[str, Dict[str, Any]] = {
    "현대해상": {
        "brand_color": "#003366",
        "qr_url": "https://www.hi.co.kr",
        "footer_note": "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 현대해상 약관 및 심사 결과에 따릅니다.",
    },
    "DB손해보험": {
        "brand_color": "#0C7E4B",
        "qr_url": "https://www.idbins.com",
        "footer_note": "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 DB손해보험 약관 및 심사 결과에 따릅니다.",
    },
    "삼성화재": {
        "brand_color": "#0055A5",
        "qr_url": "https://www.samsungfire.com",
        "footer_note": "※ 본 문서는 상담 편의를 위한 요약 자료이며, 최종 판단은 삼성화재 약관 및 심사 결과에 따릅니다.",
    },
}

ALIAS = [
    (r"현대\s*해상|현대해상|HI", "현대해상"),
    (r"DB\s*손해|DB손해|DB\s*Insurance|동부화재", "DB손해보험"),
    (r"삼성\s*화재|삼성화재|Samsung\s*Fire", "삼성화재"),
]

def normalize_insurer_name(name: Optional[str]) -> Optional[str]:
    if not name: 
        return None
    for pat, canon in ALIAS:
        if re.search(pat, name, flags=re.I):
            return canon
    return name  # unknown name passes through

def detect_insurer(question: str = "", metas: Optional[Iterable[str]] = None) -> Optional[str]:
    text = question or ""
    if metas:
        text += " " + " ".join([m or "" for m in metas])
    for pat, canon in ALIAS:
        if re.search(pat, text, flags=re.I):
            return canon
    return None

# ---------------- Fonts ----------------
def register_korean_font() -> str:
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
    return "Helvetica"

# ---------------- QR Flowable ----------------
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

# ---------------- Main PDF builder ----------------
def build_insurance_pdf(
    out_path: str,
    payload: Dict[str, Any],
) -> str:
    """
    out_path로 PDF 저장 (A4, 1쪽 목표)
    payload:
      - title: 기본 "보험 요약 한눈에"
      - insurer: "현대해상"|"DB손해보험"|"삼성화재"|기타
      - question: str
      - created_at: str
      - matrix_rows: List[List[str]]
      - timeline_steps: List[str]
      - checklist: List[str]
      - qr_url: str    # 없으면 보험사 프로필 사용
      - brand_color: str # 없으면 보험사 프로필 사용
      - footer_note: str # 없으면 보험사 프로필 사용
      - detect_metas: List[str]  # Top-K 문서 제목/출처 등
    """
    base_font = register_korean_font()

    # 보험사 결정
    insurer_in = normalize_insurer_name(payload.get("insurer"))
    if not insurer_in:
        insurer_in = detect_insurer(payload.get("question",""), payload.get("detect_metas"))
    insurer = insurer_in or "현대해상"  # 기본값

    prof = INSURER_PROFILE.get(insurer, INSURER_PROFILE["현대해상"])
    brand_color = payload.get("brand_color") or prof["brand_color"]
    qr_url = payload.get("qr_url") or prof["qr_url"]
    footer_note = payload.get("footer_note") or prof["footer_note"]

    title = payload.get("title") or "보험 요약 한눈에"
    created_at = payload.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    question = payload.get("question") or ""

    matrix_rows: List[List[str]] = payload.get("matrix_rows") or [
        ["구분", "항목", "비고"],
        ["진단비", "암 진단비", "보장 가능성 있음"],
        ["입원비", "입원 치료 시 지급 가능", "약관 확인 필요"],
        ["수술비", "수술 치료 시 지급 가능", "약관에 따라 다름"],
    ]
    timeline_steps: List[str] = payload.get("timeline_steps") or ["접수","심사","결과통보","지급"]
    checklist: List[str] = payload.get("checklist") or ["진단서","영수증","입퇴원확인서","신분증 사본"]

    # Styles
    title_style = ParagraphStyle(name='Title', fontName=base_font, fontSize=20, leading=24, alignment=1, spaceAfter=10)
    subtitle_style = ParagraphStyle(name='Subtitle', fontName=base_font, fontSize=13, leading=18, textColor=colors.HexColor(brand_color), spaceAfter=6)
    body_style = ParagraphStyle(name='Body', fontName=base_font, fontSize=11, leading=16)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=15*mm
    )
    doc.allowSplitting = 0  # 1페이지 유지 우선

    elements = []
    # 상단
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph("사건 요약 / 청구 가능성", subtitle_style))
    summary_text = f"""
    보험사: {insurer}<br/>
    문의: {question}<br/>
    생성일: {created_at}<br/>
    최종 판단은 보험사 심사 결과에 따라 달라질 수 있습니다.
    """
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 8))

    # 본론 - 메트릭스 표
    elements.append(Paragraph("보험적용항목 (메트릭스)", subtitle_style))
    table = Table(matrix_rows, colWidths=[38*mm, 70*mm, 52*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(brand_color)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), base_font),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor("#F6F8FB")]),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 8))

    # 타임라인
    elements.append(Paragraph("보험청구 타임라인 (단계)", subtitle_style))
    elements.append(Paragraph(" \u2192 ".join(timeline_steps), body_style))
    elements.append(Spacer(1, 8))

    # 체크리스트
    elements.append(Paragraph("필요서류 체크항목란 (보험청구 관련)", subtitle_style))
    elements.append(Paragraph("<br/>".join([f"☑ {c}" for c in checklist]), body_style))
    elements.append(Spacer(1, 8))

    # 하단 - QR + 면책
    elements.append(Paragraph(f"문의 QR → {insurer} 고객센터", subtitle_style))
    elements.append(QRFlowable(qr_url, mm_size=25))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f'<font size="8">{footer_note}</font>', body_style))

    # Build / Save
    doc.build(elements)
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())
    buf.close()
    return out_path
