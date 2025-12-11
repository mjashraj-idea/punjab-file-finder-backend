"""
Celery tasks for document processing
"""
from celery import Celery
from typing import Dict, Any
import os
from datetime import datetime
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from indexer.core.config import settings, JOB_STATES, PROCESSING_STAGES
from indexer.services.db_operations import DatabaseOperations
from indexer.core.database import get_storage_bucket
from indexer.services.document_processor import DocumentProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set environment variables for CPU optimization
os.environ['OMP_NUM_THREADS'] = '1'

# Create Celery app
celery_app = Celery(
    'docling_indexer',
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend
)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour timeout
    task_soft_time_limit=3300,  # 55 minutes soft timeout
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_disable_rate_limits=True,
    task_ignore_result=True,  # Don't store task results in Redis to save memory
    result_expires=3600,  # Expire results after 1 hour if any are stored
    
    # Redis connection resilience settings
    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    broker_heartbeat=30,
    broker_pool_limit=10,
)


@celery_app.task(name='docling_indexer.process_document', bind=True)
def process_document_task(self, job_id: str, generate_embeddings: bool = True):
    """
    Celery task to process a document
    
    Args:
        job_id: The job ID to process
        generate_embeddings: Whether to generate embeddings
    """
    db_ops = DatabaseOperations()
    
    try:
        logger.info(f"[Task {self.request.id}] Starting document processing for job: {job_id}")
        
        # Update job status to processing
        db_ops.update_processing_job(
            job_id=job_id,
            status=JOB_STATES['processing'],
            current_stage=PROCESSING_STAGES['downloading'],
            started_at=datetime.utcnow()
        )
        
        # Get job details
        job = db_ops.get_processing_job(job_id)
        if not job:
            raise Exception(f"Job {job_id} not found")
        
        file_storage_path = job['file_storage_path']
        file_name = job['file_name']
        
        logger.info(f"[Task {self.request.id}] Downloading file: {file_storage_path}")
        
        # Download file from Supabase storage
        storage_bucket = get_storage_bucket()
        file_content = storage_bucket.download(file_storage_path)
        
        # Update progress
        db_ops.update_processing_job(
            job_id=job_id,
            current_stage=PROCESSING_STAGES['chunking'],
            progress_info={'downloaded': True, 'file_size': len(file_content)}
        )
        
        logger.info(f"[Task {self.request.id}] Processing document: {file_name}")
        
        # Process document with Docling
        processor = DocumentProcessor(generate_embeddings=generate_embeddings)
        chunks = processor.process_document(source=file_content, file_name=file_name)
        
        logger.info(f"[Task {self.request.id}] Document processed: {len(chunks)} chunks created")
        
        # Update progress
        db_ops.update_processing_job(
            job_id=job_id,
            current_stage=PROCESSING_STAGES['storing'],
            progress_info={
                'downloaded': True,
                'chunked': True,
                'total_chunks': len(chunks)
            }
        )
        
        # Store chunks in database
        logger.info(f"[Task {self.request.id}] Storing chunks in database")
        chunks_to_store = []
        
        # Get doc_id from job
        doc_id = job.get('doc_id')
        
        for chunk in chunks:
            chunk_data = {
                'processing_job_id': job_id,
                'doc_id': doc_id,  # Add doc_id to chunks
                'file_path': file_storage_path,
                'file_name': file_name,
                'content': chunk['text'],
                'chunk_index': chunk['chunk_index'],
                'page_number': 1,  # TODO: Extract actual page number if available
                'char_count': chunk['char_count'],
                'chunk_type': chunk['type'],
                'original_content': {
                    'images': chunk.get('images', []),
                    'tables_markdown': chunk.get('tables_markdown', []),
                    'tables_html': chunk.get('tables_html', []),
                },
                'embedding': chunk.get('embedding')
            }
            chunks_to_store.append(chunk_data)
        
        # Store in batches
        stored_chunks = db_ops.create_document_chunks_batch(chunks_to_store)
        logger.info(f"[Task {self.request.id}] Stored {len(stored_chunks)} chunks in database")
        
        # Update job as completed
        db_ops.update_processing_job(
            job_id=job_id,
            status=JOB_STATES['completed'],
            current_stage=PROCESSING_STAGES['completed'],
            completed_at=datetime.utcnow(),
            progress_info={
                'downloaded': True,
                'chunked': True,
                'stored': True,
                'total_chunks': len(chunks),
                'chunks_with_embeddings': sum(1 for c in chunks if c.get('embedding'))
            }
        )
        
        logger.info(f"[Task {self.request.id}] Document processing completed for job: {job_id}")
        
        return {
            'status': 'success',
            'job_id': job_id,
            'chunks_created': len(stored_chunks)
        }
        
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Error processing document for job {job_id}: {str(e)}", exc_info=True)
        
        # Update job as failed
        db_ops.update_processing_job(
            job_id=job_id,
            status=JOB_STATES['failed'],
            error_message=str(e),
            completed_at=datetime.utcnow()
        )
        
        # Re-raise exception for Celery to handle
        raise


@celery_app.task(name='docling_indexer.health_check')
def health_check_task():
    """Simple health check task for Celery workers"""
    return {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    }

