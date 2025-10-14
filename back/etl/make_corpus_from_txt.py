#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, re, argparse
from pathlib import Path

def clean(s: str) -> str:
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def split_regex(text: str):
    # 한국/영문 종결부호 기준 초간단 문장분리 (빠름)
    t = clean(text)
    if not t: return []
    # 종결부호를 보존해서 다시 붙이기
    parts = re.split(r'([.!?…？！。])', t)
    out = []
    for i in range(0, len(parts), 2):
        chunk = parts[i].strip()
        end = parts[i+1] if i+1 < len(parts) else ""
        sent = (chunk + end).strip()
        if len(sent) >= 3:
            out.append(sent)
    return out

def split_kss(text: str):
    # 느리지만 정확; 필요시 사용
    import kss
    return [clean(s) for s in kss.split_sentences(text, num_workers=1)]

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp949", errors="ignore")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw_dir", default="back/data/raw_txt", help="입력 TXT 폴더")
    ap.add_argument("--out", default="back/data/corpus/corpus_sentences.jsonl", help="출력 JSONL 경로")
    ap.add_argument("--fast", action="store_true", help="kss 대신 정규식 분리 사용(권장)")
    args = ap.parse_args()

    RAW_DIR = Path(args.raw_dir)
    OUT = Path(args.out)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    files = [p for p in RAW_DIR.rglob("*") if p.suffix.lower() == ".txt"]
    if not files:
        print(f"[ERR] no .txt files in {RAW_DIR}")
        return

    total = 0
    with OUT.open("w", encoding="utf-8") as out:
        for f in sorted(files):
            txt = read_text(f)
            sents = split_regex(txt) if args.fast else split_kss(txt)
            for i, s in enumerate(sents, start=1):
                rec = {"id": f"{f.stem}#s{i:05d}", "text": s, "meta": {"source": f.name}}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total += 1
            print(f"[OK] {f.name}: {len(sents)} sentences")
    print(f"[DONE] saved {OUT} ({total} sentences)")

if __name__ == "__main__":
    main()
