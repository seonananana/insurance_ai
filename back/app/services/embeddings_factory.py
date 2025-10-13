# app/services/embeddings_factory.py
import os
from pathlib import Path
from .embeddings_sbert import SBertEmbeddings

# 기본 폴백 모델 (한국어 포함 멀티링구얼 미니)
DEFAULT_HF_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def get_repo_root() -> Path:
    """
    현재 파일(app/services/embeddings_factory.py) 기준으로
    저장소 루트 경로를 추정하여 반환.
    예: ~/insurance_ai/back
    """
    return Path(__file__).resolve().parents[2]

def get_embeddings_client():
    """
    프로젝트 전역에서 사용할 임베딩 클라이언트를 생성합니다.
    기본값은 SBERT(back/models/ins-match-embed).
    환경변수:
      - EMBEDDINGS_BACKEND=sbert
      - SBERT_MODEL_PATH=로컬모델경로 or HF모델아이디
    """
    backend = os.getenv("EMBEDDINGS_BACKEND", "sbert").lower()

    if backend == "sbert":
        cfg = os.getenv("SBERT_MODEL_PATH", "").strip()
        if cfg:
            model_path = cfg  # 직접 지정 경로/HF 아이디 우선
        else:
            # 로컬 폴더(back/models/ins-match-embed) 우선
            local_dir = get_repo_root() / "models" / "ins-match-embed"
            model_path = str(local_dir.resolve()) if local_dir.exists() else DEFAULT_HF_MODEL

        print(f"[embeddings_factory] Using SBERT model: {model_path}")
        return SBertEmbeddings(model_path)

    else:
        raise ValueError(f"Unsupported EMBEDDINGS_BACKEND: {backend}")
