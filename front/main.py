# main.py
from __future__ import annotations
import os, time, uuid, io
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTasks

# ===== OpenAI (v1 스타일 클라이언트) =====
# pip install openai>=1.0.0
try:
    from openai import OpenAI
    _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except Exception:
    _openai_client = None  # 키 없을 때도 서버는 뜨게

app = FastAPI(title="Insurance RAG Platform API", version="0.1.0")

# CORS (필요 시 도메인 제한)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 운영 시 특정 도메인만
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# 임시 인메모리 저장소 (데모용). 운영 시 PostgreSQL + pgvector로 교체
# =========================================================
_DOCS: Dict[str, Dict[str, Any]] = {}           # 문서 메타/본문 {doc_id: {...}}
_CHUNKS: List[Dict[str, Any]] = []              # 청크 벡터 색인 더미
_FAQ: List[Dict[str, str]] = []                 # FAQ 목록
_QA_HISTORY: Dict[str, List[Dict[str, Any]]] = {}  # 사용자별 Q&A 기록
_USERS: Dict[str, Dict[str, Any]] = {}          # (선택) 간단한 사용자 관리 더미

# =========================================================
# 공용 모델
# =========================================================
class AskRequest(BaseModel):
    user_id: str = Field(..., description="임시 사용자 식별자")
    question: str

class AskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []
    latency_ms: int

class SearchRequest(BaseModel):
    q: str
    top_k: int = 5
    filter_insurance_type: Optional[str] = Field(None, description="자동차/실손/화재 등")

class DocMeta(BaseModel):
    doc_id: str
    title: str
    insurance_type: Optional[str] = None
    filename: Optional[str] = None
    uploaded_at: float

class DocDetail(DocMeta):
    text_preview: str

class FAQItem(BaseModel):
    question: str
    answer: str

class ClaimGuideRequest(BaseModel):
    insurance_type: str  # 예: "자동차" | "실손" | "화재"
    scenario: Optional[str] = Field(
        None, description="상황 설명(입원, 접촉사고, 화재피해 등)"
    )
    user_inputs: Optional[Dict[str, Any]] = None  # 날짜, 병원명, 진료유형 등

class ClaimGuideResponse(BaseModel):
    title: str
    html: str
    checklist: List[str] = []
    suggested_docs: List[str] = []  # 예: 진료비세부내역서, 화재사실확인서 등

class HistoryItem(BaseModel):
    at: float
    question: str
    answer: str
    sources: List[Dict[str, Any]]

# =========================================================
# 유틸 (여기서 pgvector 연동 포인트 표시)
# =========================================================
def _ensure_openai():
    if _openai_client is None:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY 미설정")

