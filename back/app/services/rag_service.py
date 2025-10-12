# back/app/services/rag_service.py
from __future__ import annotations

import os, re, json
from pathlib import Path
from typing import Dict, List, Optional

import faiss
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader

# ===== 설정 =====
BASE_DIR  = Path(__file__).resolve().parents[2]          # back/
FILES_DIR = Path(os.getenv("FILES_DIR", BASE_DIR / "files")).resolve()

# 사용자가 지정하면 최우선(파일 경로/디렉터리 모두 허용: 파일이면 그 파일만 사용)
PDF_DIR_ENV = os.getenv("PDF_DIR", "").strip()

# SBERT 모델 (env로 교체 가능)
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL", "snunlp/KR-SBERT-V40")

# 디스크 캐시(기본 꺼짐: 새 파일 안 만듦)
ENABLE_RAG_CACHE = os.getenv("ENABLE_RAG_CACHE", "0") == "1"
INDEX_DIR = Path(os.getenv("INDEX_DIR", FILES_DIR / "indices")).resolve()

# 전역 상태
_model: Optional[SentenceTransformer] = None
_indices: Dict[str, faiss.IndexFlatIP] = {}      # insurer -> index
_chunks:  Dict[str, List[Dict]] = {}             # insurer -> chunks
_dim: Optional[int] = None
_initialized = False

# ---------------- 경로 탐색 로직 ----------------
def _normalize_insurer_from_filename(fname: str) -> str:
    f = Path(fname).name
    if f.startswith("DB"):
        return "DB손해"
    if f.startswith("현대"):
        return "현대해상"
    if f.startswith("삼성"):
        return "삼성화재"
    return "기타"

def _candidate_pdf_dirs() -> List[Path]:
    """가능성이 높은 디렉터리 후보들을 반환 (존재 여부는 나중에 검증)."""
    candidates: List[Path] = []
    if PDF_DIR_ENV:
        candidates.append(Path(PDF_DIR_ENV))

    # 프로젝트에서 흔한 위치들
    candidates += [
        FILES_DIR / "pdfs",
        BASE_DIR / "pdfs",
        BASE_DIR / "data" / "pdfs",
        BASE_DIR / "datasets" / "pdfs",
        BASE_DIR / "assets" / "pdfs",
        BASE_DIR / "docs" / "pdfs",
        BASE_DIR / "data",
        BASE_DIR / "datasets",
        BASE_DIR / "assets",
        BASE_DIR / "docs",
    ]
    # 중복 제거
    seen = set()
    uniq: List[Path] = []
    for c in candidates:
        if c not in seen:
            uniq.append(c)
            seen.add(c)
    return uniq

def _discover_pdf_files() -> List[Path]:
    """
    1) 환경변수 PDF_DIR가 파일이면 -> 그 파일만 사용
    2) 환경변수/후보 디렉터리들 중 존재하는 디렉터리의 *.pdf 수집
    3) 그래도 못 찾으면 BASE_DIR 전체 재귀 검색(최대 500개)
    """
    # 1) env가 파일인 경우
    if PDF_DIR_ENV:
        p = Path(PDF_DIR_ENV)
        if p.is_file() and p.suffix.lower() == ".pdf":
            print(f"[RAG] Using single PDF file from PDF_DIR={p}")
            return [p]

    # 2) 후보 디렉터리 스캔
    pdfs: List[Path] = []
    for d in _candidate_pdf_dirs():
        if d.is_dir():
            found = sorted(d.glob("*.pdf"))
            if found:
                print(f"[RAG] Found {len(found)} PDFs in {d}")
                pdfs.extend(found)

    if pdfs:
        # 중복 제거
        pdfs = sorted(list(dict.fromkeys(pdfs)))
        return pdfs

    # 3) 최후: 프로젝트 전체 재귀 스캔 (비용 보호를 위해 상한)
    print(f"[RAG] No PDFs in candidates. Scanning project recursively from {BASE_DIR} (cap=500)")
    cap = 500
    count = 0
    for p in BASE_DIR.rglob("*.pdf"):
        pdfs.append(p)
        count += 1
        if count >= cap:
            break
    pdfs = sorted(list(dict.fromkeys(pdfs)))
    if not pdfs:
        print("[RAG] No PDF files found in project.")
    else:
        print(f"[RAG] Found {len(pdfs)} PDFs by recursive scan.")
    return pdfs

