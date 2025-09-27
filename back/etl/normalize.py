#키워드/정규식 기반 분류
#지급한다, 보장한다 → coverage/면책, 제외한다 → exclusion/특약 → rider

import json, re
from pathlib import Path

JSON_DIR = Path("data/json")
CURATED_DIR = Path("data/curated")

def classify_clause(body: str):
    if re.search(r"특약", body): return "rider"
    if re.search(r"면책|제외", body): return "exclusion"
    if re.search(r"지급|보장", body): return "coverage"
    return "other"

if __name__ == "__main__":
    for jf in JSON_DIR.rglob("*.jsonl"):
        out = CURATED_DIR / jf.relative_to(JSON_DIR)
        out.parent.mkdir(parents=True, exist_ok=True)
        with jf.open(encoding="utf-8") as fin, out.open("w", encoding="utf-8") as fout:
            for line in fin:
                c = json.loads(line)
                c["type"] = classify_clause(c["body"])
                fout.write(json.dumps(c, ensure_ascii=False) + "\n")