def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    TODO(운영): OpenAI Embeddings → pgvector 저장
      - 테이블 예시: document_chunks(id uuid, doc_id uuid, page int, text text, vec vector(1536), insurance_type text, created_at timestamptz)
      - SQL 삽입: INSERT INTO document_chunks (...) VALUES (..., to_vector($embedding));
    데모: 임시로 0 벡터 반환
    """
    return [[0.0] * 8 for _ in texts]  # 데모용 축소 벡터

def vector_search(query: str, top_k: int = 5, insurance_type: Optional[str] = None):
    """
    TODO(운영): pgvector에서 cosine_distance/inner_product로 top_k 검색
      SELECT * FROM document_chunks
      WHERE ($1::text IS NULL OR insurance_type = $1)
      ORDER BY vec <=> to_vector($query_embedding)
      LIMIT $top_k;
    데모: 단순 키워드 점수로 흉내
    """
    q = query.lower()
    scored = []
    for ch in _CHUNKS:
        if insurance_type and ch.get("insurance_type") != insurance_type:
            continue
        text = ch["text"]
        score = text.lower().count(q)  # 매우 단순한 더미 점수
        if score > 0:
            scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]

def cite_block(sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return ""
    items = []
    for s in sources:
        title = s.get("title") or s.get("doc_id", "")[:8]
        page = s.get("page")
        ref = f"{title}" + (f" p.{page}" if page is not None else "")
        items.append(f"- {ref}")
    return "\n\n참고 근거:\n" + "\n".join(items)

# =========================================================
# 헬스체크 / 기본
# =========================================================
@app.get("/health")
def health():
    return {"ok": True, "docs": len(_DOCS), "chunks": len(_CHUNKS), "faq": len(_FAQ)}

# =========================================================
# 1) Q&A 챗봇 (핵심)
# =========================================================
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    start = time.time()
    # 1) 검색 (pgvector 연동 포인트)
    hits = vector_search(req.question, top_k=6, insurance_type=None)
    sources = []
    context_snippets = []
    for h in hits:
        sources.append({
            "doc_id": h["doc_id"],
            "title": _DOCS.get(h["doc_id"], {}).get("title"),
            "page": h.get("page"),
            "score": h.get("score", 1.0)
        })
        context_snippets.append(h["text"].strip())

    # 2) 프롬프트 구성
    system_prompt = (
        "너는 보험 문서(약관, 요약서, 청구안내, 필수서류)에 근거해 답하는 어시스턴트다. "
        "출처가 없으면 추측하지 말고 모른다고 답해. "
        "간결하지만 정확하게 설명하고, 조항/서류명이 나오면 그대로 적어줘."
    )
    context_blob = "\n\n--- 문서 발췌 ---\n" + "\n\n".join(context_snippets) if context_snippets else ""
    user_prompt = f"질문: {req.question}\n{context_blob}"

    # 3) OpenAI 호출
    answer_text = ""
    if _openai_client:
        try:
            resp = _openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            answer_text = resp.choices[0].message.content.strip()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OpenAI 호출 실패: {e}")
    else:
        # 데모: OpenAI 미연결 시, 문서 발췌 반환
        answer_text = "※ 데모 모드: 벡터 검색 발췌를 반환합니다.\n\n" + "\n\n".join(context_snippets[:2])

    # 4) 출처 블록 꼬리표
    answer_with_cites = answer_text + ("\n\n" + cite_block(sources) if sources else "")

    # 5) 히스토리 기록
    _QA_HISTORY.setdefault(req.user_id, []).append({
        "at": time.time(),
        "question": req.question,
        "answer": answer_with_cites,
        "sources": sources
    })

    return AskResponse(
        answer=answer_with_cites,
        sources=sources,
        latency_ms=int((time.time() - start) * 1000)
    )

# =========================================================
# 2) 문서 업로드/관리 (관리자용)
# =========================================================
@app.post("/admin/docs/upload", response_model=DocMeta)
async def upload_doc(
    file: UploadFile = File(...),
    title: str = Form(...),
    insurance_type: Optional[str] = Form(None)
):
    """
    운영 계획:
      1) PDF 텍스트 추출 → 청크 분할
      2) 임베딩 생성 → pgvector 저장
      3) 원본 파일은 오브젝트 스토리지/DB에 메타와 함께 저장
    """
    if not file.filename.lower().endswith((".pdf", ".txt", ".md")):
        raise HTTPException(status_code=400, detail="지원 형식: .pdf/.txt/.md")

    content_bytes = await file.read()
    text = ""
    if file.filename.lower().endswith(".pdf"):
        # TODO: pdfminer.six 등으로 텍스트 추출
        # from pdfminer.high_level import extract_text; text = extract_text(BytesIO(content_bytes))
        text = f"(PDF 텍스트 추출 필요) 파일 크기 {len(content_bytes)} bytes"
    else:
        text = content_bytes.decode("utf-8", errors="ignore")

    doc_id = str(uuid.uuid4())
    _DOCS[doc_id] = {
        "doc_id": doc_id,
        "title": title,
        "insurance_type": insurance_type,
        "filename": file.filename,
        "uploaded_at": time.time(),
        "text": text,
    }

    # 청크 분할 (데모: 거칠게 줄 단위)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks = []
    chunk_size = 8  # 운영 시 토큰 기준 분할 권장
    for i in range(0, len(lines), chunk_size):
        chunk_text = "\n".join(lines[i:i+chunk_size])[:2000]
        chunks.append({
            "id": str(uuid.uuid4()),
            "doc_id": doc_id,
            "page": None,  # PDF이면 페이지 매핑
            "text": chunk_text,
            "insurance_type": insurance_type,
        })
    # 임베딩 (데모)
    embs = embed_texts([c["text"] for c in chunks])
    for c, e in zip(chunks, embs):
        c["vec"] = e
    _CHUNKS.extend(chunks)

    return DocMeta(
        doc_id=doc_id,
        title=title,
        insurance_type=insurance_type,
        filename=file.filename,
        uploaded_at=_DOCS[doc_id]["uploaded_at"]
    )

@app.get("/docs", response_model=List[DocDetail])
def list_docs(insurance_type: Optional[str] = None, q: Optional[str] = None, limit: int = 50, offset: int = 0):
    items = list(_DOCS.values())
    if insurance_type:
        items = [d for d in items if d.get("insurance_type") == insurance_type]
    if q:
        items = [d for d in items if q.lower() in (d.get("title","")+d.get("text","")).lower()]
    slice_ = items[offset: offset+limit]
    return [
        DocDetail(
            doc_id=d["doc_id"],
            title=d["title"],
            insurance_type=d.get("insurance_type"),
            filename=d.get("filename"),
            uploaded_at=d["uploaded_at"],
            text_preview=(d.get("text","")[:300] + ("…" if len(d.get("text",""))>300 else ""))
        )
        for d in slice_
    ]

@app.get("/docs/{doc_id}", response_model=DocDetail)
def get_doc(doc_id: str):
    d = _DOCS.get(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없음")
    return DocDetail(
        doc_id=d["doc_id"],
        title=d["title"],
        insurance_type=d.get("insurance_type"),
        filename=d.get("filename"),
        uploaded_at=d["uploaded_at"],
        text_preview=(d.get("text","")[:2000])
    )

# =========================================================
# 3) 문서 검색 (카테고리/키워드)
# =========================================================
@app.post("/search", response_model=List[Dict[str, Any]])
def search_docs(req: SearchRequest):
    hits = vector_search(req.q, top_k=req.top_k, insurance_type=req.filter_insurance_type)
    # 반환 필드: doc_id, title, page, snippet
    results = []
    for h in hits:
        doc = _DOCS.get(h["doc_id"], {})
        text = h["text"]
        snippet = text[:240] + ("…" if len(text) > 240 else "")
        results.append({
            "doc_id": h["doc_id"],
            "title": doc.get("title"),
            "page": h.get("page"),
            "insurance_type": doc.get("insurance_type"),
            "snippet": snippet
        })
    return results

# =========================================================
# 4) 청구 가이드 (PDF 대신 HTML/체크리스트 제공 — 프론트에서 PDF로 변환)
# =========================================================
@app.post("/claims/guide", response_model=ClaimGuideResponse)
def build_claim_guide(req: ClaimGuideRequest):
    # 기본 체크리스트/필수서류 (예시 — 운영 시 테이블/정책화)
    base_checklists = {
        "자동차": ["사고일시/장소 확인", "가해/피해 차량 정보", "경찰사고확인원", "수리내역/견적서", "렌트/휴차료 영수증(해당 시)"],
        "실손": ["진료비 영수증", "진료비 세부내역서", "처방전/약국 영수증", "입·퇴원 확인서(해당 시)"],
        "화재": ["화재사실확인서(소방서)", "피해사진", "수리견적서/감정서", "임시거주비 영수증(해당 시)"]
    }
    suggested = base_checklists.get(req.insurance_type, [])

    # 간단한 HTML 템플릿 (운영 시 Jinja2 권장)
    html = f"""
    <h2>[{req.insurance_type}] 보험금 청구 가이드</h2>
    <p><strong>상황:</strong> {req.scenario or "미입력"}</p>
    <h3>절차</h3>
    <ol>
      <li>필수 서류 준비</li>
      <li>보험사 고객센터/앱에서 접수</li>
      <li>심사 진행 및 추가서류 요청 대응</li>
      <li>지급 결정 및 이의신청 절차(필요 시)</li>
    </ol>
    <h3>체크리스트</h3>
    <ul>
      {"".join(f"<li>{x}</li>" for x in suggested)}
    </ul>
    <p><em>참고: 세부 규정은 약관과 요약서를 확인하세요. Q&A 페이지에서 항목별로 질문하면 관련 조항을 근거로 안내해드립니다.</em></p>
    """.strip()

    return ClaimGuideResponse(
        title=f"{req.insurance_type} 보험 청구 가이드",
        html=html,
        checklist=suggested,
        suggested_docs=suggested
    )

# =========================================================
# 5) FAQ
# =========================================================
@app.get("/faq", response_model=List[FAQItem])
def list_faq():
    return [FAQItem(**item) for item in _FAQ]

@app.post("/admin/faq", response_model=FAQItem)
def add_faq(item: FAQItem):
    _FAQ.append(item.model_dump())
    return item

# =========================================================
# 6) 히스토리 (마이페이지)
# =========================================================
@app.get("/me/history", response_model=List[HistoryItem])
def my_history(user_id: str = Query(...)):
    items = _QA_HISTORY.get(user_id, [])
    return [HistoryItem(**it) for it in items]

# =========================================================
# 7) (옵션) 간단 회원 등록/로그인 더미
# =========================================================
class SignUpReq(BaseModel):
    user_id: str
    nickname: Optional[str] = None

@app.post("/auth/signup")
def signup(req: SignUpReq):
    _USERS[req.user_id] = {"user_id": req.user_id, "nickname": req.nickname, "created_at": time.time()}
    _QA_HISTORY.setdefault(req.user_id, [])
    return {"ok": True}

# =========================================================
# 8) 원본 문서 다운로드(데모: 원문 텍스트를 txt로 제공)
# =========================================================
@app.get("/docs/{doc_id}/download")
def download_doc(doc_id: str):
    d = _DOCS.get(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없음")
    content = d.get("text","")
    buf = io.BytesIO(content.encode("utf-8"))
    return StreamingResponse(buf, media_type="text/plain", headers={
        "Content-Disposition": f'attachment; filename="{d.get("title","document")}.txt"'
    })
