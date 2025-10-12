# app/main.py
# FastAPI 앱 초기화 + CORS + 라우터 등록(health, qa)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import health, qa, chat  # get_db는 import 안 함(순환 방지)

app = FastAPI(title="Insurance RAG API", version="0.2.2")

# 로컬 개발용 CORS (Streamlit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # 배포 시 Streamlit 앱 URL 추가
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(qa.router,     prefix="/qa",     tags=["qa"])
app.include_router(chat.router,   prefix="/chat",   tags=["chat"])

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}
