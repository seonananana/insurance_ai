#서비스 가용성/DB 연결 확인용 헬스체크 엔드포인트.

from fastapi import APIRouter, Request

router = APIRouter()

@router.get("")
async def health(req: Request):
    ok_db = False
    try:
        pool = req.app.state.db_pool
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        ok_db = True
    except Exception:
        ok_db = False
    return {"ok": True, "db": ok_db}
