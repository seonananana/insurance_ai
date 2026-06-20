
- Built an insurance-domain RAG system
- Processed and indexed insurance policy PDFs
- Improved retrieval performance with re-ranking
- Delivered explainable answers with supporting clauses
  
# INSURANCE AI

AI-powered insurance assistant that provides personalized insurance consultation, policy search, and claim guidance using Retrieval-Augmented Generation (RAG).

## Overview

INSURANCE AI helps users understand complex insurance policies by retrieving relevant clauses from insurance documents and generating accurate, evidence-based answers.

## Features

- Insurance policy Q&A
- Policy document retrieval with RAG
- Semantic search using vector embeddings
- Evidence-based responses with source clauses
- Insurance claim guidance
- PDF document processing pipeline

## Architecture

Insurance Documents (PDF)
        ↓
   Text Chunking
        ↓
    Embedding
        ↓
 PostgreSQL + pgvector
        ↓
 Vector Search
        ↓
    Re-ranking
        ↓
        LLM
        ↓
 Generated Response

## Tech Stack

### Backend
- Python
- FastAPI

### Database
- PostgreSQL
- pgvector

### AI / NLP
- E5 Embedding Model
- RAG (Retrieval-Augmented Generation)
- Vector Similarity Search
- Re-ranking

### Infrastructure
- Docker

## Key Contributions

- Built PDF-to-vector ETL pipeline
- Implemented semantic search for insurance policies
- Improved retrieval accuracy through re-ranking
- Developed evidence-based insurance consultation workflow
- Optimized Korean insurance document retrieval

## Example Query

**User**
> 암 진단을 받으면 이 보험에서 얼마를 받을 수 있나요?

**System**
> 관련 약관을 검색한 결과, 암 진단 시 최초 1회에 한하여 진단금이 지급됩니다.
>
> 근거 조항:
> 제12조 암 진단보험금 지급 사유 ...

## Future Work

- Multi-insurance comparison
- Personalized insurance recommendations
- Claim automation
- Fine-tuned insurance-specific LLM

## License

MIT License
