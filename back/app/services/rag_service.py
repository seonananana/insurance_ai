# back/app/services/rag_service.py
from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Optional

import faiss
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader

# ====== 경로/모델 설정 ======
# 프로젝트 루트(back) 기준: back/files/pdfs 를 기본으로 사용
BASE_DIR = Path(__file__).resolve().parents[2]   # back/
FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "files")).resolve()
PDF_DIR   = Path(os.getenv("PDF_DIR",   FILES_DIR / "pdfs")).resolve()
INDEX_DIR = Path(os.getenv("INDEX_DIR", FILES_DIR / "indices")).resolve()
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# SBERT 계열 임베딩 모델 (원하면 환경변수로 교체)
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL", "snunlp/KR-SBERT-V40")

# ====== 내부 상태(싱글톤) ======
_model: Optional[SentenceTransformer] = None                   # 임베딩 모델
_indices: Dict[str, faiss.IndexFlatIP] = {}                    # 보험사별 인덱스
_chunks:  Dict[str, List[Dict]] = {}                           # 보험사별 청크(meta+text)
_dim: Optional[int] = None
_initialized = False


# ====== 유틸 ======
def _normalize_insurer_from_filename(fname: str) -> str:
    f = Path(fname).name
    if f.startswith("DB"):
        return "DB손해"
    if f.startswith("현대"):
        return "현대해상"
    if f.startswith("삼성"):
        return "삼성화재"
    return "기타"


def _chunk_text(s: str, chunk_size: int = 900, overlap: int = 150) -> List[str]:
    s = re.sub(r"\s+", " ", s).strip()
    out, i = [], 0
    while i < len(s):
        out.append(s[i:i + chunk_size])
        i += chunk_size - overlap
    return out


def _ensure_model():
    global _model, _dim
    if _model is None:
        print(f"[RAG] Loading SBERT model: {EMBED_MODEL_NAME}")
        _model = SentenceTransformer(EMBED_MODEL_NAME)
        # dim은 인코딩 시 얻는다.
    return _model


def _save_index(insurer: str, index: faiss.IndexFlatIP, chunks: List[Dict]):
    faiss.write_index(index, str(INDEX_DIR / f"{insurer}.faiss"))
    with open(INDEX_DIR / f"{insurer}.meta.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)


def _load_index(insurer: str) -> bool:
    """저장된 인덱스/메타를 로드. 없으면 False"""
    faiss_f = INDEX_DIR / f"{insurer}.faiss"
    meta_f  = INDEX_DIR / f"{insurer}.meta.json"
    if not faiss_f.exists() or not meta_f.exists():
        return False
    try:
        index = faiss.read_index(str(faiss_f))
        with open(meta_f, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        _indices[insurer] = index
        _chunks[insurer]  = chunks
        # 차원 기억
        global _dim
        _dim = index.d  # type: ignore
        print(f"[RAG] Loaded index for {insurer}: {len(chunks)} chunks, dim={_dim}")
        return True
    except Exception as e:
        print(f"[RAG] Failed to load index for {insurer}: {e}")
        return False


def _build_index_for_insurer(insurer: str):
    """해당 보험사 파일들에서 인덱스를 새로 구축."""
    model = _ensure_model()

    pdfs = [p for p in PDF_DIR.glob("*.pdf") if _normalize_insurer_from_filename(p.name) == insurer]
    if not pdfs:
        print(f"[RAG] No PDFs for insurer={insurer} in {PDF_DIR}")
        return

    chunks: List[Dict] = []
    for pdf in pdfs:
        try:
            reader = PdfReader(str(pdf))
            for pageno, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                if not text.strip():
                    continue
                for piece in _chunk_text(text):
                    chunks.append({
                        "text": piece,
                        "meta": {"file": pdf.name, "page": pageno, "insurer": insurer},
                    })
        except Exception as e:
            print(f"[RAG] PDF read error: {pdf} - {e}")

    if not chunks:
        print(f"[RAG] No chunks after parsing for insurer={insurer}")
        return

    texts = [c["text"] for c in chunks]
    embs = model.encode(texts, normalize_embeddings=True).astype("float32")
    dim  = embs.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embs)

    _indices[insurer] = index
    _chunks[insurer]  = chunks

    global _dim
    _dim = dim
    _save_index(insurer, index, chunks)
    print(f"[RAG] Built index for {insurer}: {len(chunks)} chunks, dim={dim}")


def _ensure_insurer_ready(insurer: str):
    """요청 시점에 해당 보험사 인덱스가 준비되어 있도록 보장."""
    insurer = insurer or "DB손해"
    if insurer in _indices:
        return
    # 1) 로드 시도 → 2) 없으면 빌드
    if not _load_index(insurer):
        _build_index_for_insurer(insurer)


def init_indices():
    """서버 기동 시 한 번 호출 권장(없어도 첫 요청 때 lazy-init)."""
    global _initialized
    if _initialized:
        return
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for insurer in ["DB손해", "현대해상", "삼성화재"]:
        _ensure_insurer_ready(insurer)
    _initialized = True
    print("[RAG] indices ready.")


# ====== 공개 API ======
def retrieve_context(query: str, insurer: Optional[str] = None, top_k: Optional[int] = 3) -> str:
    """
    질의에 대한 상위 컨텍스트 텍스트를 하나의 문자열로 반환.
    RAG 파이프라인에서 system 프롬프트에 주입해서 사용한다.
    """
    if not query or not str(query).strip():
        return ""

    insurer = insurer or "DB손해"
    top_k = max(1, int(top_k or 3))

    _ensure_insurer_ready(insurer)
    if insurer not in _indices:
        return ""

    model = _ensure_model()
    qvec = model.encode([query], normalize_embeddings=True).astype("float32")
    D, I = _indices[insurer].search(qvec, top_k)
    hits = []
    for idx in I[0]:
        if idx < 0 or idx >= len(_chunks[insurer]):
            continue
        c = _chunks[insurer][idx]
        # 컨텍스트는 과다 길이 방지(모델 지연 방지)
        snippet = c["text"][:1200]
        hits.append(f"({c['meta']['file']} p.{c['meta']['page']})\n{snippet}")

    # 너무 길면 하드컷
    joined = "\n\n---\n\n".join(hits)
    return joined[:6000]
