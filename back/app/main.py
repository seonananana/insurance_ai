import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

from app.routers import health, qa

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")  # ex) postgresql+psycopg2://insurance:insurance_pw@localhost:5432/insurance_ai
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 환경변수가 필요합니다.")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="Insurance RAG API", version="0.2.0")

FRONT_ORIGINS = [
    "http://localhost:8501",  # 로컬 Streamlit
    # "https://<YOUR-STREAMLIT-APP>.streamlit.app",  # 배포 후 추가
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONT_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(qa.router,     prefix="/qa",     tags=["qa"])

@app.get("/")
def root():
    return {"ok": True, "service": "Insurance RAG API"}
