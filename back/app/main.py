# back/app/main.py
# FastAPI 앱 초기화 + CORS + 라우터 등록(health, qa, chat, report, chatlog)

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import health, qa, chat

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

if chatlog is not None:
    app.include_router(chatlog.router)                                 # chatlog.py 내부 prefix="/chat"
if report is not None:
    app.include_router(report.router)                                  # report.py 내부 prefix="/qa"

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}