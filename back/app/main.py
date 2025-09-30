백엔드(RAG기술 포함)

import os
import math
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import numpy as np
import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openai import OpenAI

# ===== OpenAI =====
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
EMBED_MODEL = "text-embedding-3-small"
GEN_MODEL   = "gpt-4o-mini"

# ===== 공용 =====
def cos_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb + 1e-12)

@dataclass
class DocChunk:
    id: int
    text: str
    url: str
    embedding: Optional[List[float]] = None
    title: Optional[str] = None

# ===== Repo 인터페이스 =====
class Repo:
    # chat
    def save_message(self, session_id: str, role: str, content: str) -> int: ...
    def get_recent_messages(self, session_id: str, limit: int = 20) -> List[Dict]: ...
    # docs (RAG)
    def add_documents(self, docs: List[DocChunk]) -> None: ...
    def fulltext_candidates(self, query: str, limit: int = 200) -> List[DocChunk]: ...
    def upsert_embedding(self, doc_id: int, vec: List[float]) -> None: ...
    def get_doc_by_ids(self, ids: List[int]) -> List[DocChunk]: ...

# ===== MySQLRepo =====
class MySQLRepo(Repo):
    def __init__(self):
        self.conn_args = dict(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DB", "rag"),
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.Cursor,
        )
        with pymysql.connect(**self.conn_args) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
            conn.commit()

    # --- util ---
    def _get_or_create_conversation(self, session_id: str) -> int:
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO conversations (title) VALUES (%s);",
                (session_id,)
            )
            cur.execute("SELECT id FROM conversations WHERE title=%s;", (session_id,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise RuntimeError("conversation upsert failed")
            conv_id = int(row[0])
            cur.execute(
                "UPDATE conversations SET last_active_at=CURRENT_TIMESTAMP WHERE id=%s;",
                (conv_id,)
            )
            conn.commit()
            return conv_id

    # --- chat ---
    def save_message(self, session_id: str, role: str, content: str) -> int:
        conv_id = self._get_or_create_conversation(session_id)
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s,%s,%s);",
                (conv_id, role, content)
            )
            mid = cur.lastrowid
            conn.commit()
            return int(mid)

    def get_recent_messages(self, session_id: str, limit: int = 20) -> List[Dict]:
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM conversations WHERE title=%s;", (session_id,))
            row = cur.fetchone()
            if not row:
                return []
            conv_id = int(row[0])
            cur.execute(
                "SELECT role, content, UNIX_TIMESTAMP(created_at) "
                "FROM messages WHERE conversation_id=%s "
                "ORDER BY id DESC LIMIT %s;",
                (conv_id, limit)
            )
            rows = cur.fetchall()
        return [{"role": r, "content": c, "ts": float(ts)} for (r, c, ts) in rows][::-1]

    # --- docs (RAG) ---
    def add_documents(self, docs: List[DocChunk]) -> None:
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            for d in docs:
                cur.execute(
                    "INSERT INTO documents (id, title, url, text) VALUES (%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE title=VALUES(title), url=VALUES(url), text=VALUES(text);",
                    (d.id, d.title, d.url, d.text)
                )
            conn.commit()

    def fulltext_candidates(self, query: str, limit: int = 200) -> List[DocChunk]:
        like = f"%{query}%"
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            # LIKE 기반 (원하면 FULLTEXT로 교체 가능)
            cur.execute(
                "SELECT id, title, url, text, embedding FROM documents "
                "WHERE text LIKE %s LIMIT %s;",
                (like, limit)
            )
            rows = cur.fetchall()
        out: List[DocChunk] = []
        for doc_id, title, url, text, emb in rows:
            vec = None
            if emb is not None:
                vec = np.frombuffer(emb, dtype="float32").tolist()
            out.append(DocChunk(id=int(doc_id), text=text or "", url=url or "", embedding=vec, title=title))
        return out

    def upsert_embedding(self, doc_id: int, vec: List[float]) -> None:
        data = np.array(vec, dtype="float32").tobytes()
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            cur.execute("UPDATE documents SET embedding=%s WHERE id=%s;", (data, doc_id))
            conn.commit()

    def get_doc_by_ids(self, ids: List[int]) -> List[DocChunk]:
        if not ids:
            return []
        qmarks = ",".join(["%s"] * len(ids))
        with pymysql.connect(**self.conn_args) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT id, title, url, text, embedding FROM documents WHERE id IN ({qmarks});",
                tuple(ids)
            )
            rows = cur.fetchall()
        out: List[DocChunk] = []
        for doc_id, title, url, text, emb in rows:
            vec = None
            if emb is not None:
                vec = np.frombuffer(emb, dtype="float32").tolist()
            out.append(DocChunk(id=int(doc_id), text=text or "", url=url or "", embedding=vec, title=title))
        return out

repo: Repo = MySQLRepo()

