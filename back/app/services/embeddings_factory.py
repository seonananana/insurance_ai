# 결제 전 돌려보기 위한 코드

from __future__ import annotations
import os
from .embeddings_local import LocalHashEmbeddings

def get_embeddings_client():
    backend = os.getenv("EMBEDDINGS_BACKEND", "local").lower()
    if backend == "openai":
        raise RuntimeError("결제 후에 EMBEDDINGS_BACKEND=openai로 전환하세요.")
    return LocalHashEmbeddings()