# 발견한 PDF들을 한 번 계산해 재사용
_PDF_FILES: List[Path] = _discover_pdf_files()

# ---------------- 공통 유틸 ----------------
def _chunk_text(s: str, chunk_size: int = 900, overlap: int = 150) -> List[str]:
    s = re.sub(r"\s+", " ", s).strip()
    out, i = [], 0
    while i < len(s):
        out.append(s[i:i + chunk_size])
        i += chunk_size - overlap
    return out

def _ensure_model():
    global _model
    if _model is None:
        print(f"[RAG] Loading SBERT model: {EMBED_MODEL_NAME}")
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model

def _cache_paths(insurer: str):
    return (INDEX_DIR / f"{insurer}.faiss", INDEX_DIR / f"{insurer}.meta.json")

def _save_index(insurer: str, index: faiss.IndexFlatIP, chunks: List[Dict]):
    if not ENABLE_RAG_CACHE:
        return
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    idx_f, meta_f = _cache_paths(insurer)
    faiss.write_index(index, str(idx_f))
    with open(meta_f, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)

def _load_index(insurer: str) -> bool:
    if not ENABLE_RAG_CACHE:
        return False
    idx_f, meta_f = _cache_paths(insurer)
    if not idx_f.exists() or not meta_f.exists():
        return False
    try:
        index = faiss.read_index(str(idx_f))
        with open(meta_f, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        _indices[insurer] = index
        _chunks[insurer]  = chunks
        global _dim
        _dim = index.d  # type: ignore
        print(f"[RAG] Loaded cached index for {insurer}: {len(chunks)} chunks, dim={_dim}")
        return True
    except Exception as e:
        print(f"[RAG] Cache load failed for {insurer}: {e}")
        return False

# ---------------- 인덱스 빌드/검색 ----------------
def _build_index_for_insurer(insurer: str):
    """발견된 PDF 목록에서 해당 보험사 것만 골라 인메모리 인덱스 생성."""
    model = _ensure_model()
    pdfs = [p for p in _PDF_FILES if _normalize_insurer_from_filename(p.name) == insurer]
    if not pdfs:
        print(f"[RAG] No PDFs for insurer={insurer} (checked {_PDF_FILES[:3]} ...)")
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
    print(f"[RAG] Built index for {insurer}: {len(chunks)} chunks, dim={dim} (cache={'on' if ENABLE_RAG_CACHE else 'off'})")

def _ensure_insurer_ready(insurer: str):
    insurer = insurer or "DB손해"
    if insurer in _indices:
        return
    if not _load_index(insurer):
        _build_index_for_insurer(insurer)

def init_indices():
    """앱 기동 시 호출 권장(없어도 첫 요청 시 lazy-init)."""
    global _initialized
    if _initialized:
        return
    for insurer in ["DB손해", "현대해상", "삼성화재"]:
        _ensure_insurer_ready(insurer)
    _initialized = True
    print("[RAG] indices ready (cache=%s)" % ("on" if ENABLE_RAG_CACHE else "off"))

# ---------------- 공개 API ----------------
def retrieve_context(query: str, insurer: Optional[str] = None, top_k: Optional[int] = 3) -> str:
    """
    질문과 가장 가까운 컨텍스트 텍스트를 합쳐 반환.
    PDF 위치는 자동 탐색 결과(_PDF_FILES) 사용. 디스크 캐시는 기본 비활성.
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
        snippet = c["text"][:1200]
        hits.append(f"({c['meta']['file']} p.{c['meta']['page']})\n{snippet}")

    joined = "\n\n---\n\n".join(hits)
    return joined[:6000]
