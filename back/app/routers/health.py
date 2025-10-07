# /health: DB 연결 확인 (SELECT 1)
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db

router = APIRouter()

@router.get("/")
def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": True}
    except Exception as e:
        return {"ok": True, "db": False, "error": str(e)}
