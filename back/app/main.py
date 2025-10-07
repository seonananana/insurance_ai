# app/main.py
# -----------------------------------------------------------------------------
# 기능: FastAPI 앱 초기화 + CORS + 라우터 등록
#  - 순환임포트 방지를 위해 DB 의존성은 app/db.py로 분리
# -----------------------------------------------------------------------------
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import health, qa  # 라우터만 임포트

app = FastAPI(title="Insurance RAG API", version="0.2.1")

FRONT_ORIGINS = [
    "http://localhost:8501",  # 로컬 Streamlit
    # "https://<your-streamlit>.streamlit.app",  # 배포 후 추가
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONT_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(qa.router,     prefix="/qa",     tags=["qa"])

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}
