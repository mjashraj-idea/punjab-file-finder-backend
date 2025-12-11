from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import logging
from datetime import datetime
import uuid
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from indexer.core.config import settings, JOB_STATES, PROCESSING_STAGES
from indexer.core.models import (
    FileUploadResponse,
    IndexingRequest,
    IndexingResponse,
    JobStatusResponse,
    ChunkResponse
)
from indexer.core.database import get_supabase_client, get_storage_bucket
from indexer.services.db_operations import DatabaseOperations

# Note: Search functionality moved to separate retrieval module
# from search_api import SearchAPI, SearchRequest, SearchResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Document Indexer Module",
    description="Document indexing service with Docling and Supabase. Part of a multi-module system (Indexer → Retriever → LLM)",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "indexer",
            "description": "Document indexing operations - upload, process, and store documents"
        },
        {
            "name": "status",
            "description": "Job and system status monitoring"
        },
        {
            "name": "health",
            "description": "Health check endpoints"
        }
    ]
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database operations
db_ops = DatabaseOperations()

# Note: Search API will be in separate retrieval module
# search_api = SearchAPI()


@app.get("/", tags=["health"])
async def root():
    """Root endpoint - Indexer Module"""
    return {
        "module": "indexer",
        "service": "Document Indexer",
        "version": "1.0.0",
        "status": "running",
        "description": "Handles document upload, processing, chunking, and embedding generation",
        "next_modules": {
            "retrieval": "Will handle search and document retrieval",
            "llm": "Will handle LLM interactions and RAG"
        }
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for indexer module"""
    try:
        # Test Supabase connection
        client = get_supabase_client()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "supabase_connected": True
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }


@app.post("/api/indexer/upload", response_model=FileUploadResponse, tags=["indexer"])
async def upload_file(
    file: UploadFile = File(...),
    generate_embeddings: bool = Form(True)
):
    """
    Upload a file to Supabase storage, create a processing job, and start Celery task.
    
    This endpoint:
    1. Validates the file
    2. Uploads to Supabase storage (filename = doc_id)
    3. Creates a processing job record
    4. Starts a Celery task to process the document
    5. Returns the job ID, doc_id, and task ID for tracking
    """
    try:
        # Validate file type
        file_ext = file.filename.split('.')[-1].lower()
        if file_ext not in settings.allowed_file_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type .{file_ext} not allowed. Allowed types: {', '.join(settings.allowed_file_types)}"
            )
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size
        if file_size > settings.max_file_size:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds maximum allowed size of {settings.max_file_size / (1024*1024)}MB"
            )
        
        # Generate doc_id (will be used as filename in storage)
        doc_id = str(uuid.uuid4())
        file_storage_path = f"{doc_id}.{file_ext}"  # Simple: doc_id.pdf
        
        logger.info(f"Uploading file: {file.filename} ({file_size} bytes) as {file_storage_path}")
        
        # Upload to Supabase storage
        storage_bucket = get_storage_bucket()
        upload_result = storage_bucket.upload(
            path=file_storage_path,
            file=file_content,
            file_options={"content-type": file.content_type or "application/octet-stream"}
        )
        
        logger.info(f"File uploaded successfully: {file_storage_path}")
        
        # Create processing job with the generated doc_id
        job = db_ops.create_processing_job(
            doc_id=doc_id,  # Pass doc_id explicitly
            file_storage_path=file_storage_path,
            file_name=file.filename,
            file_type=file_ext,
            file_size=file_size,
            user_id=None,  # No user_id needed
            metadata={
                "original_filename": file.filename,
                "content_type": file.content_type,
                "upload_timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.info(f"Processing job created: {job['id']} with doc_id: {doc_id}")
        
        # Import and start Celery task
        from indexer.services.celery_tasks import process_document_task
        
        task = process_document_task.delay(
            job_id=str(job['id']),
            generate_embeddings=generate_embeddings
        )
        
        logger.info(f"Celery task started: {task.id} for job: {job['id']}")
        
        # Update job with celery task ID
        db_ops.update_processing_job(
            job_id=str(job['id']),
            progress_info={
                'celery_task_id': task.id,
                'started_processing': datetime.utcnow().isoformat()
            }
        )
        
        return FileUploadResponse(
            job_id=str(job['id']),
            doc_id=job['doc_id'],  # Return doc_id for cross-module use
            upload_url=f"supabase://{settings.supabase_storage_bucket}/{file_storage_path}",
            file_storage_path=file_storage_path,
            message=f"File uploaded successfully and processing started. Task ID: {task.id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/tasks/{task_id}", tags=["status"])
async def get_task_status(task_id: str):
    """
    Get Celery task status
    
    Args:
        task_id: Celery task ID
    
    Returns:
        Task status information
    """
    try:
        from indexer.services.celery_tasks import celery_app
        from celery.result import AsyncResult
        
        task = AsyncResult(task_id, app=celery_app)
        
        return {
            "task_id": task_id,
            "status": task.status,
            "ready": task.ready(),
            "successful": task.successful() if task.ready() else None,
            "failed": task.failed() if task.ready() else None,
        }
        
    except Exception as e:
        logger.error(f"Error getting task status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/indexer/retry", response_model=IndexingResponse, tags=["indexer"])
async def index_document(request: IndexingRequest):
    """
    Manually trigger indexing for a job (if not already started).
    
    Note: With Celery integration, indexing starts automatically on upload.
    This endpoint can be used to retry failed jobs.
    """
    try:
        # Get job
        job = db_ops.get_processing_job(request.job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")
        
        # Check if job is already processing or completed
        if job['status'] in [JOB_STATES['processing']]:
            return IndexingResponse(
                status="already_processing",
                job_id=request.job_id,
                message=f"Job is already being processed",
                data={
                    "current_status": job['status'],
                    "current_stage": job['current_stage']
                }
            )
        
        if job['status'] == JOB_STATES['completed']:
            return IndexingResponse(
                status="already_completed",
                job_id=request.job_id,
                message=f"Job is already completed",
                data={
                    "current_status": job['status'],
                    "progress_info": job.get('progress_info', {})
                }
            )
        
        # Start/restart Celery task
        from indexer.services.celery_tasks import process_document_task
        
        task = process_document_task.delay(
            job_id=request.job_id,
            generate_embeddings=request.generate_embeddings
        )
        
        # Update job with new task ID
        db_ops.update_processing_job(
            job_id=request.job_id,
            status=JOB_STATES['pending'],
            progress_info={
                'celery_task_id': task.id,
                'restarted_at': datetime.utcnow().isoformat()
            }
        )
        
        return IndexingResponse(
            status="started",
            job_id=request.job_id,
            message=f"Document indexing (re)started. Task ID: {task.id}",
            data={
                "generate_embeddings": request.generate_embeddings,
                "task_id": task.id
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting indexing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/jobs/{job_id}", response_model=JobStatusResponse, tags=["status"])
async def get_job_status(job_id: str):
    """Get job status and progress by job ID"""
    try:
        job = db_ops.get_processing_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        return JobStatusResponse(
            id=str(job['id']),
            doc_id=job.get('doc_id'),
            status=job['status'],
            current_stage=job['current_stage'],
            progress_info=job.get('progress_info', {}),
            error_message=job.get('error_message'),
            file_name=job.get('file_name'),
            file_size=job.get('file_size'),
            started_at=job.get('started_at'),
            completed_at=job.get('completed_at'),
            created_at=job['created_at']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/documents/{doc_id}", response_model=JobStatusResponse, tags=["status"])
async def get_job_status_by_doc_id(doc_id: str):
    """Get job status and progress by document ID (useful for other modules)"""
    try:
        job = db_ops.get_processing_job_by_doc_id(doc_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        
        return JobStatusResponse(
            id=str(job['id']),
            doc_id=job.get('doc_id'),
            status=job['status'],
            current_stage=job['current_stage'],
            progress_info=job.get('progress_info', {}),
            error_message=job.get('error_message'),
            file_name=job.get('file_name'),
            file_size=job.get('file_size'),
            started_at=job.get('started_at'),
            completed_at=job.get('completed_at'),
            created_at=job['created_at']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status by doc_id: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/jobs", response_model=List[JobStatusResponse], tags=["status"])
async def get_jobs(
    status: Optional[str] = None,
    limit: int = 100
):
    """Get all jobs or filter by status"""
    try:
        if status:
            jobs = db_ops.get_jobs_by_status(status, limit)
        else:
            jobs = db_ops.get_all_jobs(limit)
        
        return [
            JobStatusResponse(
                id=str(job['id']),
                doc_id=job.get('doc_id'),
                status=job['status'],
                current_stage=job['current_stage'],
                progress_info=job.get('progress_info', {}),
                error_message=job.get('error_message'),
                file_name=job.get('file_name'),
                file_size=job.get('file_size'),
                started_at=job.get('started_at'),
                completed_at=job.get('completed_at'),
                created_at=job['created_at']
            )
            for job in jobs
        ]
        
    except Exception as e:
        logger.error(f"Error getting jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/jobs/{job_id}/chunks", response_model=List[ChunkResponse], tags=["indexer"])
async def get_job_chunks(
    job_id: str,
    with_embeddings: bool = False
):
    """Get chunks for a job by job ID"""
    try:
        chunks = db_ops.get_chunks_by_job_id(job_id, with_embeddings=with_embeddings)
        
        return [
            ChunkResponse(
                id=str(chunk['id']),
                content=chunk['content'],
                chunk_index=chunk['chunk_index'],
                page_number=chunk['page_number'],
                char_count=chunk['char_count'],
                type=chunk['type'],
                has_embedding=chunk.get('embedding') is not None,
                created_at=chunk['created_at']
            )
            for chunk in chunks
        ]
        
    except Exception as e:
        logger.error(f"Error getting job chunks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/documents/{doc_id}/chunks", response_model=List[ChunkResponse], tags=["indexer"])
async def get_document_chunks_by_doc_id(
    doc_id: str,
    with_embeddings: bool = False
):
    """Get chunks for a document by document ID (useful for retrieval module)"""
    try:
        chunks = db_ops.get_chunks_by_doc_id(doc_id, with_embeddings=with_embeddings)
        
        if not chunks:
            raise HTTPException(status_code=404, detail=f"No chunks found for document {doc_id}")
        
        return [
            ChunkResponse(
                id=str(chunk['id']),
                content=chunk['content'],
                chunk_index=chunk['chunk_index'],
                page_number=chunk['page_number'],
                char_count=chunk['char_count'],
                type=chunk['type'],
                has_embedding=chunk.get('embedding') is not None,
                created_at=chunk['created_at']
            )
            for chunk in chunks
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document chunks by doc_id: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indexer/stats", tags=["status"])
async def get_statistics():
    """Get indexer module statistics"""
    try:
        # Get job counts by status
        pending_jobs = db_ops.get_jobs_by_status(JOB_STATES['pending'])
        processing_jobs = db_ops.get_jobs_by_status(JOB_STATES['processing'])
        completed_jobs = db_ops.get_jobs_by_status(JOB_STATES['completed'])
        failed_jobs = db_ops.get_jobs_by_status(JOB_STATES['failed'])
        
        # Get chunk statistics
        chunk_stats = db_ops.get_chunk_statistics()
        
        return {
            "jobs": {
                "pending": len(pending_jobs),
                "processing": len(processing_jobs),
                "completed": len(completed_jobs),
                "failed": len(failed_jobs),
                "total": len(pending_jobs) + len(processing_jobs) + len(completed_jobs) + len(failed_jobs)
            },
            "chunks": chunk_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Note: Search/Retrieval endpoints moved to separate retrieval module
# The search functionality will be in a dedicated retrieval service that:
# - Reads from the same document_chunks table
# - Provides text, vector, and hybrid search
# - Handles query processing and ranking
# This separation follows microservices architecture for better scalability

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )

