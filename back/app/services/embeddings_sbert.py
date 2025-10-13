# back/app/services/embeddings_sbert.py
# --rag_service.search_top_k() 호출 전에 질문은 is_query=True로
# 문서 청크는 기본(패시지)로 임베딩해야 E5/BGE 계열 성능이 잘 나옴.
# 문서 적재 스크립트(ingest_pdfs_to_chunks.py)는 embed(chunks) 그대로(패시지),
# /qa/ask 의 쿼리 임베딩은 embed([question], is_query=True)로 호출.

from __future__ import annotations
from typing import List, Optional
from pathlib import Path
import os

from sentence_transformers import SentenceTransformer

_PREFIX_FAMILIES_TRUE = ("e5", "bge")   # 'e5-base', 'e5-multilingual', 'bge-m3' 등
_PREFIX_FAMILIES_FALSE = ("mpnet", "minilm", "distiluse", "gte")  # gte는 보통 프리픽스 불필요

def _looks_like_local_path(s: str) -> bool:
    p = Path(s)
    return p.exists()

def _resolve_model_path(model_name_or_path: str) -> str:
    # 로컬 경로면 절대경로로 정규화
    if _looks_like_local_path(model_name_or_path):
        return str(Path(model_name_or_path).resolve())
    return model_name_or_path  # HF 모델 ID 그대로

def _auto_detect_use_prefix(model_name_or_path: str) -> bool:
    name = model_name_or_path.lower()
    # 환경변수 강제 설정이 있으면 그 값을 우선
    env_override = os.getenv("SBERT_USE_PREFIX", "").strip().lower()
    if env_override in ("1", "true", "yes", "y"):
        return True
    if env_override in ("0", "false", "no", "n"):
        return False

    # 휴리스틱: 모델명에 e5/bge 포함 → prefix 권장
    if any(fam in name for fam in _PREFIX_FAMILIES_TRUE):
        return True
    if any(fam in name for fam in _PREFIX_FAMILIES_FALSE):
        return False
    # 모르면 보수적으로 False (프리픽스 강제하지 않음)
    return False

def _get_prefix_strings() -> tuple[str, str]:
    # 필요 시 환경변수로 커스터마이즈 가능
    q = os.getenv("SBERT_PREFIX_QUERY", "query: ").strip()
    p = os.getenv("SBERT_PREFIX_PASSAGE", "passage: ").strip()
    return q, p

class SBertEmbeddings:
    def __init__(
        self,
        model_dir: str,
        *,
        use_e5_prefix: Optional[bool] = None,
        device: Optional[str] = None,     # e.g., "cuda", "cpu", "mps"
        normalize: bool = True,
        default_batch_size: int = 32,     # ✅ 기본 배치 크기(폴백)
    ):
        """
        model_dir: 로컬 폴더 또는 HF 모델 ID
        use_e5_prefix: None이면 자동 감지(e5/bge True), True/False로 강제 가능
        device: SentenceTransformer(device=...) 전달
        normalize: encode 시 normalize_embeddings 기본값
        default_batch_size: encode 기본 배치 크기
        """
        path = _resolve_model_path(model_dir)
        try:
            self.model = SentenceTransformer(path, device=device)
        except Exception as e:
            raise ValueError(
                f"Failed to load SBERT model from '{model_dir}'. "
                f"Resolved path/id: '{path}'. Original error: {e}"
            ) from e

        self.model_id_or_path = path
        self.normalize = normalize
        # ✅ 환경변수로도 오버라이드 가능 (예: export SBERT_BATCH_SIZE=64)
        env_bs = os.getenv("SBERT_BATCH_SIZE")
        self.default_batch_size = default_batch_size
        if env_bs:
            try:
                self.default_batch_size = max(1, int(env_bs))
            except ValueError:
                pass

        if use_e5_prefix is None:
            self.use_prefix = _auto_detect_use_prefix(path)
        else:
            self.use_prefix = bool(use_e5_prefix)

        self.query_prefix, self.passage_prefix = _get_prefix_strings()

    @property
    def dim(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def _prep(self, texts: List[str], is_query: bool = False) -> List[str]:
        # 안전 장치: None/공백 방지 및 strip
        cleaned = [(t or "").strip() for t in texts]
        if self.use_prefix:
            prefix = self.query_prefix if is_query else self.passage_prefix
            # 이미 같은 접두사가 있으면 중복 붙이지 않음 (대소문자 무시)
            pl = prefix.lower()
            out = [t if t.lower().startswith(pl) else (prefix + t) for t in cleaned]
            return out
        return cleaned

    def embed(
        self,
        texts: List[str],
        *,
        is_query: bool = False,
        batch_size: Optional[int] = None,
        normalize_embeddings: Optional[bool] = None,
        show_progress_bar: bool = False,
    ) -> List[list]:
        """
        returns: List[List[float]]  (convert_to_numpy=True → .tolist())
        """
        if not isinstance(texts, list):
            raise TypeError("texts must be a List[str].")

        prepped = self._prep(texts, is_query=is_query)
        if not prepped:
            return []

        # ✅ batch_size 안전 폴백 (None 금지)
        bs = batch_size if batch_size is not None else self.default_batch_size
        try:
            bs = int(bs)
        except Exception:
            bs = 32
        if bs <= 0:
            bs = 32

        norm = self.normalize if normalize_embeddings is None else normalize_embeddings

        vecs = self.model.encode(
            prepped,
            batch_size=bs,
            normalize_embeddings=norm,
            convert_to_numpy=True,
            show_progress_bar=show_progress_bar,
        )
        return vecs.tolist()
