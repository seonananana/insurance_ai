# back/app/routers/health.py
from fastapi import APIRouter
import os

router = APIRouter(tags=["health"])

def _llm_ok() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))

@router.get("/health", include_in_schema=False)
@router.get("/health/", include_in_schema=False)
def health():
    # TODO: DB ping이 필요하면 여기에서 간단 쿼리 수행 후 db_ok 업데이트
    return {"ok": True, "llm_ok": _llm_ok(), "db_ok": True}
