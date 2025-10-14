import os, math
from sqlalchemy import create_engine, text as sql
from app.services.embeddings_sbert import SBertEmbeddings

DATABASE_URL = os.environ["DATABASE_URL"]  # 반드시 설정되어 있어야 함
BATCH = int(os.getenv("BATCH", "64"))

def main():
    eng = create_engine(DATABASE_URL)
    embedder = SBertEmbeddings(os.getenv("SBERT_MODEL_DIR") or "intfloat/e5-base-v2",
                               device=os.getenv("EMBED_DEVICE","cpu"))

    with eng.begin() as cx:
        total = cx.execute(sql("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL")).scalar()
        print(f"[backfill] NULL embeddings: {total}")
        if not total:
            return

        # PK가 id라고 가정. 없다면 doc_id+chunk_id로 바꿔도 됨.
        rows = cx.execute(sql("""
            SELECT id, content
            FROM document_chunks
            WHERE embedding IS NULL
            ORDER BY id
        """)).fetchall()

    # 배치 임베딩
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    for batch in chunks(rows, BATCH):
        ids = [r[0] for r in batch]
        texts = [r[1] or "" for r in batch]
        vecs = embedder.embed(texts)
        # pgvector는 real[] 캐스팅 → vector(768)
        vecs_sql = [f"'[{','.join(f'{x:.6f}' for x in v)}]'" for v in vecs]
        values = ",".join(f"({i}, {v}::vector(768))" for i, v in zip(ids, vecs_sql))
        up = f"""
        UPDATE document_chunks AS t
        SET embedding = v.embedding
        FROM (VALUES {values}) AS v(id, embedding)
        WHERE t.id = v.id;
        """
        with create_engine(DATABASE_URL).begin() as cx2:
            cx2.execute(sql(up))
        print(f"[backfill] updated {len(ids)} rows")

    with create_engine(DATABASE_URL).begin() as cx:
        left = cx.execute(sql("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL")).scalar()
        print(f"[backfill] done. remaining NULL: {left}")

if __name__ == "__main__":
    main()
