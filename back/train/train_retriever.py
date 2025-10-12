# back/train/train_retriever.py
# 로컬 환경에서 비용 없이 학습할 수 있는 Sentence-Transformers 기반 Bi-Encoder를 사용
# 권장 초기 베이스(한국어 포함 다국어): intfloat/multilingual-e5-base (768차원, 속도/정확도 균형)
import json, random, math
from pathlib import Path
from sentence_transformers import SentenceTransformer, InputExample, losses, models, SentenceTransformerTrainer, evaluation
from torch.utils.data import DataLoader

DATA = Path(__file__).resolve().parents[1] / "data" / "train" / "triplets.jsonl"
OUT  = Path(__file__).resolve().parents[1] / "models" / "ins-match-embed"

base = "intfloat/multilingual-e5-base"  # 768-d
model = SentenceTransformer(base)

# E5 권장 전처리: 입력 앞에 지시어
def as_query(x): return f"query: {x}"
def as_passage(x): return f"passage: {x}"

triplets = [json.loads(x) for x in DATA.read_text(encoding="utf-8").splitlines()]
random.shuffle(triplets)

train_size = int(len(triplets)*0.9)
train, dev = triplets[:train_size], triplets[train_size:]

train_ex = [InputExample(texts=[as_query(t["query"]), as_passage(t["positive"])]) for t in train]
# MultipleNegativesRankingLoss: 배치 내 다른 positive를 자동 네거티브로 사용
train_dl = DataLoader(train_ex, batch_size=64, shuffle=True, drop_last=True)
loss = losses.MultipleNegativesRankingLoss(model)

# 간단한 평가: dev 쿼리→ 후보(정답+노이즈 몇 개) R@1
def build_dev_evaluator(dev, k_noise=15):
    queries = [as_query(t["query"]) for t in dev]
    positives = [as_passage(t["positive"]) for t in dev]
    # 노이즈(네거티브) 후보 섞기
    passages = positives.copy()
    random.shuffle(passages)
    passages = passages[:max(64, k_noise)] + positives  # 최소 풀 구성
    return evaluation.InformationRetrievalEvaluator(
        queries=[f"q{i}" for i in range(len(queries))],
        corpus={f"p{j}": p for j,p in enumerate(passages)},
        relevant_docs={f"q{i}": {f"p{len(passages)-len(positives)+i}"} for i in range(len(positives))},
        query_texts=queries,
        corpus_chunk_size=100000,
        name="dev-rer",
        show_progress_bar=False,
    )

evaluator = build_dev_evaluator(dev)

trainer = SentenceTransformerTrainer(
    model=model,
    train_objectives=[(train_dl, loss)],
    evaluator=evaluator,
    epochs=2,                 # 시작은 2~3 epoch로 빠르게 확인
    evaluation_steps=500,
    warmup_steps=1000,
    use_amp=True,
    output_path=str(OUT),
)
trainer.fit()
print("Saved to", OUT)
