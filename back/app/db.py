# app/db.py
# -----------------------------------------------------------------------------
# 기능: DB 연결/세션 관리 (SQLAlchemy + psycopg2)
#  - 엔진/세션 팩토리 정의
#  - FastAPI 의존성: get_db()
#  - .env(로컬) 또는 배포 환경변수에서 DATABASE_URL 읽음
# -----------------------------------------------------------------------------
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()  # 로컬 개발 시 .env 로드 (배포에선 환경변수 우선)

DATABASE_URL = os.getenv("DATABASE_URL")  # ex) postgresql+psycopg2://user:pw@host:5432/db
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
