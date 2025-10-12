# app/services/pdf_report.py
import os, textwrap
from fpdf import FPDF

# 한글 폰트 경로 (없으면 기본 영문 폰트로 진행)
FONT_PATH = os.getenv("KOREAN_FONT_TTF", "").strip()

class ReportPDF(FPDF):
    def header(self):
        self.set_font("Nanum" if FONT_PATH else "Arial", "B", 14)
        self.cell(0, 8, "보험 문서 RAG 답변", ln=1)
        self.ln(2)

    def h2(self, text):
        self.set_font("Nanum" if FONT_PATH else "Arial", "B", 12)
        self.cell(0, 7, text, ln=1)
        self.set_draw_color(200,200,200)
        self.line(self.l_margin, self.get_y(), 210-self.r_margin, self.get_y())
        self.ln(2)

    def p(self, text, size=11):
        self.set_font("Nanum" if FONT_PATH else "Arial", "", size)
        for line in textwrap.wrap(text or "-", 80):
            self.cell(0, 6, line, ln=1)

def _ensure_fonts(pdf: FPDF):
    if FONT_PATH:
        try:
            pdf.add_font("Nanum","", FONT_PATH, uni=True)
            pdf.add_font("Nanum","B", FONT_PATH, uni=True)
        except Exception:
            pass  # 폰트 등록 실패 시 기본 폰트로 fallback

def build_pdf(payload: dict, out_path: str):
    pdf = ReportPDF()
    _ensure_fonts(pdf)
    pdf.add_page()

    meta = f"보험사: {payload.get('policy_type','-')}  |  Top-K: {payload.get('top_k','-')}  |  conv_id: {payload.get('conv_id','-')}"
    pdf.set_font("Nanum" if FONT_PATH else "Arial","",10); pdf.cell(0,5,meta,ln=1); pdf.ln(2)

    pdf.h2("요약"); pdf.p(payload.get("summary","-")); pdf.ln(2)

    fitness = payload.get("fitness","check")
    badge = {"ok":"✅ 적합","check":"⚠️ 확인 필요","lack":"❌ 근거 부족"}.get(fitness, "⚠️ 확인 필요")
    conf  = int(payload.get("confidence",0))
    reason= payload.get("fitness_reason","-")
    pdf.h2("적합성 판단")
    pdf.p(f"{badge}  |  확신도 {conf}%"); pdf.p(f"사유: {reason}"); pdf.ln(2)

    pdf.h2("다음 단계 · 타임라인")
    steps = payload.get("timeline") or []
    if steps:
        for s in steps: pdf.p(f"• {s}")
    else:
        pdf.p("제공된 타임라인이 없습니다.")
    pdf.ln(2)

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

    pdf.h2("근거 요약")
    for s in (payload.get("sources") or [])[:3]:
        title = s.get("clause_title","문서"); score = s.get("score")
        pdf.set_font("Nanum" if FONT_PATH else "Arial","B",11)
        pdf.cell(0,6, f"- {title}" + (f" (score={score:.4f})" if isinstance(score,(int,float)) else ""), ln=1)
        pdf.set_font("Nanum" if FONT_PATH else "Arial","",10)
        snip = (s.get("content","") or "").replace("\n"," ")
        if len(snip) > 400: snip = snip[:400] + "…"
        pdf.p(snip); pdf.ln(1)

    links = payload.get("links") or {}
    if links:
        pdf.h2("링크")
        for k,v in links.items(): pdf.p(f"- {k}: {v}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)
