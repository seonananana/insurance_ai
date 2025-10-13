# app/services/pdf_report.py  (updated for bracket/box/QR layout)
import os, io, textwrap, base64, tempfile
from fpdf import FPDF

# 한글 폰트 경로 (없으면 기본 영문 폰트로 진행)
FONT_PATH = os.getenv("KOREAN_FONT_TTF", "").strip()

try:
    import qrcode
except Exception:
    qrcode = None  # QR없어도 동작하도록

class ReportPDF(FPDF):
    def header(self):
        self.set_font("Nanum" if FONT_PATH else "Arial", "B", 14)
        self.cell(0, 8, "보험 문서 RAG 답변", ln=1)
        self.ln(2)

    def h2(self, text):
        self.set_font("Nanum" if FONT_PATH else "Arial", "B", 12)
        self.cell(0, 7, text, ln=1)
        # subtle divider
        self.set_draw_color(200,200,200)
        self.line(self.l_margin, self.get_y(), 210-self.r_margin, self.get_y())
        self.ln(2)

    def p(self, text, size=11):
        self.set_font("Nanum" if FONT_PATH else "Arial", "", size)
        for line in textwrap.wrap(text or "-", 80):
            self.cell(0, 6, line, ln=1)

    # --- util: bracket (중간내용) ---
    def begin_bracket(self):
        """call before writing the middle block; returns y_start"""
        return self.get_y()

    def end_bracket(self, y_start, label="중간내용"):
        """draw a right-side bracket from y_start to current y"""
        y_end = self.get_y()
        if y_end <= y_start:  # nothing to draw
            return
        x = self.w - self.r_margin - 4  # right inset
        self.set_draw_color(0,0,0); self.set_line_width(0.6)
        # vertical
        self.line(x, y_start+1.5, x, y_end-1.5)
        # caps
        self.set_line_width(1.2)
        self.line(x, y_start, x+5, y_start)  # top small horizontal
        self.line(x, y_end,   x+5, y_end)    # bottom small horizontal
        # label (no rotation for simplicity; place small text near)
        self.set_font("Nanum" if FONT_PATH else "Arial", "", 9)
        self.set_text_color(40,40,40)
        # draw vertical label text (top-to-bottom)
        yy = (y_start + y_end)/2.0 - (len(label)*3)/2.0
        for i, ch in enumerate(label):
            self.text(x+6, yy + i*3.6, ch)
        self.set_text_color(0,0,0)
        self.set_line_width(0.2)

    # --- util: boxed area (근거 박스 등) ---
    def begin_box(self):
        """returns y_start to later draw rectangle"""
        return self.get_y()

    def end_box(self, y_start, title=None, border_color=(17,17,17)):
        y_end = self.get_y()
        x = self.l_margin
        w = self.w - self.l_margin - self.r_margin
        self.set_draw_color(*border_color)
        self.set_line_width(0.8)
        self.rect(x, y_start-2, w, (y_end - y_start) + 4)
        self.set_line_width(0.2)
        if title:
            # title badge
            self.set_fill_color(255,255,255)
            self.set_font("Nanum" if FONT_PATH else "Arial", "B", 11)
            self.set_xy(x+3, y_start-6.5)
            self.cell(32, 5.5, title, border=0)

def _ensure_fonts(pdf: FPDF):
    if FONT_PATH:
        try:
            pdf.add_font("Nanum","", FONT_PATH, uni=True)
            pdf.add_font("Nanum","B", FONT_PATH, uni=True)
        except Exception:
            pass  # 폰트 등록 실패 시 기본 폰트로 fallback

def _qr_tempfile(qr_url: str):
    if not (qrcode and qr_url):
        return None
    img = qrcode.make(qr_url)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path)
    return path

