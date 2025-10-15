#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retriever fine-tuning (E5/SBERT) — CPU-safe manual loop.
Input(train/valid): JSONL lines like {"query":"...", "pos":["..."], "neg":["..."]}

Run:
  python back/train/train_retriever.py \
    --train back/data/train/train_retriever.jsonl \
    --valid back/data/train/valid_retriever.jsonl \
    --out   back/models/ins-match-embed \
    --base  intfloat/multilingual-e5-small \
    --epochs 1 --max-samples 1000 --batch 2 --max-len 64 --device cpu
"""

import os, json, time, random, argparse
from typing import List, Dict
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("ACCELERATE_USE_MPS_DEVICE", "false")
os.environ.setdefault("ACCELERATE_MIXED_PRECISION", "no")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from torch.utils.data import DataLoader
from sentence_transformers import SentenceTransformer, InputExample, losses

def read_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line: yield json.loads(line)

def build_train_examples(path: str, max_samples: int) -> List[InputExample]:
    ex=[]
    for r in read_jsonl(path):
        q=(r.get("query") or "").strip()
        pos=r.get("pos") or []
        if q and pos:
            ex.append(InputExample(texts=[f"query: {q}", f"passage: {pos[0]}"]))
        if len(ex)>=max_samples: break
    random.shuffle(ex); return ex

@torch.no_grad()
def eval_recall_at_k(valid_path: str, model: SentenceTransformer, k_values=(1,3,5,10)) -> Dict[int,float]:
    import numpy as np
    def norm(x): n=np.linalg.norm(x,axis=1,keepdims=True)+1e-12; return x/n
    hits={k:0 for k in k_values}; total=0
    for r in read_jsonl(valid_path):
        q=(r.get("query") or "").strip()
        pos=r.get("pos") or []
        neg=r.get("neg") or []
        if not q or not pos: continue
        cands=[pos[0]]+list(neg)
        if not cands: continue
        texts=[f"query: {q}"]+[f"passage: {t}" for t in cands]
        embs=model.encode(texts, normalize_embeddings=True).astype("float32")
        qe, de=embs[0:1], embs[1:]
        scores=(qe@de.T)[0]
        order=np.argsort(-scores)
        pos_rank=int(np.where(order==0)[0][0])+1
        total+=1
        for k in k_values:
            if pos_rank<=k: hits[k]+=1
    return {k:(hits[k]/total if total else 0.0) for k in k_values}

def train(train_path, valid_path, out_dir, base_model="intfloat/multilingual-e5-small",
          device="cpu", epochs=1, batch_size=2, max_len=64, lr=2e-5,
          max_samples=1000, early_stop_loss=1e-3, patience=2,
          steps_per_epoch=0, save_every=500):
    device=device.lower()
    if device not in {"cpu","cuda","mps"}: device="cpu"
    print(f"[INFO] base={base_model} device={device}")

    train_ex=build_train_examples(train_path, max_samples=max_samples)
    if not train_ex: raise SystemExit(f"[ERR] empty/invalid train file: {train_path}")
    print(f"[INFO] train samples: {len(train_ex)}")

    model=SentenceTransformer(base_model, device=device)
    model.max_seq_length=max_len
    loss_fn=losses.MultipleNegativesRankingLoss(model)
    loader=DataLoader(train_ex, batch_size=batch_size, shuffle=True, drop_last=True,
                      collate_fn=model.smart_batching_collate)

    opt=torch.optim.AdamW(model.parameters(), lr=lr)
    steps_ep = len(loader) if steps_per_epoch<=0 else min(steps_per_epoch, len(loader))
    total_steps = steps_ep * epochs
    print(f"[INFO] epochs={epochs} batch={batch_size} steps/epoch={steps_ep} total={total_steps}")

    model.train(); step=0; low_cnt=0; t0=time.time(); running=0.0
    for ep in range(epochs):
        step_in_ep=0
        for features, labels in loader:
            for feat in features:
                for k,v in feat.items():
                    if isinstance(v, torch.Tensor): feat[k]=v.to(device)
            loss=loss_fn(features, labels)
            lv=float(loss.detach().cpu().item())
            running+=lv
            opt.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
            step+=1; step_in_ep+=1

            if step%100==0:
                avg=running/100.0; running=0.0
                print(f"[epoch {ep+1}/{epochs}] step {step}/{total_steps} loss={avg:.4f} elapsed={int(time.time()-t0)}s", flush=True)
                if avg<early_stop_loss:
                    low_cnt+=1
                    if low_cnt>=patience:
                        print("[INFO] early stop triggered."); ep=epochs; break
                else:
                    low_cnt=0

            if save_every>0 and step%save_every==0:
                os.makedirs(out_dir, exist_ok=True); model.save(out_dir)
                print(f"[CKPT] saved -> {out_dir}")

            if steps_per_epoch>0 and step_in_ep>=steps_per_epoch: break

    os.makedirs(out_dir, exist_ok=True); model.save(out_dir)
    print(f"[OK] saved model -> {out_dir}")

    if valid_path and os.path.exists(valid_path):
        print("[INFO] evaluating valid (Recall@1/3/5/10)...")
        rk=eval_recall_at_k(valid_path, model, k_values=(1,3,5,10))
        print(" ".join([f"R@{k}={rk[k]:.3f}" for k in (1,3,5,10)]))

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument("--train", required=True)
    p.add_argument("--valid", default="")
    p.add_argument("--out",   default="back/models/ins-match-embed")
    p.add_argument("--base",  default=os.getenv("E5_BASE","intfloat/multilingual-e5-small"))
    p.add_argument("--device", default="cpu", choices=["cpu","mps","cuda"])
    p.add_argument("--epochs", type=int, default=int(os.getenv("EPOCHS","1")))
    p.add_argument("--batch",  type=int, default=int(os.getenv("BATCH","2")))
    p.add_argument("--max-len",type=int, default=int(os.getenv("MAX_LEN","64")))
    p.add_argument("--lr",     type=float, default=float(os.getenv("LR","2e-5")))
    p.add_argument("--max-samples", type=int, default=int(os.getenv("MAX_SAMPLES","1000")))
    p.add_argument("--early-stop-loss", type=float, default=float(os.getenv("EARLY_STOP_LOSS","1e-3")))
    p.add_argument("--patience", type=int, default=int(os.getenv("PATIENCE","2")))
    p.add_argument("--steps-per-epoch", type=int, default=int(os.getenv("STEPS_PER_EPOCH","0")))
    p.add_argument("--save-every", type=int, default=int(os.getenv("SAVE_EVERY","500")))
    return p.parse_args()

if __name__=="__main__":
    args=parse_args()
    train(train_path=args.train, valid_path=args.valid, out_dir=args.out, base_model=args.base,
          device=args.device, epochs=args.epochs, batch_size=args.batch, max_len=args.max_len,
          lr=args.lr, max_samples=args.max_samples, early_stop_loss=args.early_stop_loss,
          patience=args.patience, steps_per_epoch=args.steps_per_epoch, save_every=args.save_every)
