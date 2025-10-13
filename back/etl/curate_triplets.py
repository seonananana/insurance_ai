#!/usr/bin/env python3
# etl/curate_triplets.py
import os, json, random, glob, re
from pathlib import Path
from typing import List, Dict

BASE = Path(__file__).resolve().parents[1]  # ~/insurance_ai/back
TEXT_DIR = BASE / "data/text"
CURATED_DIR = BASE / "data/curated"
TRAIN_TRIPLETS = BASE / "data/train/triplets.jsonl"
CURATED_CHUNKS = CURATED_DIR / "chunks.jsonl"

CHUNK_SIZE = 300
CHUNK_OVERLAP = 60
SEED = 42

def read_texts() -> Dict[str, str]:
    files = sorted(glob.glob(str(TEXT_DIR / "**/*.txt"), recursive=True))
    data = {}
    for f in files:
        try:
            s = Path(f).read_text(encoding="utf-8", errors="ignore")
            s = re.sub(r"\s+", " ", s).strip()
            if len(s) > 0:
                data[Path(f).stem] = s
        except Exception:
            pass
    return data

def chunk_text(s: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    chunks = []
    i = 0
    while i < len(s):
        j = min(len(s), i + size)
        chunk = s[i:j].strip()
        if len(chunk) >= max(80, size // 3):  # 너무 짧은 조각 제거
            chunks.append(chunk)
        if j == len(s):
            break
        i = j - overlap
        if i < 0:
            i = 0
        if i >= len(s):
            break
    return chunks

def ensure_dirs():
    os.makedirs(CURATED_DIR, exist_ok=True)
    os.makedirs(TRAIN_TRIPLETS.parent, exist_ok=True)

def build_chunks(all_docs: Dict[str, str]) -> List[Dict]:
    rows = []
    for doc_id, s in all_docs.items():
        chunks = chunk_text(s)
        for idx, c in enumerate(chunks):
            rows.append({"doc_id": doc_id, "idx": idx, "text": c})
    return rows

def build_triplets(rows: List[Dict], per_anchor: int = 2) -> List[Dict]:
    # 같은 문서 이웃 → positive, 다른 문서 랜덤 → negative
    random.seed(SEED)
    by_doc = {}
    for r in rows:
        by_doc.setdefault(r["doc_id"], []).append(r)
    for k in by_doc:
        by_doc[k].sort(key=lambda x: x["idx"])

    all_doc_ids = list(by_doc.keys())
    triplets = []
    for doc_id, chunks in by_doc.items():
        others = [d for d in all_doc_ids if d != doc_id]
        if not others:
            # 문서가 하나뿐이면 랜덤 네거티브를 전체에서 뽑기
            others = all_doc_ids

        for i, r in enumerate(chunks):
            # 후보 positive: 이웃(±1, ±2)
            pos_candidates = []
            for off in [1, -1, 2, -2]:
                j = i + off
                if 0 <= j < len(chunks):
                    pos_candidates.append(chunks[j]["text"])
            if not pos_candidates:
                continue
            positives = random.sample(pos_candidates, k=min(per_anchor, len(pos_candidates)))

            # negatives
            for p in positives:
                neg_doc = random.choice(others)
                neg = random.choice(by_doc[neg_doc])["text"]
                triplets.append({
                    "anchor": r["text"],
                    "positive": p,
                    "negative": neg,
                    "meta": {"anchor_doc": doc_id, "neg_doc": neg_doc}
                })
    return triplets

def main():
    ensure_dirs()
    docs = read_texts()
    if not docs:
        print(f"[warn] No .txt found in {TEXT_DIR}. Put some txt files first.")
        # 그래도 파이프라인이 끊기지 않게 더미 샘플 1건 생성
        ensure_dirs()
        dummy = {
            "anchor": "질병으로 입원했을 때 실손의료보험금 지급 기준을 확인합니다.",
            "positive": "실손 의료비 보장은 실제 부담한 의료비를 한도로 보상합니다.",
            "negative": "자동차 보험은 자동차 사고로 인한 손해를 담보합니다.",
            "meta": {"anchor_doc": "dummy", "neg_doc": "dummy2"}
        }
        CURATED_CHUNKS.write_text("", encoding="utf-8")
        with TRAIN_TRIPLETS.open("w", encoding="utf-8") as f:
            f.write(json.dumps(dummy, ensure_ascii=False) + "\n")
        print(f"[info] wrote 1 dummy triplet → {TRAIN_TRIPLETS}")
        return

    rows = build_chunks(docs)
    with CURATED_CHUNKS.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[ok] chunks → {CURATED_CHUNKS}  (rows={len(rows)})")

    triplets = build_triplets(rows, per_anchor=2)
    with TRAIN_TRIPLETS.open("w", encoding="utf-8") as f:
        for t in triplets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"[ok] triplets → {TRAIN_TRIPLETS}  (rows={len(triplets)})")

if __name__ == "__main__":
    main()
