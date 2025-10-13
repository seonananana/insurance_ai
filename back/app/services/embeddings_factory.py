# app/services/embeddings_factory.py
import os
from pathlib import Path
from .embeddings_sbert import SBertEmbeddings

DEFAULT_HF_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def get_repo_root() -> Path:
    # .../app/services/embeddings_factory.py => repo root 추정
    return Path(__file__).resolve().parents[2]  # ~/insurance_ai/back

def get_embeddings_client():
    backend = os.getenv("EMBEDDINGS_BACKEND", "sbert").lower()
    if backend == "sbert":
        cfg = os.getenv("SBERT_MODEL_PATH", "").strip()
        if cfg:
            # 사용자가 환경변수로 경로 또는 HF 아이디를 준 경우
            model_path = cfg
        else:
            # 로컬 폴더 우선 시도
            local_dir = get_repo_root() / "models" / "ins-match-embed"
            if local_dir.exists():
                model_path = str(local_dir.resolve())
            else:
                # 마지막 폴백: HF 아이디
                model_path = DEFAULT_HF_MODEL
        return SBertEmbeddings(model_path)
    else:
        raise ValueError(f"Unsupported EMBEDDINGS_BACKEND: {backend}")
