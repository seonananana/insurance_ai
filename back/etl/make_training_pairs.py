# back/etl/make_training_pairs.py
# 학습 포맷, 자동 생성 규칙(실데이터 없을 때도 바로 가능), 
import json, random, re
from pathlib import Path

CURATED = Path(__file__).resolve().parents[1] / "data" / "curated"
OUT = Path(__file__).resolve().parents[1] / "data" / "train" / "triplets.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)

def make_query(title, body):
    key = (title or "").strip()
    key = re.sub(r"\s+", " ", key)[:60]
    templates = [
        f"{key} 요건이 뭐야?",
        f"{key} 보상 조건 알려줘",
        f"{key} 필요한 서류",
        f"{key} 제외/면책은?",
        f"{key} 정리",
    ]
    return random.choice(templates)

def body_clip(t, n=600):
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]

docs = []
for jf in CURATED.rglob("*.jsonl"):
    items = [json.loads(x) for x in jf.read_text(encoding="utf-8").splitlines()]
    # 각 item은 {"title"/"clause_no", "body"} 가정
    chunks = []
    for it in items:
        title = it.get("title") or it.get("clause_no") or ""
        chunks.append( (title, body_clip(it["body"])) )
    if len(chunks) >= 3:
        docs.append(chunks)

with OUT.open("w", encoding="utf-8") as f:
    for chunks in docs:
        for i,(title,body) in enumerate(chunks):
            q = make_query(title, body)
            pos = f"{title}\n{body}".strip()
            # 하드 네거티브: 같은 문서 내 다른 조항
            neg_title, neg_body = random.choice([c for j,c in enumerate(chunks) if j!=i])
            neg = f"{neg_title}\n{neg_body}".strip()
            f.write(json.dumps({"query": q, "positive": pos, "negative": neg}, ensure_ascii=False) + "\n")
print("Wrote", OUT)
