#ETL 한 방에 끝 — PDF → 청크 → 임베딩 → DB
import os, re
from pathlib import Path
from typing import List
import fitz  # PyMuPDF
from sqlalchemy import create_engine, text as sql
from app.services.embeddings_factory import get_embeddings_client

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ENGINE = create_engine(os.environ["DATABASE_URL"])
EMB = get_embeddings_client()

def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text("text") for page in doc)

def simple_chunk(text: str, max_chars: int = 1400) -> List[str]:
    parts = re.split(r"(\n{2,}|[.!?])", text)
    chunks, buf = [], ""
    for p in parts:
        if len(buf) + len(p) > max_chars and buf:
            chunks.append(buf.strip()); buf = p
        else:
            buf += p
    if buf.strip(): chunks.append(buf.strip())
    merged, acc = [], ""
    for c in chunks:
        if len(acc) + len(c) < max_chars//2:
            acc += ("" if not acc else "\n") + c
        else:
            if acc: merged.append(acc); acc = ""
            merged.append(c)
    if acc: merged.append(acc)
    return [c for c in merged if len(c) >= 80]

def main():
    pdfs = sorted(DATA_DIR.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDFs under {DATA_DIR}"); return
    with ENGINE.begin() as conn:
        for pdf in pdfs:
            policy_type = pdf.parent.name  # 상위 폴더명 분류
            doc_id = pdf.stem
            print(f"[ingest] {pdf}")
            text = extract_text(pdf)
            chunks = simple_chunk(text)
            embs = EMB.embed(chunks)
            for i, (c,e) in enumerate(zip(chunks, embs)):
                conn.execute(sql("""
                    INSERT INTO document_chunks
                      (doc_id, chunk_id, policy_type, clause_title, content, embedding)
                    VALUES (:doc_id, :chunk_id, :policy_type, :title, :content, :embedding)
                """), dict(doc_id=doc_id, chunk_id=str(i), policy_type=policy_type,
                           title=None, content=c, embedding=e))
            print(f"  -> chunks={len(chunks)}")
if __name__ == "__main__":
    main()
