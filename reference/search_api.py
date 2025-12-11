"""
Search API for querying indexed documents
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging

from database import get_supabase_client
from document_processor import DocumentProcessor

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    """Search request model"""
    query: str
    search_type: str = "text"  # "text", "vector", or "hybrid"
    limit: int = 10
    threshold: float = 0.7
    file_name_filter: Optional[str] = None
    user_id_filter: Optional[str] = None


class SearchResult(BaseModel):
    """Search result model"""
    chunk_id: str
    content: str
    file_name: str
    chunk_index: int
    score: float
    page_number: Optional[int] = None
    file_path: Optional[str] = None
    highlight: Optional[str] = None


class SearchAPI:
    """Search API for document chunks"""
    
    def __init__(self):
        self.client = get_supabase_client()
        self.processor = DocumentProcessor(generate_embeddings=False)
    
    def text_search(
        self,
        query: str,
        limit: int = 10,
        file_name_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Full-text search using PostgreSQL's full-text search
        
        Args:
            query: Search query
            limit: Maximum number of results
            file_name_filter: Optional file name filter
        
        Returns:
            List of search results with rank scores
        """
        try:
            # Use Supabase RPC to call the search function
            result = self.client.rpc(
                'search_chunks_by_text',
                {
                    'search_query': query,
                    'match_count': limit
                }
            ).execute()
            
            results = result.data if result.data else []
            
            # Apply file name filter if provided
            if file_name_filter:
                results = [r for r in results if file_name_filter.lower() in r['file_name'].lower()]
            
            return results
            
        except Exception as e:
            logger.error(f"Text search failed: {str(e)}")
            raise
    
    def vector_search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        file_name_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Vector similarity search using embeddings
        
        Args:
            query: Search query
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0-1)
            file_name_filter: Optional file name filter
        
        Returns:
            List of search results with similarity scores
        """
        try:
            # Generate embedding for query
            self.processor.generate_embeddings = True
            if not self.processor.embedding_model:
                from sentence_transformers import SentenceTransformer
                self.processor.embedding_model = SentenceTransformer(self.processor.embed_model_id)
            
            query_embedding = self.processor.generate_embedding(query)
            
            if not query_embedding:
                raise Exception("Failed to generate query embedding")
            
            # Use Supabase RPC to call the search function
            result = self.client.rpc(
                'search_chunks_by_embedding',
                {
                    'query_embedding': query_embedding,
                    'match_threshold': threshold,
                    'match_count': limit
                }
            ).execute()
            
            results = result.data if result.data else []
            
            # Apply file name filter if provided
            if file_name_filter:
                results = [r for r in results if file_name_filter.lower() in r['file_name'].lower()]
            
            return results
            
        except Exception as e:
            logger.error(f"Vector search failed: {str(e)}")
            raise
    
    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        text_weight: float = 0.3,
        vector_weight: float = 0.7,
        file_name_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining text and vector search
        
        Args:
            query: Search query
            limit: Maximum number of results
            threshold: Minimum similarity threshold for vector search
            text_weight: Weight for text search scores (0-1)
            vector_weight: Weight for vector search scores (0-1)
            file_name_filter: Optional file name filter
        
        Returns:
            List of search results with combined scores
        """
        try:
            # Perform both searches
            text_results = self.text_search(query, limit * 2, file_name_filter)
            vector_results = self.vector_search(query, limit * 2, threshold, file_name_filter)
            
            # Normalize and combine scores
            combined = {}
            
            # Process text results
            max_text_rank = max([r['rank'] for r in text_results]) if text_results else 1
            for result in text_results:
                chunk_id = result['id']
                normalized_score = result['rank'] / max_text_rank
                combined[chunk_id] = {
                    **result,
                    'combined_score': normalized_score * text_weight
                }
            
            # Process vector results
            for result in vector_results:
                chunk_id = result['id']
                if chunk_id in combined:
                    combined[chunk_id]['combined_score'] += result['similarity'] * vector_weight
                else:
                    combined[chunk_id] = {
                        **result,
                        'combined_score': result['similarity'] * vector_weight
                    }
            
            # Sort by combined score and return top results
            sorted_results = sorted(
                combined.values(),
                key=lambda x: x['combined_score'],
                reverse=True
            )[:limit]
            
            return sorted_results
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {str(e)}")
            raise
    
    def search(
        self,
        request: SearchRequest
    ) -> List[SearchResult]:
        """
        Main search method that routes to appropriate search type
        
        Args:
            request: SearchRequest object
        
        Returns:
            List of SearchResult objects
        """
        try:
            if request.search_type == "text":
                results = self.text_search(
                    query=request.query,
                    limit=request.limit,
                    file_name_filter=request.file_name_filter
                )
                score_key = 'rank'
            elif request.search_type == "vector":
                results = self.vector_search(
                    query=request.query,
                    limit=request.limit,
                    threshold=request.threshold,
                    file_name_filter=request.file_name_filter
                )
                score_key = 'similarity'
            elif request.search_type == "hybrid":
                results = self.hybrid_search(
                    query=request.query,
                    limit=request.limit,
                    threshold=request.threshold,
                    file_name_filter=request.file_name_filter
                )
                score_key = 'combined_score'
            else:
                raise ValueError(f"Invalid search type: {request.search_type}")
            
            # Convert to SearchResult objects
            search_results = []
            for result in results:
                search_results.append(
                    SearchResult(
                        chunk_id=str(result['id']),
                        content=result['content'],
                        file_name=result['file_name'],
                        chunk_index=result['chunk_index'],
                        score=float(result[score_key]),
                        page_number=result.get('page_number'),
                        file_path=result.get('file_path'),
                        highlight=self._generate_highlight(result['content'], request.query)
                    )
                )
            
            return search_results
            
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            raise
    
    def _generate_highlight(self, content: str, query: str, context_chars: int = 150) -> str:
        """
        Generate a highlighted snippet around the query match
        
        Args:
            content: Full content text
            query: Search query
            context_chars: Number of characters of context on each side
        
        Returns:
            Highlighted snippet
        """
        try:
            # Find query position (case-insensitive)
            lower_content = content.lower()
            lower_query = query.lower()
            
            pos = lower_content.find(lower_query)
            if pos == -1:
                # Query not found, return beginning of content
                return content[:context_chars * 2] + "..."
            
            # Calculate snippet boundaries
            start = max(0, pos - context_chars)
            end = min(len(content), pos + len(query) + context_chars)
            
            snippet = content[start:end]
            
            # Add ellipsis if truncated
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
            
            return snippet
            
        except Exception as e:
            logger.warning(f"Failed to generate highlight: {str(e)}")
            return content[:300] + "..."

