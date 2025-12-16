-- Supabase Database Setup Script
-- Run this in your Supabase SQL Editor

-- Enable pgvector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Create processing_jobs table
CREATE TABLE IF NOT EXISTS public.processing_jobs (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  doc_id text,
  status text DEFAULT 'pending'::text,
  current_stage text DEFAULT 'uploaded'::text,
  progress_info jsonb DEFAULT '{}'::jsonb,
  user_id text,
  error_message text,
  file_storage_path text,
  file_name text,
  file_type text,
  file_size integer,
  metadata jsonb DEFAULT '{}'::jsonb,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT processing_jobs_pkey PRIMARY KEY (id)
);

-- Create document_chunks table
CREATE TABLE IF NOT EXISTS public.document_chunks (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  processing_job_id uuid,
  sharepoint_file_id text,
  file_path text,
  file_name text,
  content text,
  chunk_index integer,
  page_number integer DEFAULT 1,
  char_count integer DEFAULT 0,
  type text[] DEFAULT ARRAY['text'::text],
  original_content jsonb,
  embedding vector(384),  -- 384 dimensions for all-MiniLM-L6-v2
  fts tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, COALESCE(content, ''))) STORED,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT document_chunks_pkey PRIMARY KEY (id),
  CONSTRAINT document_chunks_processing_job_id_fkey 
    FOREIGN KEY (processing_job_id) REFERENCES public.processing_jobs(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON public.processing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_user_id ON public.processing_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_created_at ON public.processing_jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_chunks_job_id ON public.document_chunks(processing_job_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_id ON public.document_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_file_path ON public.document_chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_document_chunks_fts ON public.document_chunks USING GIN(fts);

-- Create index for vector similarity search (cosine distance)
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON public.document_chunks 
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
DROP TRIGGER IF EXISTS update_processing_jobs_updated_at ON public.processing_jobs;
CREATE TRIGGER update_processing_jobs_updated_at
    BEFORE UPDATE ON public.processing_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_document_chunks_updated_at ON public.document_chunks;
CREATE TRIGGER update_document_chunks_updated_at
    BEFORE UPDATE ON public.document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security (RLS)
ALTER TABLE public.processing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;

-- Create policies for service role (BYPASS RLS for backend service)
-- The service uses service_role key which bypasses RLS by default

-- If using anon key for development, create permissive policies:
CREATE POLICY "Allow all operations for anon users on processing_jobs"
  ON public.processing_jobs
  FOR ALL
  TO anon
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Allow all operations for anon users on document_chunks"
  ON public.document_chunks
  FOR ALL
  TO anon
  USING (true)
  WITH CHECK (true);

-- Allow authenticated users as well
CREATE POLICY "Allow all operations for authenticated users on processing_jobs"
  ON public.processing_jobs
  FOR ALL
  TO authenticated
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Allow all operations for authenticated users on document_chunks"
  ON public.document_chunks
  FOR ALL
  TO authenticated
  USING (true)
  WITH CHECK (true);

-- Service role bypasses RLS automatically (no policy needed)

-- Create a view for chunk statistics
CREATE OR REPLACE VIEW public.chunk_statistics AS
SELECT 
  COUNT(*) as total_chunks,
  COUNT(embedding) as chunks_with_embeddings,
  COUNT(*) - COUNT(embedding) as chunks_without_embeddings,
  COUNT(DISTINCT processing_job_id) as total_jobs,
  AVG(char_count) as avg_char_count,
  SUM(char_count) as total_chars
FROM public.document_chunks;

-- Create a view for job statistics
CREATE OR REPLACE VIEW public.job_statistics AS
SELECT 
  status,
  COUNT(*) as count,
  AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_processing_time_seconds
FROM public.processing_jobs
WHERE started_at IS NOT NULL
GROUP BY status;

-- Function to search chunks by embedding similarity
CREATE OR REPLACE FUNCTION search_chunks_by_embedding(
  query_embedding vector(384),
  match_threshold float DEFAULT 0.7,
  match_count int DEFAULT 1
)
RETURNS TABLE (
  id uuid,
  content text,
  similarity float,
  file_name text,
  chunk_index int
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT 
    document_chunks.id,
    document_chunks.content,
    1 - (document_chunks.embedding <=> query_embedding) as similarity,
    document_chunks.file_name,
    document_chunks.chunk_index
  FROM public.document_chunks
  WHERE document_chunks.embedding IS NOT NULL
    AND 1 - (document_chunks.embedding <=> query_embedding) > match_threshold
  ORDER BY document_chunks.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Function for full-text search
CREATE OR REPLACE FUNCTION search_chunks_by_text(
  search_query text,
  match_count int DEFAULT 1
)
RETURNS TABLE (
  id uuid,
  content text,
  rank float,
  file_name text,
  chunk_index int
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT 
    document_chunks.id,
    document_chunks.content,
    ts_rank(document_chunks.fts, websearch_to_tsquery('english', search_query)) as rank,
    document_chunks.file_name,
    document_chunks.chunk_index
  FROM public.document_chunks
  WHERE document_chunks.fts @@ websearch_to_tsquery('english', search_query)
  ORDER BY rank DESC
  LIMIT match_count;
END;
$$;

-- Grant necessary permissions
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated, service_role;

COMMENT ON TABLE public.processing_jobs IS 'Stores document processing job metadata and status';
COMMENT ON TABLE public.document_chunks IS 'Stores document chunks with embeddings and metadata';
COMMENT ON FUNCTION search_chunks_by_embedding IS 'Search chunks by vector similarity using cosine distance';
COMMENT ON FUNCTION search_chunks_by_text IS 'Full-text search across document chunks';

