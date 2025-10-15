#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, json, math, argparse, csv
from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd
from rouge_score import rouge_scorer
from sentence_transformers import SentenceTransformer, util

os.environ.setdefault("CUDA_VISIBLE_DEVICES","")
os.environ.setdefault("ACCELERATE_USE_MPS_DEVICE","false")
os.environ.setdefault("ACCELERATE_MIXED_PRECISION","no")
os.environ.setdefault("TOKENIZERS_PARALLELISM","false")

def read_csv(path: str) -> List[Dict[str, str]]:
    rows=[]
    with open(path, "r", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for r in rd:
            rows.append({
                "id": (r.get("id") or "").strip(),
                "policy_type": (r.get("policy_type") or "").strip(),
                "question": (r.get("question") or "").strip(),
                "ground_truth": (r.get("ground_truth") or "").strip(),
                "ground_evidence": (r.get("ground_evidence") or "").strip(),
            })
    return rows

def read_jsonl(path: str) -> Dict[str, Dict[str, Any]]:
    out={}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            o=json.loads(line)
            i=str(o.get("id","")).strip()
            if not i: continue
            ans=(o.get("answer") or "").strip()
            src=o.get("sources") or []
            src_texts=[]
            for s in src:
                if isinstance(s, dict):
                    t=(s.get("content") or s.get("text") or s.get("chunk") or "")
                else:
                    t=str(s)
                t=str(t).strip()
                if t: src_texts.append(t)
            out[i]={"answer": ans, "sources": src_texts}
    return out

def _normalize_strict(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\"\'`”“’‘·…•\-$begin:math:text$$end:math:text$$begin:math:display$$end:math:display$\{\},.;:!?/\\]", "", s)
    return s

def _normalize_ko_loose(s: str) -> str:
    s = (s or "")
    s = re.sub(r"[\"\'`”“’‘·…•,.;:!?/\\\-\(\)\[\]\{\}]", " ", s)
    s = re.sub(r"(입니다|이다|합니다|하였습니다|합니다\.|이다\.|됨|임)$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def rougeL_recall(ref: str, hyp: str, ko_loose: bool=False) -> float:
    if not ref or not hyp: return float("nan")
    if ko_loose:
        ref = _normalize_ko_loose(ref)
        hyp = _normalize_ko_loose(hyp)
    sc = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=False)
    r = sc.score(ref, hyp)['rougeL']
    return r.recall

def gt_in_sources(gt: str, sources: List[str], ko_loose: bool=False) -> float:
    if not gt or not sources: return float("nan")
    if ko_loose:
        tgt  = _normalize_ko_loose(gt)
        pool = _normalize_ko_loose(" ".join(sources))
    else:
        tgt  = _normalize_strict(gt)
        pool = _normalize_strict(" ".join(sources))
    return 1.0 if tgt and tgt in pool else 0.0

def embed_model(name: str):
    return SentenceTransformer(name, device="cpu")

def cosine_sim(m: SentenceTransformer, a: str, b: str) -> float:
    if not a or not b: return float("nan")
    ea = m.encode([a], normalize_embeddings=True)
    eb = m.encode([b], normalize_embeddings=True)
    return float(util.cos_sim(ea, eb)[0][0])

def evaluate(eval_rows, baseline_pred, rag_pred, sim_model_name:str, ko_loose: bool):
    sim_m = embed_model(sim_model_name)
    recs=[]
    for r in eval_rows:
        i   = r["id"]; gt  = r["ground_truth"]; ge  = r["ground_evidence"]
        q   = r["question"]; pol = r["policy_type"]
        base = baseline_pred.get(i, {"answer":"", "sources":[]})
        rag  = rag_pred.get(i, {"answer":"", "sources":[]})

        sim_base = cosine_sim(sim_m, gt, base["answer"])
        sim_rag  = cosine_sim(sim_m, gt, rag["answer"])
        rouge_base = rougeL_recall(ge, base["answer"], ko_loose) if ge else float("nan")
        rouge_rag  = rougeL_recall(ge, rag["answer"],  ko_loose) if ge else float("nan")
        gts_base = float("nan")
        gts_rag  = gt_in_sources(gt, rag["sources"], ko_loose)

        recs.append({
            "id": i, "policy_type": pol, "question": q,
            "ground_truth": gt, "ground_evidence": ge,
            "baseline_answer": base["answer"], "rag_answer": rag["answer"],
            "sem_sim_baseline": sim_base, "sem_sim_rag": sim_rag,
            "evid_rougeL_recall_baseline": rouge_base,
            "evid_rougeL_recall_rag": rouge_rag,
            "gt_in_sources_baseline": gts_base, "gt_in_sources_rag": gts_rag,
        })
    df = pd.DataFrame.from_records(recs)

    def mean_nan(x): 
        x = pd.Series(x).dropna()
        return float(x.mean()) if len(x) else float("nan")

    summary = {
        "count": len(df),
        "sem_sim_baseline": mean_nan(df["sem_sim_baseline"]),
        "sem_sim_rag":      mean_nan(df["sem_sim_rag"]),
        "evid_rougeL_recall_baseline": mean_nan(df["evid_rougeL_recall_baseline"]),
        "evid_rougeL_recall_rag":      mean_nan(df["evid_rougeL_recall_rag"]),
        "gt_in_sources_rag":           mean_nan(df["gt_in_sources_rag"]),
        "improve_sem_sim":             mean_nan(df["sem_sim_rag"]) - mean_nan(df["sem_sim_baseline"]),
        "improve_evid_rougeL":         mean_nan(df["evid_rougeL_recall_rag"]) - mean_nan(df["evid_rougeL_recall_baseline"]),
    }
    return df, summary

def verdict_sem(sim: float) -> str:
    if math.isnan(sim): return "N/A"
    if sim >= 0.85: return "매우정확"
    if sim >= 0.70: return "대체로맞음"
    return "부정확/오답"

def verdict_evid(rouge: float, gts: float) -> str:
    ok_r = (not math.isnan(rouge)) and (rouge >= 0.50)
    ok_g = (not math.isnan(gts)) and (gts >= 0.60)
    if ok_r and ok_g: return "근거활용 양호"
    if ok_r: return "부분활용"
    return "미흡/없음"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval_csv", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--rag", required=True)
    ap.add_argument("--sim_model", default="intfloat/multilingual-e5-small")
    ap.add_argument("--out_dir", default="back/eval/out")
    ap.add_argument("--ko_loose", action="store_true")
    args = ap.parse_args()

    eval_rows = read_csv(args.eval_csv)
    base_pred = read_jsonl(args.baseline)
    rag_pred  = read_jsonl(args.rag)

    df, summary = evaluate(eval_rows, base_pred, rag_pred, args.sim_model, args.ko_loose)

    df["verdict_sem_baseline"] = df["sem_sim_baseline"].map(verdict_sem)
    df["verdict_sem_rag"]      = df["sem_sim_rag"].map(verdict_sem)
    df["verdict_evidence_rag"] = [verdict_evid(r, g) for r,g in zip(df["evid_rougeL_recall_rag"], df["gt_in_sources_rag"])]

    os.makedirs(args.out_dir, exist_ok=True)
    out_csv  = os.path.join(args.out_dir, "eval_detail.csv")
    out_json = os.path.join(args.out_dir, "metrics_summary.json")
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    with open(out_json,"w",encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n=== RAG 성능평가 요약 ===")
    print(f"[count] {summary['count']}")
    print("[baseline_chatgpt]")
    print(f"- sem_sim_mean: {summary['sem_sim_baseline']:.3f}")
    print(f"- evidence_coverage_mean(rougeL_recall): {summary['evid_rougeL_recall_baseline']:.3f}")
    print("[rag_system]")
    print(f"- sem_sim_mean: {summary['sem_sim_rag']:.3f}")
    print(f"- evidence_coverage_mean(rougeL_recall): {summary['evid_rougeL_recall_rag']:.3f}")
    print(f"- gt_in_sources_mean: {summary['gt_in_sources_rag']:.3f}")
    print("\n[improvements]")
    print(f"- Δ sem_sim: {summary['improve_sem_sim']:+.3f}")
    print(f"- Δ evidence_rougeL: {summary['improve_evid_rougeL']:+.3f}")
    print(f"\n[FILES] detail: {out_csv}\n        summary: {out_json}")
if __name__ == "__main__":
    main()
