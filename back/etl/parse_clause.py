#정규식/JSONL로 각 조항 저장

import re, json
from pathlib import Path

TEXT_DIR = Path("data/text")
JSON_DIR = Path("data/json")

def split_clauses(text: str):
    pattern = re.compile(r"(제\d+조.*)")
    parts = pattern.split(text)
    clauses = []
    for i in range(1, len(parts), 2):
        header, body = parts[i], parts[i+1]
        clauses.append({"clause_no": header.strip(), "body": body.strip()})
    return clauses

if __name__ == "__main__":
    for txt in TEXT_DIR.rglob("*.txt"):
        out = JSON_DIR / txt.relative_to(TEXT_DIR)
        out = out.with_suffix(".jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        clauses = split_clauses(txt.read_text(encoding="utf-8"))
        with out.open("w", encoding="utf-8") as f:
            for c in clauses:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

