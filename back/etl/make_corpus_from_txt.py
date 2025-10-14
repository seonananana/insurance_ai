#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, re
from pathlib import Path

RAW_DIR = Path("back/data/raw_txt")
OUT_PATH = Path("back/data/corpus/corpus_sentences.jsonl")

def clean(s: str) -> str:
    s = s.replace("\u3000", " ")  # 전각 공백
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def split_sentences(text: str):
    # kss가 있으면 우선 사용
    try:
        import kss
        for s in kss.split_sentences(text):
            s = clean(s)
            if len(s) >= 5:
                yield s
    except Exception:
        # 매우 단순한 폴백
        for s in re.split(r"(?<=[.!?。…])\s+|\n+", text):
            s = clean(s)
            if len(s) >= 5:
                yield s

def guess_meta_from_name(name: str):
    # 파일명에서 대충 meta 추정 (예: DB_2024-07-01_약관.txt)
    m_policy = re.search(r"(DB손해|현대해상|삼성화재|메리츠|KB손해|한화손해)", name)
    m_date = re.search(r"(20\d{2}[-_.]?\d{2}[-_.]?\d{2})", name)
    return {
        "policy_type": m_policy.group(1) if m_policy else None,
        "rev_date": m_date.group(1).replace("_","-").replace(".","-") if m_date else None,
        "source": name
    }

def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    n_total = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for txt_path in sorted(RAW_DIR.glob("*.txt")):
            # 인코딩 이슈 대응 (utf-8 우선, 실패 시 cp949 시도)
            try:
                raw = txt_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raw = txt_path.read_text(encoding="cp949", errors="ignore")

            meta = guess_meta_from_name(txt_path.name)
            sid = 0
            for sent in split_sentences(raw):
                sid += 1
                rec = {
                    "id": f"{txt_path.stem}#s{sid:05d}",
                    "text": sent,
                    "meta": {k:v for k,v in meta.items() if v}
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_total += 1
    print(f"[OK] Saved {OUT_PATH}  ({n_total} sentences)")

if __name__ == "__main__":
    main()
