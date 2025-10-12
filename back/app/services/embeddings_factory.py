# back/app/services/embeddings_factory.py
# 임베딩 팩토리 교체

from __future__ import annotations
import os

def get_embeddings_client():
    backend = os.getenv("EMBEDDINGS_BACKEND", "local").lower()
    if backend == "local":
        from .embeddings_local import LocalHashEmbeddings
        return LocalHashEmbeddings()
    elif backend == "sbert":
        from .embeddings_sbert import SBertEmbeddings
        model_dir = os.getenv("SBERT_MODEL_DIR", "models/ins-match-embed")
        return SBertEmbeddings(model_dir)
    elif backend == "openai":
        raise RuntimeError("결제 후에 EMBEDDINGS_BACKEND=openai로 전환하세요.")
    else:
        raise RuntimeError(f"Unknown EMBEDDINGS_BACKEND={backend}")
