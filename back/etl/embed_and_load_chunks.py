# document_chunks용 간단 적재 스크립트 골격=>벡터 검색 테이블
# back/etl/embed_and_load_chunks.py
import os, json
from pathlib import Path
from sqlalchemy import create_engine, text
from openai import OpenAI

ENGINE = create_engine(os.environ["DATABASE_URL"])
OPENAI = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "curated"

def embed(txt:str):
    r = OPENAI.embeddings.create(model="text-embedding-3-small", input=txt)
    return r.data[0].embedding

with ENGINE.begin() as conn:
    for jf in JSON_DIR.rglob("*.jsonl"):
        policy_type = jf.parts[-2]  # 예: .../curated/<insurer>/<file>.jsonl → 필요시 매핑
        doc_id = jf.stem
        with jf.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                c = json.loads(line)
                vec = embed(c["body"])
                conn.execute(
                    text("""
                    INSERT INTO document_chunks (doc_id, chunk_id, policy_type, clause_title, content, embedding)
                    VALUES (:doc_id, :chunk_id, :policy_type, :title, :content, :embedding)
                    """),
                    dict(doc_id=doc_id, chunk_id=str(i), policy_type=policy_type,
                         title=c.get("clause_no") or c.get("title"), content=c["body"], embedding=vec)
                )