def build_pdf(payload: dict, out_path: str):
    pdf = ReportPDF()
    _ensure_fonts(pdf)
    pdf.add_page()

    # 상단 메타 + 상태 태그
    meta = f"보험사: {payload.get('policy_type','-')}  |  Top-k: {payload.get('top_k','-')}  |  conv_id: {payload.get('conv_id','-')}"
    pdf.set_font("Nanum" if FONT_PATH else "Arial","",10); pdf.cell(0,5,meta,ln=1); pdf.ln(1)

    status = payload.get("status",{})
    if status:
        tag = f"에러: {status.get('error','-')}   ·   정확성: {status.get('accuracy','-')}   ·   배경: {status.get('background','-')}"
        pdf.set_font("Nanum" if FONT_PATH else "Arial","",10)
        pdf.set_fill_color(242,242,247); pdf.set_draw_color(229,229,234)
        pdf.cell(0,6, tag, ln=1, border=1, fill=True)
        pdf.ln(2)

    # 요약
    pdf.h2("요약")
    pdf.p(payload.get("summary","-"))
    pdf.ln(2)

    # 작성방법 (있으면)
    howto = payload.get("howto") or []
    if howto:
        pdf.h2("작성방법 (중요)")
        for tip in howto:
            pdf.p(f"• {tip}")
        pdf.ln(1)

    # === 중간내용 (브라켓) 시작 ===
    y0 = pdf.begin_bracket()

    # 적합성 판단
    fitness = payload.get("fitness","check")
    badge = {"ok":"✅ 적합","check":"⚠️ 확인 필요","lack":"❌ 근거 부족"}.get(fitness, "⚠️ 확인 필요")
    conf  = int(payload.get("confidence",0))
    reason= payload.get("fitness_reason","-")
    pdf.h2("적합성 판단")
    pdf.p(f"{badge}  |  확신도 {conf}%")
    pdf.p(f"사유: {reason}")
    pdf.ln(1.5)

    # 다음 단계 · 타임라인
    pdf.h2("다음 단계 · 타임라인")
    steps = payload.get("timeline") or []
    if steps:
        for s in steps: pdf.p(f"• {s}")
    else:
        pdf.p("제공된 타임라인이 없습니다.")
    pdf.ln(1.5)

    # 권고 / 제안 (체크박스)
    recos = payload.get("recommendations") or []
    if recos:
        pdf.h2("권고 / 제안")
        pdf.set_font("Nanum" if FONT_PATH else "Arial","",11)
        for r in recos:
            text = r["text"] if isinstance(r, dict) else str(r)
            checked = bool(r.get("checked", False)) if isinstance(r, dict) else False
            box = "☑" if checked else "☐"
            pdf.p(f"{box} {text}")
        pdf.ln(1)

    # 필요서류 체크리스트
    pdf.h2("필요서류 체크리스트")
    docs = payload.get("required_docs",[])
    if docs:
        per_line = 3
        pdf.set_font("Nanum" if FONT_PATH else "Arial","",11)
        for i, d in enumerate(docs):
            pdf.cell(65, 6, f"[ ] {d}")
            if (i+1) % per_line == 0: pdf.ln(6)
        pdf.ln(8)
    else:
        pdf.p("확인된 서류 없음")
    pdf.ln(1)

    # === 중간내용 (브라켓) 종료 ===
    pdf.end_bracket(y0, label="중간내용")

    # 근거 요약 박스
    pdf.ln(1)
    pdf.h2("근거 · 첨부 요약")
    yb = pdf.begin_box()
    for s in (payload.get("sources") or [])[:3]:
        title = s.get("clause_title","문서"); score = s.get("score")
        pdf.set_font("Nanum" if FONT_PATH else "Arial","B",11)
        tail = f" (score={score:.4f})" if isinstance(score,(int,float)) else ""
        pdf.cell(0,6, f"- {title}{tail}", ln=1)
        pdf.set_font("Nanum" if FONT_PATH else "Arial","",10)
        snip = (s.get("content","") or "").replace("\\n"," ").replace("\n"," ")
        if len(snip) > 400: snip = snip[:400] + "…"
        pdf.p(snip); pdf.ln(1)
    if not (payload.get("sources") or []):
        pdf.p("근거가 제공되지 않았습니다.")
    pdf.end_box(yb, title="근거 · 첨부 요약")

    # 링크 (선택)
    links = payload.get("links") or {}
    if links:
        pdf.ln(2)
        pdf.h2("링크")
        for k,v in links.items(): pdf.p(f"- {k}: {v}")

    # 하단 푸터: 문의 + QR
    pdf.ln(3)
    pdf.set_draw_color(0,0,0); pdf.set_line_width(0.6)
    x1 = pdf.l_margin; x2 = pdf.w - pdf.r_margin
    y = pdf.get_y()
    pdf.line(x1, y, x2, y)
    pdf.ln(2)

    contact = payload.get("contact", {})
    msg = f"문의: {contact.get('name','-')} · {contact.get('org','')} · {contact.get('email','')} · {contact.get('phone','')}"
    pdf.set_font("Nanum" if FONT_PATH else "Arial","",10)
    left_y = pdf.get_y()
    pdf.multi_cell(0, 5, msg)
    right_x = pdf.w - pdf.r_margin - 30  # QR width ~26
    # QR
    qr_path = _qr_tempfile(payload.get("qr_url",""))
    if qr_path:
        # place QR at right
        cur_y = left_y
        pdf.image(qr_path, x=right_x, y=cur_y, w=26, h=26)
        try:
            os.remove(qr_path)
        except Exception:
            pass

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)
