#!/usr/bin/env python3
# etl/make_training_pairs.py
import json, glob, re, random
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple, List

BASE = Path(__file__).resolve().parents[1]   # ~/insurance_ai/back
CURATED_CHUNKS = BASE / "data/curated/chunks.jsonl"
OUT_PAIRS = BASE / "data/train/pairs.jsonl"

MIN_LEN = 40       # 너무 짧은 문장 제거
SEED = 42

# 우선순위로 본문 후보 키들
BODY_KEYS = ["body", "text", "content", "clause", "description", "paragraph"]

def body_clip(s: str, max_chars: int = 1000) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s

def extract_body(item: Dict[str, Any]) -> Tuple[str, str]:
    """(title, body) 반환. title은 없으면 빈 문자열."""
    title = item.get("title") or item.get("heading") or ""
    for k in BODY_KEYS:
        if k in item and isinstance(item[k], str) and item[k].strip():
            return title, item[k]
    # 혹시 nested 구조 (예: item["data"]["text"])도 대응
    data = item.get("data")
    if isinstance(data, dict):
        for k in BODY_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return title, v
    raise KeyError("no_body_like_field")

def load_policy_jsons() -> Iterable[Dict[str, Any]]:
    # 필요 시 경로 패턴 조정
    for path in glob.glob(str(BASE / "data" / "policies" / "*.json")):
        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                yield obj
            elif isinstance(obj, list):
                for it in obj:
                    if isinstance(it, dict):
                        yield it
        except Exception:
            continue

def load_curated_chunks() -> List[str]:
    texts = []
    if CURATED_CHUNKS.exists():
        with CURATED_CHUNKS.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    it = json.loads(line)
                    t = it.get("text")
                    if isinstance(t, str) and len(t.strip()) >= MIN_LEN:
                        texts.append(body_clip(t))
                except Exception:
                    pass
    return texts

def build_pairs_from_chunks(chunks: List[str]) -> List[Tuple[str, str]]:
    """이웃 청크를 양/양(pair)로 묶어서 query-pos 생성."""
    pairs = []
    for i, t in enumerate(chunks):
        # 좌/우 이웃 중 하나를 positive로
        neighbors = []
        if i - 1 >= 0: neighbors.append(chunks[i - 1])
        if i + 1 < len(chunks): neighbors.append(chunks[i + 1])
        for pos in neighbors:
            if len(t) >= MIN_LEN and len(pos) >= MIN_LEN and t != pos:
                pairs.append((t, pos))
    return pairs

def build_pairs_from_policies() -> List[Tuple[str, str]]:
    """정책 JSON에서 (제목↔본문) 또는 (본문↔본문 일부) 페어 생성."""
    pairs = []
    for it in load_policy_jsons():
        try:
            title, body = extract_body(it)
        except KeyError:
            continue
        body = body_clip(body)
        if len(body) < MIN_LEN:
            continue
        # 제목이 있으면 (제목 → 본문) 페어
        if title and len(title.strip()) >= 5:
            pairs.append((title.strip(), body))
        # 본문 내 문장 스플릿으로 (본문 일부 → 본문) 페어도 생성
        sents = re.split(r"(?<=[.!?]|[.] [가-힣])\s+", body)
        sents = [s.strip() for s in sents if len(s.strip()) >= MIN_LEN]
        for s in sents[:3]:  # 과도 생성 방지
            pairs.append((s, body))
    return pairs

def dedup_pairs(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    seen = set()
    out = []
    for q, p in pairs:
        key = (q, p)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out

def main():
    random.seed(SEED)
    # 1) curated/chunks.jsonl 우선 활용
    chunks = load_curated_chunks()
    pairs = build_pairs_from_chunks(chunks)

    # 2) policies/*.json 등도 있으면 추가
    pairs += build_pairs_from_policies()

    pairs = dedup_pairs(pairs)
    OUT_PAIRS.parent.mkdir(parents=True, exist_ok=True)

    if not pairs:
        # 더미 1건이라도 만들어서 학습 파이프라인 안 끊기게
        dummy_q = "실손의료보험의 보장 범위를 알고 싶습니다."
        dummy_p = "실손의료보험은 실제 부담한 의료비를 한도로 보상하며 약관의 보장 제외 사항을 확인해야 합니다."
        pairs = [(dummy_q, dummy_p)]

    with OUT_PAIRS.open("w", encoding="utf-8") as f:
        for q, p in pairs:
            f.write(json.dumps({"query": q, "pos": p}, ensure_ascii=False) + "\n")

    print(f"[ok] wrote {len(pairs)} pairs → {OUT_PAIRS}")

if __name__ == "__main__":
    main()
