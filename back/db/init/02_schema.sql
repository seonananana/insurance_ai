-- 1️⃣ 인덱스 먼저 삭제
DROP INDEX IF EXISTS idx_doc_chunks_ivfflat;

-- 2️⃣ embedding 차원 수정 (기존 테이블 재사용)
ALTER TABLE document_chunks
  ALTER COLUMN embedding TYPE vector(768);

-- 3️⃣ IVF Flat 인덱스 다시 생성
CREATE INDEX idx_doc_chunks_ivfflat
  ON document_chunks
  USING ivfflat (embedding vector_l2_ops)
  WITH (lists = 100);

-- 4️⃣ (선택) policy_type 인덱스 유지
CREATE INDEX IF NOT EXISTS idx_doc_chunks_policy ON document_chunks(policy_type);
