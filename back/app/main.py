# back/app/main.py
# FastAPI 앱 초기화 + CORS + 라우터 등록(health, qa, chat, report, chatlog)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # ← 정적 PDF 서빙
from app.routers import health, qa, chat     # 기존 라우터
# 아래 두 개는 파일이 이미 있으면 import, 없으면 나중에 추가
try:
    from app.routers import report          # /qa/answer_pdf
except Exception:
    report = None
try:
    from app.routers import chatlog         # /chat/log
except Exception:
    chatlog = None

app = FastAPI(title="Insurance RAG API", version="0.3.0")

# 로컬 개발용 CORS (Streamlit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # 배포 시 Streamlit 앱 URL 추가
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PDF/정적 파일 서빙
app.mount("/files", StaticFiles(directory="files"), name="files")

# 라우터
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(qa.router,     prefix="/qa",     tags=["qa"])
app.include_router(chat.router,   prefix="/chat",   tags=["chat"])

# 선택 라우터(존재할 때만 등록)
if chatlog is not None:
    app.include_router(chatlog.router, prefix="/chat", tags=["chat"])
if report is not None:
    app.include_router(report.router,  prefix="/qa",   tags=["qa"])

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}
