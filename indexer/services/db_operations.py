from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import UUID
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from indexer.core.database import get_supabase_client
from indexer.core.models import ProcessingJob, DocumentChunk
from indexer.core.config import JOB_STATES, PROCESSING_STAGES

logger = logging.getLogger(__name__)


class DatabaseOperations:
    """Database operations for processing jobs and document chunks"""
    
    def __init__(self):
        self.client = get_supabase_client()
    
    # Processing Jobs Operations
    
    def create_processing_job(
        self,
        doc_id: str,  # Now required parameter
        file_storage_path: str,
        file_name: str,
        file_type: str,
        file_size: Optional[int] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new processing job"""
        try:
            job = ProcessingJob(
                doc_id=doc_id,  # Use provided doc_id
                file_storage_path=file_storage_path,
                file_name=file_name,
                file_type=file_type,
                file_size=file_size,
                user_id=user_id,
                metadata=metadata or {},
                status=JOB_STATES['pending'],
                current_stage=PROCESSING_STAGES['uploaded']
            )
            
            job_dict = job.model_dump(mode='json')
            # Convert UUID to string for Supabase
            if job_dict.get('id'):
                job_dict['id'] = str(job_dict['id'])
            
            result = self.client.table('processing_jobs').insert(job_dict).execute()
            
            if result.data:
                logger.info(f"Created processing job: {result.data[0]['id']} with doc_id: {doc_id}")
                return result.data[0]
            else:
                raise Exception("Failed to create processing job")
                
        except Exception as e:
            logger.error(f"Error creating processing job: {str(e)}")
            raise
    
    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get processing job by ID"""
        try:
            result = self.client.table('processing_jobs').select('*').eq('id', job_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting processing job {job_id}: {str(e)}")
            return None
    
    def get_processing_job_by_doc_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get processing job by document ID"""
        try:
            result = self.client.table('processing_jobs').select('*').eq('doc_id', doc_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting processing job by doc_id {doc_id}: {str(e)}")
            return None
    
    def update_processing_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        current_stage: Optional[str] = None,
        progress_info: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ) -> bool:
        """Update processing job"""
        try:
            update_data = {'updated_at': datetime.utcnow().isoformat()}
            
            if status is not None:
                update_data['status'] = status
            if current_stage is not None:
                update_data['current_stage'] = current_stage
            if progress_info is not None:
                # Merge with existing progress_info
                existing_job = self.get_processing_job(job_id)
                if existing_job:
                    existing_progress = existing_job.get('progress_info', {})
                    update_data['progress_info'] = {**existing_progress, **progress_info}
                else:
                    update_data['progress_info'] = progress_info
            if error_message is not None:
                update_data['error_message'] = error_message
            if started_at is not None:
                update_data['started_at'] = started_at.isoformat()
            if completed_at is not None:
                update_data['completed_at'] = completed_at.isoformat()
            
            result = self.client.table('processing_jobs').update(update_data).eq('id', job_id).execute()
            
            return len(result.data) > 0
            
        except Exception as e:
            logger.error(f"Error updating processing job {job_id}: {str(e)}")
            return False
    
    def get_jobs_by_status(self, status: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get jobs by status"""
        try:
            result = self.client.table('processing_jobs')\
                .select('*')\
                .eq('status', status)\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting jobs by status {status}: {str(e)}")
            return []
    
    def get_all_jobs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all jobs"""
        try:
            result = self.client.table('processing_jobs')\
                .select('*')\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting all jobs: {str(e)}")
            return []
    
    # Document Chunks Operations
    
    def create_document_chunk(
        self,
        processing_job_id: str,
        file_path: str,
        file_name: str,
        content: str,
        chunk_index: int,
        page_number: int = 1,
        char_count: int = 0,
        chunk_type: List[str] = None,
        original_content: Dict[str, Any] = None,
        embedding: Optional[List[float]] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a document chunk"""
        try:
            chunk = DocumentChunk(
                processing_job_id=UUID(processing_job_id),
                file_path=file_path,
                file_name=file_name,
                content=content,
                chunk_index=chunk_index,
                page_number=page_number,
                char_count=char_count,
                type=chunk_type or ["text"],
                original_content=original_content or {},
                embedding=embedding
            )
            
            chunk_dict = chunk.model_dump(mode='json')
            # Convert UUIDs to strings
            if chunk_dict.get('id'):
                chunk_dict['id'] = str(chunk_dict['id'])
            if chunk_dict.get('processing_job_id'):
                chunk_dict['processing_job_id'] = str(chunk_dict['processing_job_id'])
            
            result = self.client.table('document_chunks').insert(chunk_dict).execute()
            
            if result.data:
                return result.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error creating document chunk: {str(e)}")
            raise
    
    def create_document_chunks_batch(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple document chunks in a batch"""
        try:
            # Prepare chunks for insertion
            chunks_data = []
            for chunk_data in chunks:
                chunk = DocumentChunk(**chunk_data)
                chunk_dict = chunk.model_dump(mode='json')
                
                # Convert UUIDs to strings
                if chunk_dict.get('id'):
                    chunk_dict['id'] = str(chunk_dict['id'])
                if chunk_dict.get('processing_job_id'):
                    chunk_dict['processing_job_id'] = str(chunk_dict['processing_job_id'])
                
                chunks_data.append(chunk_dict)
            
            # Insert in batches of 100 (Supabase limit)
            all_results = []
            batch_size = 100
            
            for i in range(0, len(chunks_data), batch_size):
                batch = chunks_data[i:i + batch_size]
                result = self.client.table('document_chunks').insert(batch).execute()
                if result.data:
                    all_results.extend(result.data)
            
            logger.info(f"Created {len(all_results)} document chunks in batch")
            return all_results
            
        except Exception as e:
            logger.error(f"Error creating document chunks batch: {str(e)}")
            raise
    
    def get_chunks_by_job_id(
        self,
        job_id: str,
        with_embeddings: bool = False
    ) -> List[Dict[str, Any]]:
        """Get document chunks by job ID"""
        try:
            if with_embeddings:
                result = self.client.table('document_chunks')\
                    .select('*')\
                    .eq('processing_job_id', job_id)\
                    .order('chunk_index')\
                    .execute()
            else:
                result = self.client.table('document_chunks')\
                    .select('id, processing_job_id, file_path, file_name, content, chunk_index, page_number, char_count, type, original_content, created_at, updated_at')\
                    .eq('processing_job_id', job_id)\
                    .order('chunk_index')\
                    .execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting chunks for job {job_id}: {str(e)}")
            return []
    
    def get_chunks_by_doc_id(
        self,
        doc_id: str,
        with_embeddings: bool = False
    ) -> List[Dict[str, Any]]:
        """Get document chunks by document ID"""
        try:
            # First get the job by doc_id
            job = self.get_processing_job_by_doc_id(doc_id)
            if not job:
                logger.warning(f"No job found for doc_id: {doc_id}")
                return []
            
            # Then get chunks by job_id
            return self.get_chunks_by_job_id(str(job['id']), with_embeddings)
            
        except Exception as e:
            logger.error(f"Error getting chunks for doc_id {doc_id}: {str(e)}")
            return []
    
    def update_chunk_embedding(
        self,
        chunk_id: str,
        embedding: List[float]
    ) -> bool:
        """Update embedding for a chunk"""
        try:
            result = self.client.table('document_chunks')\
                .update({'embedding': embedding, 'updated_at': datetime.utcnow().isoformat()})\
                .eq('id', chunk_id)\
                .execute()
            
            return len(result.data) > 0
            
        except Exception as e:
            logger.error(f"Error updating embedding for chunk {chunk_id}: {str(e)}")
            return False
    
    def get_chunk_statistics(self) -> Dict[str, int]:
        """Get chunk statistics"""
        try:
            # Total chunks
            result = self.client.table('document_chunks').select('id', count='exact').execute()
            total_chunks = result.count if hasattr(result, 'count') else 0
            
            # Chunks with embeddings
            result_emb = self.client.table('document_chunks')\
                .select('id', count='exact')\
                .not_.is_('embedding', 'null')\
                .execute()
            chunks_with_embeddings = result_emb.count if hasattr(result_emb, 'count') else 0
            
            return {
                'total_chunks': total_chunks,
                'chunks_with_embeddings': chunks_with_embeddings,
                'chunks_without_embeddings': total_chunks - chunks_with_embeddings
            }
            
        except Exception as e:
            logger.error(f"Error getting chunk statistics: {str(e)}")
            return {
                'total_chunks': 0,
                'chunks_with_embeddings': 0,
                'chunks_without_embeddings': 0
            }

