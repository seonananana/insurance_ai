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

@app.post("/export/pdf")
def export_pdf(payload: PdfPayload):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    x, y = 40, height - 50
    c.setTitle(payload.title)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, payload.title)
    y -= 24
    c.setFont("Helvetica", 11)
    for line in payload.content.splitlines() or ["(빈 문서)"]:
        for w in wrap(line, 90):
            c.drawString(x, y, w)
            y -= 16
            if y < 40:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - 50
    c.save()
    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="answer.pdf"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)
