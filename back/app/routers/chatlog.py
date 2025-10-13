# app/routers/chatlog.py
from __future__ import annotations
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db

router = APIRouter(prefix="/chat", tags=["chat"])

class Msg(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str

class ChatLogRequest(BaseModel):
    conv_id: Optional[str] = None
    message: Msg

class ChatLogResponse(BaseModel):
    conv_id: str
    ok: bool = True

@router.post("/log", response_model=ChatLogResponse)
def log_message(req: ChatLogRequest, db: Session = Depends(get_db)):
    try:
        conv_id = req.conv_id or str(uuid.uuid4())
        if req.conv_id is None:
            db.execute(text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conv_id})
        db.execute(
            text("""INSERT INTO messages (conv_id, role, content)
                    VALUES (:cid, :role, :content)"""),
            {"cid": conv_id, "role": req.message.role, "content": req.message.content},
        )
        db.commit()
        return ChatLogResponse(conv_id=conv_id)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"chat log failed: {e}")