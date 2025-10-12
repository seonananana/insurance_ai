# back/app/services/embeddings_sbert.py
# --rag_service.search_top_k() 호출 전에 질문은 is_query=True로
#문서 청크는 기본(패시지)로 임베딩해야 E5 계열 성능이 잘 나옴.
#문서 적재 스크립트(ingest_pdfs_to_chunks.py)는 embed(chunks) 그대로(패시지), /qa/ask의 쿼리 임베딩은 embed([question], is_query=True)로 호출.
from __future__ import annotations
from sentence_transformers import SentenceTransformer
from typing import List

class SBertEmbeddings:
    def __init__(self, model_dir: str):
        self.model = SentenceTransformer(model_dir)
        # E5는 지시어 사용
        self.use_e5_prefix = True

    @property
    def dim(self):
        return self.model.get_sentence_embedding_dimension()

    def _prep(self, texts: List[str], is_query=False):
        if self.use_e5_prefix:
            prefix = "query: " if is_query else "passage: "
            return [prefix + t for t in texts]
        return texts

    def embed(self, texts: List[str], is_query=False) -> List[list]:
        texts = self._prep(texts, is_query=is_query)
        v = self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return v.tolist()
