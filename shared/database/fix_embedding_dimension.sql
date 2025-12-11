-- Fix embedding dimension mismatch and add doc_id column
-- Change from 1536 (OpenAI) to 384 (sentence-transformers/all-MiniLM-L6-v2)

-- Drop the existing embedding column
ALTER TABLE public.document_chunks DROP COLUMN IF EXISTS embedding;

-- Add doc_id column if it doesn't exist
ALTER TABLE public.document_chunks 
ADD COLUMN IF NOT EXISTS doc_id text;

-- Add embedding column back with correct dimensions (384)
ALTER TABLE public.document_chunks 
ADD COLUMN embedding vector(384);

-- Create index on doc_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_id ON public.document_chunks(doc_id);

-- Recreate the vector index
DROP INDEX IF EXISTS idx_document_chunks_embedding;
CREATE INDEX idx_document_chunks_embedding ON public.document_chunks 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Verify the changes
SELECT column_name, data_type, udt_name 
FROM information_schema.columns 
WHERE table_name = 'document_chunks' AND column_name IN ('embedding', 'doc_id')
ORDER BY column_name;

