#FastAPI 앱 초기화, 라우터 등록, DB 풀(psycopg async) 라이프사이클 관리.
#환경변수(OPENAI_API_KEY, DATABASE_URL)를 읽어 서비스에 주입.

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg
from psycopg_pool import AsyncConnectionPool

from app.routers import qa, health
from dotenv import load_dotenv

app = FastAPI(title="Claims Assistant API", version="0.1.0")

# CORS: 필요 시 도메인 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/claims")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 전역 풀(비동기)
pool: AsyncConnectionPool | None = None

@app.on_event("startup")
async def on_startup():
    global pool
    # psycopg v3 풀 – FastAPI에서 공유
    pool = AsyncConnectionPool(DATABASE_URL.replace("+psycopg", ""), open=True, min_size=1, max_size=5)  # DSN 정규화

    # 간단 연결 테스트
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")

    # 라우터가 풀/키에 접근할 수 있도록 상태에 저장
    app.state.db_pool = pool
    app.state.openai_api_key = OPENAI_API_KEY

@app.on_event("shutdown")
async def on_shutdown():
    if pool:
        await pool.close()

# 라우터 등록
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(qa.router, prefix="/qa", tags=["qa"])

# 루트
@app.get("/")
async def root():
    return {"ok": True, "service": "Claims Assistant API"}
