"""
Retriever module routes with Role-Based Access Control and Search Logic
"""
from fastapi import APIRouter, HTTPException, Depends, Body
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.core.database import get_supabase_client
from shared.services.db_operations import DatabaseOperations
from auth.core.rbac import get_current_user, require_permission

# Initialize router
router = APIRouter()

# Initialize database operations
db_ops = DatabaseOperations(get_supabase_client())

# Initialize logger
logger = logging.getLogger(__name__)

# Define request/response models
class SearchRequest(BaseModel):
    query: str
    mode: str = "keyword"  # keyword, semantic, fuzzy
    match_count: int = 20
    similarity_threshold: float = 0.1

class SearchResult(BaseModel):
    id: str
    doc_id: str
    file_name: str
    content: str
    score: float
    page_number: Optional[int] = None
    chunk_index: int
    created_at: str

# Document processor for embeddings (lazy import)
doc_processor = None

def get_doc_processor():
    """Lazy import of document processor to avoid circular dependencies"""
    global doc_processor
    if doc_processor is None:
        try:
            from indexer.services.document_processor import DocumentProcessor
            doc_processor = DocumentProcessor()
        except ImportError:
            logger.warning("DocumentProcessor not available - semantic search will be disabled")
            doc_processor = None
    return doc_processor

@router.post("/search", response_model=List[SearchResult])
async def search_documents(
    request: SearchRequest = Body(...),
    current_user: dict = Depends(require_permission('can_search'))
):
    """
    Search documents with RBAC enforcement.
    Modes:
    - keyword: Full-text search
    - semantic: Hybrid search (75% Vector / 25% Keyword)
    - fuzzy: Standard keyword search (for now)
    """
    try:
        # 1. Get Accessible Documents (RBAC)
        # Returns list of UUIDs or None (if Admin/All access)
        allowed_doc_ids = db_ops.get_accessible_documents(current_user['id'])
        
        # 2. Generate Embedding if Semantic/Hybrid
        query_embedding = None
        if request.mode == 'semantic':
            try:
                processor = get_doc_processor()
                if processor is None:
                    raise HTTPException(
                        status_code=503, 
                        detail="Semantic search is not available. DocumentProcessor not initialized."
                    )
                # Generate embedding for the query
                query_embedding = processor.generate_embedding(request.query)
            except Exception as e:
                logger.error(f"Embedding generation failed: {str(e)}")
                raise HTTPException(status_code=500, detail="Failed to generate query embedding")

        # 3. Perform Search
        results = db_ops.search_documents(
            query_text=request.query,
            query_embedding=query_embedding,
            match_count=request.match_count,
            filter_doc_ids=allowed_doc_ids,
            mode=request.mode,
            similarity_threshold=request.similarity_threshold
        )
        
        # 4. Format Results
        response = []
        for r in results:
            # Map different score names from different RPCs to common 'score'
            score = r.get('hybrid_score') or r.get('rank_score') or r.get('similarity_score') or 0.0
            
            response.append(SearchResult(
                id=str(r['id']),
                doc_id=str(r['doc_id']),
                file_name=r['file_name'],
                content=r['content'],
                score=score,
                page_number=r.get('page_number'),
                chunk_index=r['chunk_index'],
                created_at=r['created_at']
            ))
            
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search API error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """Retriever health check"""
    return {"status": "healthy", "module": "retriever"}
