#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv, json, random, os
from collections import defaultdict

EVAL = "back/data/eval/eval_set.csv"
CORP = "back/data/corpus/corpus_ko_ins.jsonl"
TR   = "back/data/train/train_retriever.jsonl"
VA   = "back/data/train/valid_retriever.jsonl"

# 코퍼스 문장 로드
sents = []
with open(CORP,"r",encoding="utf-8") as f:
    for l in f:
        try:
            rec = json.loads(l)
            sents.append(rec["text"])
        except:
            pass

# 평가 CSV 로드
rows = list(csv.DictReader(open(EVAL,"r",encoding="utf-8")))
# (선택) policy_type 층화 스플릿
by_type = defaultdict(list)
for r in rows:
    by_type[(r.get("policy_type") or "ALL")].append(r)

train_rows, valid_rows = [], []
for _, bucket in by_type.items():
    random.shuffle(bucket)
    cut = max(1, int(len(bucket)*0.8))
    train_rows += bucket[:cut]
    valid_rows += bucket[cut:]

def dump(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as out:
        for r in rows:
            q  = (r.get("question") or "").strip()
            ge = (r.get("ground_evidence") or "").strip()
            if not q or not ge:
                continue
            # 랜덤 네거티브 몇 개(ground_evidence가 포함되지 않도록)
            neg, tries = [], 0
            while len(neg) < 5 and tries < 200:
                tries += 1
                t = random.choice(sents)
                if ge not in t:
                    neg.append(t)
            rec = {"query": q, "pos": [ge], "neg": neg}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("[OK]", path, f"rows={len(rows)}")

dump(train_rows, TR)
dump(valid_rows, VA)
