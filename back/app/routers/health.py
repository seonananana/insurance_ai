#서비스 가용성/DB 연결 확인용 헬스체크 엔드포인트.

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.main import get_db

router = APIRouter()

@router.get("/")
def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": True}
    except Exception as e:
        return {"ok": True, "db": False, "error": str(e)}
