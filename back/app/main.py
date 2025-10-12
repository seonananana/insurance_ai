# back/app/main.py
# FastAPI 앱 초기화 + CORS + 라우터 등록(health, qa, chat, report, chatlog)
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import health, qa, chat

# 선택 라우터들: 모듈 없으면 건너뜀
try:
    from app.routers import report          # /qa/answer_pdf (내부에서 prefix 선언돼 있다고 가정)
except Exception:
    report = None
try:
    from app.routers import chatlog         # /chat/log (내부에서 prefix 선언돼 있다고 가정)
except Exception:
    chatlog = None

app = FastAPI(title="Insurance RAG API", version="0.3.0")

# ===== 정적 파일 기본 경로(폴더는 생성하지 않음) =====
BASE_DIR = Path(__file__).resolve().parent.parent  # back/app -> back
FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "files")).resolve()

# 폴더가 없어도 앱이 뜨도록 check_dir=False
app.mount("/files", StaticFiles(directory=str(FILES_DIR), check_dir=False), name="files")

# ===== CORS (Streamlit 로컬 개발 기본값) =====
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

# ===== 라우터 등록 =====
# ⚠️ qa/chat 라우터 파일 내부에 이미 prefix가 선언돼 있다면 여기서 prefix를 또 주지 마!
#    (중복되면 /qa/qa/..., /chat/chat/... 이 되어 404 발생)
app.include_router(health.router, prefix="/health", tags=["health"])  # health에 내부 prefix가 없다면 이대로 사용
app.include_router(qa.router)     # 내부에서 prefix="/qa" 라면 여기서는 prefix 주지 않음
app.include_router(chat.router)   # 내부에서 prefix="/chat" 라면 여기서는 prefix 주지 않음
if chatlog is not None:
    app.include_router(chatlog.router)
if report is not None:
    app.include_router(report.router)

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}
