# app/routers/health.py
# -----------------------------------------------------------------------------
# 기능: 헬스 체크 엔드포인트 (/health)
#  - DB 연결 확인 (SELECT 1)
# -----------------------------------------------------------------------------
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db  # <-- main에서 가져오던 걸 db 모듈로 변경

router = APIRouter()

@router.get("/")
def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": True}
    except Exception as e:
        return {"ok": True, "db": False, "error": str(e)}
