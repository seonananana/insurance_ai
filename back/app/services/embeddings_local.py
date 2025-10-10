# 결제 전 돌려보기 위한 코드
from __future__ import annotations
import hashlib, numpy as np
from typing import List

DIM = 3072  # OpenAI 임베딩과 동일 차원

def _hash_vec(text: str, dim: int = DIM) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(h[:8], "little")
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim)
    v = v / (np.linalg.norm(v) + 1e-12)
    return v.tolist()

class LocalHashEmbeddings:
    dim = DIM
    def embed(self, texts: List[str]) -> List[list]:
        return [_hash_vec(t, DIM) for t in texts]
