-- Migration to enhance keyword search with partial matching and camelCase support
-- This adds ILIKE fallback for cases where FTS doesn't match (e.g., camelCase, partial words)
-- 
-- BACKUP STRATEGY:
-- These are NEW functions with _enhanced suffix to keep old functions as backup:
--   - keyword_search_chunks (old) → keyword_search_chunks_enhanced (new)
--   - fuzzy_search_chunks_enhanced (new function)
-- 
-- If the enhanced functions don't work, you can:
--   1. Revert Python code to call original function names
--   2. Or drop the _enhanced functions and keep using the old ones
--   3. Old functions remain untouched and functional

-- Enhanced Keyword Search Function with fallback to ILIKE
CREATE OR REPLACE FUNCTION keyword_search_chunks_enhanced(
    query_text text,
    filter_doc_ids uuid[] DEFAULT NULL,
    match_count int DEFAULT 1
)
RETURNS TABLE (
    id uuid,
    doc_id uuid,
    file_path text,
    file_name text,
    content text,
    chunk_index int,
    page_number int,
    char_count int,
    type text[],
    original_content jsonb,
    embedding vector(384),
    created_at timestamptz,
    rank_score float
) AS $$
DECLARE
    fts_results_count int;
    normalized_query text;
BEGIN
    -- Normalize query: lowercase and remove extra spaces
    normalized_query := lower(trim(query_text));
    
    -- Try FTS first (exact token matching) and collect IDs
    -- Group by doc_id to return only best chunk per document
    RETURN QUERY
    WITH fts_matches AS (
        SELECT 
            dc.id,
            dc.doc_id,
            dc.file_path,
            dc.file_name,
            dc.content,
            dc.chunk_index,
            dc.page_number,
            dc.char_count,
            dc.type,
            dc.original_content,
            dc.embedding,
            dc.created_at,
            ts_rank(dc.fts, plainto_tsquery('english', query_text))::float as rank_score,
            ROW_NUMBER() OVER (PARTITION BY dc.doc_id ORDER BY ts_rank(dc.fts, plainto_tsquery('english', query_text)) DESC, dc.chunk_index ASC) as rn
        FROM document_chunks dc
        WHERE 
            (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
            AND dc.fts @@ plainto_tsquery('english', query_text)
    )
    SELECT 
        fm.id, fm.doc_id, fm.file_path, fm.file_name, fm.content, fm.chunk_index, fm.page_number,
        fm.char_count, fm.type, fm.original_content, fm.embedding, fm.created_at, fm.rank_score
    FROM fts_matches fm
    WHERE fm.rn = 1  -- Only best chunk per document
    ORDER BY fm.rank_score DESC
    LIMIT match_count;
    
    -- Get count of FTS results
    GET DIAGNOSTICS fts_results_count = ROW_COUNT;
    
    -- If FTS found enough results, return them
    IF fts_results_count >= match_count THEN
        RETURN;
    END IF;
    
    -- Fallback: Use ILIKE for partial/case-insensitive matching
    -- This handles cases like "casediarydetails" matching "CaseDiaryDetails"
    -- FIX: Match words individually, not as exact phrase
    -- Group by doc_id to return only best chunk per document
    RETURN QUERY
    WITH fts_ids AS (
        SELECT dc.id
        FROM document_chunks dc
        WHERE 
            (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
            AND dc.fts @@ plainto_tsquery('english', query_text)
        LIMIT match_count
    ),
    query_words AS (
        SELECT unnest(string_to_array(normalized_query, ' ')) AS word
    ),
    ilike_matches AS (
        SELECT 
            dc.id,
            dc.doc_id,
            dc.file_path,
            dc.file_name,
            dc.content,
            dc.chunk_index,
            dc.page_number,
            dc.char_count,
            dc.type,
            dc.original_content,
            dc.embedding,
            dc.created_at,
            -- Calculate a score based on how many words match
            (
                SELECT COUNT(*)::float / GREATEST(array_length(string_to_array(normalized_query, ' '), 1), 1)::float
                FROM query_words qw
                WHERE lower(dc.content) LIKE '%' || qw.word || '%'
                   OR lower(dc.file_name) LIKE '%' || qw.word || '%'
            )::float as rank_score,
            -- Row number to get best chunk per document
            ROW_NUMBER() OVER (
                PARTITION BY dc.doc_id 
                ORDER BY (
                    SELECT COUNT(*)::float / GREATEST(array_length(string_to_array(normalized_query, ' '), 1), 1)::float
                    FROM query_words qw
                    WHERE lower(dc.content) LIKE '%' || qw.word || '%'
                       OR lower(dc.file_name) LIKE '%' || qw.word || '%'
                ) DESC, dc.chunk_index ASC
            ) as rn
        FROM document_chunks dc
        WHERE 
            (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
            AND (
                -- Match at least one word from query (case-insensitive, partial)
                EXISTS (
                    SELECT 1 FROM query_words qw
                    WHERE lower(dc.content) LIKE '%' || qw.word || '%'
                       OR lower(dc.file_name) LIKE '%' || qw.word || '%'
                )
            )
            -- Exclude results already found by FTS
            AND NOT EXISTS (
                SELECT 1 FROM fts_ids fi WHERE fi.id = dc.id
            )
    )
    SELECT 
        im.id, im.doc_id, im.file_path, im.file_name, im.content, im.chunk_index, im.page_number,
        im.char_count, im.type, im.original_content, im.embedding, im.created_at, im.rank_score
    FROM ilike_matches im
    WHERE im.rn = 1  -- Only best chunk per document
    ORDER BY im.rank_score DESC
    LIMIT (match_count - fts_results_count);
END;
$$ LANGUAGE plpgsql;

-- Enhanced Fuzzy Search Function (uses ILIKE with pattern matching)
CREATE OR REPLACE FUNCTION fuzzy_search_chunks_enhanced(
    query_text text,
    filter_doc_ids uuid[] DEFAULT NULL,
    match_count int DEFAULT 1
)
RETURNS TABLE (
    id uuid,
    doc_id uuid,
    file_path text,
    file_name text,
    content text,
    chunk_index int,
    page_number int,
    char_count int,
    type text[],
    original_content jsonb,
    embedding vector(384),
    created_at timestamptz,
    rank_score float
) AS $$
DECLARE
    normalized_query text;
    query_words text[];
    word_pattern text;
BEGIN
    -- Normalize query
    normalized_query := lower(trim(query_text));
    
    -- Split query into words (if spaces exist)
    query_words := string_to_array(normalized_query, ' ');
    
    -- If single word or no spaces, use direct pattern matching
    IF array_length(query_words, 1) IS NULL OR array_length(query_words, 1) = 1 THEN
        -- Single word: match anywhere in content
        -- Group by doc_id to return only best chunk per document
        RETURN QUERY
        WITH fuzzy_matches AS (
            SELECT 
                dc.id,
                dc.doc_id,
                dc.file_path,
                dc.file_name,
                dc.content,
                dc.chunk_index,
                dc.page_number,
                dc.char_count,
                dc.type,
                dc.original_content,
                dc.embedding,
                dc.created_at,
                CASE 
                    WHEN lower(dc.content) = normalized_query THEN 1.0
                    WHEN lower(dc.content) LIKE normalized_query || '%' THEN 0.9
                    WHEN lower(dc.content) LIKE '%' || normalized_query || '%' THEN 0.7
                    WHEN lower(dc.file_name) LIKE '%' || normalized_query || '%' THEN 0.6
                    ELSE 0.5
                END::float as rank_score,
                ROW_NUMBER() OVER (
                    PARTITION BY dc.doc_id 
                    ORDER BY 
                        CASE 
                            WHEN lower(dc.content) = normalized_query THEN 1.0
                            WHEN lower(dc.content) LIKE normalized_query || '%' THEN 0.9
                            WHEN lower(dc.content) LIKE '%' || normalized_query || '%' THEN 0.7
                            WHEN lower(dc.file_name) LIKE '%' || normalized_query || '%' THEN 0.6
                            ELSE 0.5
                        END DESC, 
                        dc.chunk_index ASC
                ) as rn
            FROM document_chunks dc
            WHERE 
                (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
                AND (
                    lower(dc.content) LIKE '%' || normalized_query || '%'
                    OR lower(dc.file_name) LIKE '%' || normalized_query || '%'
                )
        )
        SELECT 
            fm.id, fm.doc_id, fm.file_path, fm.file_name, fm.content, fm.chunk_index, fm.page_number,
            fm.char_count, fm.type, fm.original_content, fm.embedding, fm.created_at, fm.rank_score
        FROM fuzzy_matches fm
        WHERE fm.rn = 1  -- Only best chunk per document
        ORDER BY fm.rank_score DESC
        LIMIT match_count;
    ELSE
        -- Multiple words: match all words (AND condition) or any word (OR condition)
        -- Using OR for more flexible fuzzy matching
        -- Group by doc_id to return only best chunk per document
        RETURN QUERY
        WITH fuzzy_matches AS (
            SELECT 
                dc.id,
                dc.doc_id,
                dc.file_path,
                dc.file_name,
                dc.content,
                dc.chunk_index,
                dc.page_number,
                dc.char_count,
                dc.type,
                dc.original_content,
                dc.embedding,
                dc.created_at,
                -- Score based on how many words match
                (
                    SELECT COUNT(*)::float / array_length(query_words, 1)::float
                    FROM unnest(query_words) AS word
                    WHERE lower(dc.content) LIKE '%' || word || '%'
                       OR lower(dc.file_name) LIKE '%' || word || '%'
                ) as rank_score,
                ROW_NUMBER() OVER (
                    PARTITION BY dc.doc_id 
                    ORDER BY (
                        SELECT COUNT(*)::float / array_length(query_words, 1)::float
                        FROM unnest(query_words) AS word
                        WHERE lower(dc.content) LIKE '%' || word || '%'
                           OR lower(dc.file_name) LIKE '%' || word || '%'
                    ) DESC, 
                    dc.chunk_index ASC
                ) as rn
            FROM document_chunks dc
            WHERE 
                (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
                AND (
                    -- At least one word must match
                    EXISTS (
                        SELECT 1 FROM unnest(query_words) AS word
                        WHERE lower(dc.content) LIKE '%' || word || '%'
                           OR lower(dc.file_name) LIKE '%' || word || '%'
                    )
                )
        )
        SELECT 
            fm.id, fm.doc_id, fm.file_path, fm.file_name, fm.content, fm.chunk_index, fm.page_number,
            fm.char_count, fm.type, fm.original_content, fm.embedding, fm.created_at, fm.rank_score
        FROM fuzzy_matches fm
        WHERE fm.rn = 1  -- Only best chunk per document
        ORDER BY fm.rank_score DESC
        LIMIT match_count;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Enhanced Hybrid Search Function with doc_id deduplication
-- Returns only best chunk per document (highest score, first match)
CREATE OR REPLACE FUNCTION hybrid_search_chunks(
    query_embedding vector(384),
    query_text text,
    filter_doc_ids uuid[] DEFAULT NULL,
    vector_weight float DEFAULT 0.7,
    keyword_weight float DEFAULT 0.3,
    similarity_threshold float DEFAULT 0.3,
    match_count int DEFAULT 1
)
RETURNS TABLE (
    id uuid,
    doc_id uuid,
    file_path text,
    file_name text,
    content text,
    chunk_index int,
    page_number int,
    char_count int,
    type text[],
    original_content jsonb,
    embedding vector(384),
    created_at timestamptz,
    hybrid_score float
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT 
            dc.id,
            (1 - (dc.embedding <=> query_embedding))::float as similarity_score
        FROM document_chunks dc
        WHERE 
            (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
            AND (1 - (dc.embedding <=> query_embedding)) >= similarity_threshold
    ),
    keyword_results AS (
        SELECT 
            dc.id,
            ts_rank(dc.fts, plainto_tsquery('english', query_text))::float as rank_score
        FROM document_chunks dc
        WHERE 
            (filter_doc_ids IS NULL OR dc.doc_id = ANY(filter_doc_ids))
            AND dc.fts @@ plainto_tsquery('english', query_text)
    ),
    combined_scores AS (
        SELECT 
            COALESCE(v.id, k.id) as id,
            (COALESCE(v.similarity_score, 0) * vector_weight + COALESCE(k.rank_score, 0) * keyword_weight) as hybrid_score
        FROM vector_results v
        FULL OUTER JOIN keyword_results k ON v.id = k.id
    ),
    ranked_results AS (
        SELECT 
            dc.id,
            dc.doc_id,
            dc.file_path,
            dc.file_name,
            dc.content,
            dc.chunk_index,
            dc.page_number,
            dc.char_count,
            dc.type,
            dc.original_content,
            dc.embedding,
            dc.created_at,
            cs.hybrid_score,
            -- Row number to get best chunk per document
            ROW_NUMBER() OVER (
                PARTITION BY dc.doc_id 
                ORDER BY cs.hybrid_score DESC, dc.chunk_index ASC
            ) as rn
        FROM combined_scores cs
        JOIN document_chunks dc ON cs.id = dc.id
        WHERE cs.hybrid_score >= similarity_threshold
    )
    SELECT 
        rr.id, rr.doc_id, rr.file_path, rr.file_name, rr.content, rr.chunk_index, rr.page_number,
        rr.char_count, rr.type, rr.original_content, rr.embedding, rr.created_at, rr.hybrid_score
    FROM ranked_results rr
    WHERE rr.rn = 1  -- Only best chunk per document
    ORDER BY rr.hybrid_score DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
