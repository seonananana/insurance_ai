# back/app/services/embeddings_sbert.py
# -- E5/BGE 계열 최적화: 쿼리는 is_query=True → "query: ...",
#    문서 패시지는 기본 → "passage: ..." 접두사(자동 감지/강제 가능)
# -- ETL(ingest_pdfs_to_chunks.py)에서는 embed(chunks)  # passage
# -- 검색(/qa/ask)에서는 embed([question], is_query=True)  # query

from __future__ import annotations

from typing import List, Optional
from pathlib import Path
import os

from sentence_transformers import SentenceTransformer


# 모델명 휴리스틱
_PREFIX_FAMILIES_TRUE = ("e5", "bge")          # ex) intfloat/e5-base-v2, bge-m3
_PREFIX_FAMILIES_FALSE = ("mpnet", "minilm", "distiluse", "gte")  # gte는 접두사 불필요 케이스 多


def _looks_like_local_path(s: str) -> bool:
    p = Path(s)
    return p.exists()


def _resolve_model_path(model_name_or_path: str) -> str:
    # 로컬 경로면 절대경로로
    if _looks_like_local_path(model_name_or_path):
        return str(Path(model_name_or_path).resolve())
    return model_name_or_path  # HF Hub 모델 ID 그대로


def _auto_detect_use_prefix(model_name_or_path: str) -> bool:
    """
    use_e5_prefix=None일 때 자동 판정:
      - SBERT_USE_PREFIX=1/0 으로 강제 가능
      - 모델명에 'e5'/'bge' 포함 → True
      - mpnet/minilm/distiluse/gte 포함 → False
      - 기타는 보수적으로 False
    """
    env = os.getenv("SBERT_USE_PREFIX", "").strip().lower()
    if env in ("1", "true", "yes", "y"):
        return True
    if env in ("0", "false", "no", "n"):
        return False

    name = (model_name_or_path or "").lower()
    if any(f in name for f in _PREFIX_FAMILIES_TRUE):
        return True
    if any(f in name for f in _PREFIX_FAMILIES_FALSE):
        return False
    return False


def _get_prefix_strings() -> tuple[str, str]:
    # SBERT_PREFIX_QUERY / SBERT_PREFIX_PASSAGE 로 커스터마이즈 가능
    q = os.getenv("SBERT_PREFIX_QUERY", "query: ").strip()
    p = os.getenv("SBERT_PREFIX_PASSAGE", "passage: ").strip()
    return q, p


class SBertEmbeddings:
    """
    SentenceTransformer 래퍼:
      - e5/bge 자동 접두사
      - normalize 옵션 일관화
      - 배치 크기/디바이스/에러 메시지 개선
    """

    def __init__(
        self,
        model_dir: str,
        *,
        use_e5_prefix: Optional[bool] = None,
        device: Optional[str] = None,         # "cuda" / "cpu" / "mps"
        normalize: bool = True,
        default_batch_size: int = 32,
    ):
        """
        model_dir: 로컬경로 또는 HF 모델 ID
        use_e5_prefix: None(자동), True/False(강제)
        device: SentenceTransformer(device=...)
        normalize: encode 시 normalize_embeddings 기본값
        default_batch_size: encode 기본 배치 크기 (SBERT_BATCH_SIZE 로 오버라이드 가능)
        """
        path = _resolve_model_path(model_dir)
        try:
            self.model = SentenceTransformer(path, device=device)
        except Exception as e:
            raise ValueError(
                f"SBERT 모델 로딩 실패: '{model_dir}' (resolved='{path}')\n{e}"
            ) from e

        self.model_id_or_path = path
        self.normalize = normalize

        # 배치 크기: env 우선
        env_bs = os.getenv("SBERT_BATCH_SIZE")
        self.default_batch_size = default_batch_size
        if env_bs:
            try:
                self.default_batch_size = max(1, int(env_bs))
            except ValueError:
                # 무시하고 기본값 사용
                pass

        # 접두사 자동/강제
        self.use_prefix = _auto_detect_use_prefix(path) if use_e5_prefix is None else bool(use_e5_prefix)
        self.query_prefix, self.passage_prefix = _get_prefix_strings()

    @property
    def dim(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    # 내부 전처리: 공백/None 방지 + 접두사
    def _prep(self, texts: List[str], *, is_query: bool = False) -> List[str]:
        cleaned = [(t or "").strip() for t in texts]
        if self.use_prefix:
            prefix = self.query_prefix if is_query else self.passage_prefix
            pl = prefix.lower()
            # 이미 같은 접두사면 중복 부착 방지(대소문자 무시)
            return [t if t.lower().startswith(pl) else (prefix + t) for t in cleaned]
        return cleaned

    def embed(
        self,
        texts: List[str],
        *,
        is_query: bool = False,
        batch_size: Optional[int] = None,
        normalize_embeddings: Optional[bool] = None,
        show_progress_bar: bool = False,
    ) -> List[List[float]]:
        """
        문장 리스트 → 벡터 리스트(List[List[float]]) 반환.
        - is_query=True: 쿼리 접두사 적용(e5/bge 자동일 때)
        - batch_size: 미지정 시 default_batch_size 사용 (음수/0 방지)
        - normalize_embeddings: 미지정 시 self.normalize
        """
        if not isinstance(texts, list):
            raise TypeError("texts must be a List[str].")

        prepped = self._prep(texts, is_query=is_query)
        if not prepped:
            return []

        # 배치 크기 안전 가드
        bs = batch_size if batch_size is not None else self.default_batch_size
        try:
            bs = int(bs)
        except Exception:
            bs = self.default_batch_size or 32
        if bs <= 0:
            bs = self.default_batch_size or 32

        norm = self.normalize if normalize_embeddings is None else bool(normalize_embeddings)

        vecs = self.model.encode(
            prepped,
            batch_size=bs,
            normalize_embeddings=norm,
            convert_to_numpy=True,
            show_progress_bar=show_progress_bar,
        )
        # numpy.ndarray → list
        return vecs.tolist()
