import argparse, json, random, os, re
try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except Exception:
    HAS_BM25 = False

def read_jsonl(p):
    with open(p,"r",encoding="utf-8") as f:
        for l in f:
            l=l.strip()
            if l: yield json.loads(l)

def to_query(s: str) -> str:
    s = s.strip()
    if s.endswith(("다.","요.",".")): s = s[:-1]
    if not s.endswith("?"): s += "?"
    return s

def tokenize(s: str):
    s = s.lower()
    s = re.sub(r"[^0-9a-z가-힣]+"," ",s)
    return s.split()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="back/data/corpus/corpus_ko_ins.jsonl")
    ap.add_argument("--out", default="back/data/train/train_retriever.jsonl")
    ap.add_argument("--valid", default="back/data/train/valid_retriever.jsonl")
    ap.add_argument("--split", type=float, default=0.8)
    ap.add_argument("--neg", choices=["random","bm25"], default="bm25")
    ap.add_argument("--neg-num", type=int, default=20)
    ap.add_argument("--neg-topk", type=int, default=50)
    args = ap.parse_args()

    src=args.src
    if not os.path.exists(src):
        alt="back/data/corpus/corpus_sentences.jsonl"
        if os.path.exists(alt): src=alt
        else: raise SystemExit(f"[ERR] corpus not found: {args.src} / {alt}")

    docs=[(rec.get("text") or "").strip() for rec in read_jsonl(src)]
    docs=[t for t in docs if t]
    if not docs: raise SystemExit("[ERR] empty corpus")

    if args.neg=="bm25":
        if not HAS_BM25:
            print("[WARN] rank-bm25 미설치 → 랜덤 네거로 대체 (pip install rank-bm25)")
            args.neg="random"
        else:
            bm25 = BM25Okapi([tokenize(x) for x in docs])

    random.shuffle(docs)
    cut=max(100,int(len(docs)*args.split))
    train_docs=docs[:cut]
    valid_docs=docs[cut:cut+max(500,len(docs)//10)]

    def pick_negs(q_text):
        if args.neg=="random":
            k=min(args.neg_num,len(docs))
            return random.sample(docs,k=k)
        # bm25
        scores=bm25.get_scores(tokenize(q_text))
        idx=sorted(range(len(scores)), key=lambda i:-scores[i])[:args.neg_topk]
        res=[]
        for i in idx:
            t=docs[i]
            if t!=q_text and t not in res:
                res.append(t)
            if len(res)>=args.neg_num: break
        if not res:
            k=min(args.neg_num,len(docs))
            res=random.sample(docs,k=k)
        return res

    def dump(subset,path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        n=0
        with open(path,"w",encoding="utf-8") as out:
            for p in subset:
                q=to_query(p)
                negs=pick_negs(q)
                out.write(json.dumps({"query":q,"pos":[p],"neg":negs},ensure_ascii=False)+"\n")
                n+=1
        print(f"[OK] {path} rows={n}")

    dump(train_docs, args.out)
    dump(valid_docs, args.valid)

if __name__=="__main__":
    main()