# ===== 스키마 =====
class ChatRequest(BaseModel):
    session_id: str
    message: str
    top_k: int = 5           # 문서 근거 상위 K
    max_context: int = 8     # 최근 대화 맥락

class ChatResponse(BaseModel):
    answer: str
    evidence: List[Dict]

class IngestItem(BaseModel):
    id: int
    text: str
    title: Optional[str] = None
    url: Optional[str] = None

class IngestRequest(BaseModel):
    items: List[IngestItem]

# ===== RAG 로직 =====
def embed_texts(texts: List[str]) -> List[List[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]

def ensure_doc_embeddings(docs: List[DocChunk]) -> None:
    to_embed = [d for d in docs if d.embedding is None]
    if not to_embed:
        return
    vecs = embed_texts([d.text for d in to_embed])
    for d, v in zip(to_embed, vecs):
        repo.upsert_embedding(d.id, v)
        d.embedding = v

def retrieve_with_rerank(user_query: str, top_k: int = 5) -> Tuple[List[DocChunk], List[float]]:
    cands = repo.fulltext_candidates(user_query, limit=200)
    if not cands:
        return [], []
    ensure_doc_embeddings(cands)
    qvec = embed_texts([user_query])[0]
    scored: List[Tuple[float, DocChunk]] = []
    for d in cands:
        if d.embedding is None:
            continue
        s = cos_sim(qvec, d.embedding)
        scored.append((s, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [d for s, d in scored[:top_k]]
    sims = [float(s) for s, d in scored[:top_k]]
    return top, sims

def build_prompt(user_query: str, chunks: List[DocChunk]) -> str:
    numbered = []
    for i, d in enumerate(chunks, 1):
        snippet = (d.text or "")[:400]
        numbered.append(f"[{i}] {snippet}\n(URL: {d.url})")
    context = "\n\n".join(numbered) if numbered else "No context."
    return f"""너는 보험/대출 약관 어시스턴트야.
다음 '근거'만 사용해서 한국어로 정확하고 간결하게 답해. 본문에 [번호]로 근거 표시.
근거:
{context}

질문: {user_query}"""

def generate_answer(prompt: str) -> str:
    resp = client.responses.create(model=GEN_MODEL, input=prompt)
    return resp.output_text

def generate_chat_with_history(session_id: str, user_message: str, max_context: int) -> str:
    # 근거 없을 때 대비한 일반 대화(백업 경로)
    history = repo.get_recent_messages(session_id, limit=max_context)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": user_message})
    # 시스템 프롬프트
    system = {"role": "system", "content": "You are a helpful Korean assistant. Be accurate and concise."}
    messages = [system] + messages
    chat = client.chat.completions.create(model=GEN_MODEL, messages=messages, temperature=0.2)
    return chat.choices[0].message.content.strip()

# ===== FastAPI =====
app = FastAPI(title="RAG Chat Backend (MySQL)")

@app.post("/ingest")
def ingest(req: IngestRequest):
    docs = [DocChunk(id=i.id, text=i.text, title=i.title, url=i.url or "") for i in req.items]
    repo.add_documents(docs)
    return {"added": len(docs)}

@app.post("/seed_demo")
def seed_demo():
    demo = [
        DocChunk(1, "대물배상은 피보험자가 타인의 재물에 손해를 끼친 경우 보상합니다.", "https://example.com/policy#property", title="대물배상"),
        DocChunk(2, "자기차량손해 담보는 피보험차량의 손해를 약관에 따라 보상합니다.", "https://example.com/policy#own-damage", title="자기차량손해"),
        DocChunk(3, "면책사유: 고의, 무면허, 음주운전 등은 보상하지 않습니다.", "https://example.com/policy#exclusion", title="면책사유"),
    ]
    repo.add_documents(demo)
    return {"ok": True, "seeded": len(demo)}

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # 1) 사용자 메시지 저장
    repo.save_message(req.session_id, "user", req.message)

    # 2) RAG: 검색 → 임베딩 재랭크
    chunks, sims = retrieve_with_rerank(req.message, top_k=req.top_k)

    if not chunks:
        # 근거 없으면 일반 챗으로 백업
        answer = generate_chat_with_history(req.session_id, req.message, req.max_context)
        repo.save_message(req.session_id, "assistant", answer)
        return ChatResponse(answer=answer, evidence=[])

    # 3) 생성
    prompt = build_prompt(req.message, chunks)
    answer = generate_answer(prompt)

    # 4) 어시스턴트 메시지 저장
    repo.save_message(req.session_id, "assistant", answer)

    # 5) 증거 패키징
    evidence = [
        {"id": d.id, "title": d.title, "url": d.url, "snippet": d.text[:160], "score": sims[i]}
        for i, d in enumerate(chunks)
    ]
    return ChatResponse(answer=answer, evidence=evidence)

@app.get("/history")
def history(session_id: str, limit: int = 50):
    return JSONResponse({"messages": repo.get_recent_messages(session_id, limit)})

@app.get("/healthz")
def healthz():
    return {"ok": True}
