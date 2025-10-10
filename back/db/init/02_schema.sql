--DB 스키마에 document_chunks 추가 + pgvector 인덱스
CREATE TABLE IF NOT EXISTS document_chunks (
  id BIGSERIAL PRIMARY KEY,
  doc_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  policy_type TEXT,
  clause_title TEXT,
  content TEXT NOT NULL,
  embedding VECTOR(3072)
);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_ivfflat
  ON document_chunks USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_policy ON document_chunks(policy_type);
