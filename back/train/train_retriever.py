# back/train/train_retriever.py
# Ultra-safe training for low-memory CPU boxes

import os
import json
import random
import warnings
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, Iterator

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
warnings.filterwarnings("ignore", message=".*pin_memory.*")

import torch
torch.set_num_threads(1)

from sentence_transformers import SentenceTransformer, InputExample, losses, evaluation
from torch.utils.data import IterableDataset, DataLoader

# -----------------------
# 설정 (환경변수로 즉시 튜닝 가능)
# -----------------------
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "train"
OUT_DIR  = BASE_DIR / "models" / "ins-match-embed"

# 학습 데이터 후보 파일 (존재하는 순으로 선택)
CANDIDATES = [
    DATA_DIR / "pairs.jsonl",
    DATA_DIR / "pairs_positive.jsonl",
    DATA_DIR / "triplets.jsonl",
]

# 모델/학습 하이퍼파라미터 (env override 가능)
BASE_MODEL   = os.getenv("E5_BASE", "intfloat/multilingual-e5-small")  # ★ 더 작은 기본값
BATCH_SIZE   = int(os.getenv("TRAIN_BATCH", "2"))       # ★ 매우 작게 시작
EPOCHS       = int(os.getenv("EPOCHS", "1"))            # 일단 1 epoch로 검증
WARMUP_STEPS = int(os.getenv("WARMUP_STEPS", "200"))
MAX_LEN      = int(os.getenv("MAX_LEN", "128"))         # ★ 96~128 권장
SEED         = int(os.getenv("SEED", "42"))

# 평가 토글/크기
ENABLE_EVAL  = os.getenv("EVAL", "0").lower() not in ("0", "false", "no", "n")  # ★ 기본 끔
NOISE_MAX    = int(os.getenv("EVAL_NOISE_MAX", "256"))

# 한 epoch에 사용할 step 수 (OOM/누수 방지용)
STEPS_PER_EPOCH = int(os.getenv("STEPS_PER_EPOCH", "800"))  # 필요시 500/300까지 낮추세요

# 셔플 버퍼 크기: 메모리와 타협 (너무 크면 OOM 원인)
SHUFFLE_BUFFER = int(os.getenv("SHUFFLE_BUFFER", "1024"))   # 512~2048 사이 권장

# -----------------------
# E5 전처리
# -----------------------
def as_query(x: str) -> str:
    return f"query: {x}"

def as_passage(x: str) -> str:
    return f"passage: {x}"

# -----------------------
# JSONL 파서
# -----------------------
def _first_str(d: Dict[str, Any], *keys) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

def parse_pair_line(line: str) -> Optional[InputExample]:
    try:
        d = json.loads(line)
    except Exception:
        return None
    q = _first_str(d, "query", "q", "anchor")
    p = _first_str(d, "positive", "pos", "p", "passage", "text")
    if not (q and p):
        return None
    # CosineSimilarityLoss 사용 → label 필수
    return InputExample(texts=[as_query(q), as_passage(p)], label=1.0)

def choose_train_file() -> Path:
    for p in CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No training file found under {DATA_DIR} "
        f"(expected one of: {', '.join(x.name for x in CANDIDATES)})"
    )

# -----------------------
# 스트리밍 데이터셋(파일 → 작은 셔플 버퍼 → 배치)
# -----------------------
class PairsStream(IterableDataset):
    def __init__(self, jsonl_path: Path, shuffle_buffer: int, seed: int):
        self.path = jsonl_path
        self.bufsz = max(1, shuffle_buffer)
        self.seed = seed

    def __iter__(self) -> Iterator[InputExample]:
        # 작은 버퍼로 의사 셔플 (in-memory 전체 적재 X)
        rng = random.Random(self.seed + torch.randint(0, 10_000_000, ()).item())
        buf: deque[InputExample] = deque(maxlen=self.bufsz)

        def flush_buffer():
            # 버퍼에 남은 것을 무작위 순서로 방출
            tmp = list(buf)
            rng.shuffle(tmp)
            buf.clear()
            for it in tmp:
                yield it

        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                ex = parse_pair_line(line.strip())
                if ex is None:
                    continue
                buf.append(ex)
                # 버퍼가 꽉 차면 일부를 랜덤 방출
                if len(buf) == self.bufsz:
                    k = max(1, self.bufsz // 4)  # 일부만 내보내고 잔류시켜 다양성 유지
                    tmp = list(buf)
                    rng.shuffle(tmp)
                    emit, keep = tmp[:k], tmp[k:]
                    buf.clear()
                    for it in keep:
                        buf.append(it)
                    for it in emit:
                        yield it

        # 잔여 방출
        yield from flush_buffer()

# -----------------------
# 메인
# -----------------------
def main():
    random.seed(SEED)

    train_path = choose_train_file()
    print(f"[ok] training source: {train_path}")

    # 모델/손실 (먼저 생성해야 collate_fn 사용 가능)
    model = SentenceTransformer(BASE_MODEL)
    model.max_seq_length = MAX_LEN

    # 가능한 경우 gradient checkpointing 활성화 (메모리 절감)
    try:
        first = model._first_module()
        if hasattr(first, "auto_model") and hasattr(first.auto_model, "gradient_checkpointing_enable"):
            first.auto_model.gradient_checkpointing_enable()
            print("[info] gradient checkpointing enabled")
    except Exception:
        pass

    # 메모리 친화 손실
    loss = losses.CosineSimilarityLoss(model)

    # 스트리밍 데이터셋 & 로더
    train_ds = PairsStream(train_path, shuffle_buffer=SHUFFLE_BUFFER, seed=SEED)
    train_dl = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        shuffle=False,               # IterableDataset는 shuffle 불가
        drop_last=False,
        num_workers=0,
        pin_memory=False,
        collate_fn=model.smart_batching_collate
    )

    evaluator = None  # 안전 모드: 평가 기본 끔

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 짧게 끊어서 학습 (메모리 피크/누수 회피)
    model.fit(
        train_objectives=[(train_dl, loss)],
        evaluator=evaluator,
        epochs=EPOCHS,
        steps_per_epoch=STEPS_PER_EPOCH,
        warmup_steps=WARMUP_STEPS,
        output_path=str(OUT_DIR),
        use_amp=False,
        show_progress_bar=True,
        save_best_model=True
    )

    print("Saved to", OUT_DIR)

if __name__ == "__main__":
    main()
