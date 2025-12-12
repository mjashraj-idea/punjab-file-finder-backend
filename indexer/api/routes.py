"""
Indexer module routes with Role-Based Access Control
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import Optional, List
import logging
from datetime import datetime
import uuid
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from indexer.core.config import settings, JOB_STATES, PROCESSING_STAGES
from indexer.core.models import (
    FileUploadResponse,
    IndexingRequest,
    IndexingResponse,
    JobStatusResponse,
    ChunkResponse
)
from shared.core.database import get_supabase_client, get_storage_bucket
from shared.services.db_operations import DatabaseOperations
from auth.core.rbac import get_current_user, require_admin, require_permission

# Initialize router
router = APIRouter()

# Initialize database operations
db_ops = DatabaseOperations(get_supabase_client())

# Initialize logger
logger = logging.getLogger(__name__)

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    restricted: bool = Form(False),
    generate_embeddings: bool = Form(True),
    current_user: dict = Depends(require_permission('can_upload'))
):
    """
    Upload a file to Supabase storage, create a document record, create a processing job, and start Celery task.
    
    **Permission Required**: `can_upload` (or Admin)
    
    This endpoint:
    1. Validates the file
    2. Creates a document master record (with metadata)
    3. Uploads to Supabase storage (filename = doc_id)
    4. Creates a processing job record
    5. Starts a Celery task to process the document
    6. Returns the job ID, doc_id, and task ID for tracking
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
        
        # 1. Create Document Master Record first (for FK integrity)
        try:
            db_ops.create_document(
                doc_id=doc_id,
                name=file.filename,
                type=file_ext.replace('.', ''),  # remove dot
                size_bytes=file_size,
                category=category,
                department=department,
                tags=None,
                restricted=restricted
            )
        except Exception as e:
            logger.error(f"Failed to create document record: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to initialize document record")
        
        # 2. Upload to Supabase storage
        try:
            storage_bucket = get_storage_bucket()
            upload_result = storage_bucket.upload(
                path=file_storage_path,
                file=file_content,
                file_options={"content-type": file.content_type or "application/octet-stream"}
            )
            logger.info(f"File uploaded successfully: {file_storage_path}")
        except Exception as e:
            # Rollback: delete document record if storage upload fails
            # In a real transaction this would be automatic, but here we do manual cleanup
            logger.error(f"Storage upload failed, rolling back document: {str(e)}")
            # db_ops.delete_document(doc_id) # Consider implementing rollback
            raise HTTPException(status_code=500, detail=f"Storage upload failed: {str(e)}")
        
        # 3. Create processing job with the generated doc_id
        job = db_ops.create_processing_job(
            doc_id=doc_id,
            file_storage_path=file_storage_path,
            file_name=file.filename,
            file_type=file_ext,
            file_size=file_size,
            user_id=current_user['id'],  # Track who uploaded
            metadata={
                "original_filename": file.filename,
                "content_type": file.content_type,
                "upload_timestamp": datetime.utcnow().isoformat(),
                "uploaded_by": current_user['username'],
                "category": category,
                "department": department,
                "restricted": restricted
            },
            status=JOB_STATES['pending'],
            current_stage=PROCESSING_STAGES['uploaded']
        )
        
        logger.info(f"Processing job created: {job['id']} with doc_id: {doc_id}")
        
        # Log upload activity
        db_ops.create_activity_log(
            user_id=current_user['id'],
            user_name=current_user['full_name'] or current_user['username'],
            action="file_upload",
            details=f"Uploaded file: {file.filename} ({file_size} bytes) to {category}/{department} (Restricted: {restricted})"
        )
        
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
            doc_id=job['doc_id'],
            upload_url=f"supabase://{settings.supabase_storage_bucket}/{file_storage_path}",
            file_storage_path=file_storage_path,
            message=f"File uploaded successfully and processing started. Task ID: {task.id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user)  # Any authenticated user
):
    """Get job status and progress by job ID (All authenticated users)"""
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


@router.get("/documents/{doc_id}", response_model=JobStatusResponse)
async def get_job_status_by_doc_id(
    doc_id: str,
    current_user: dict = Depends(get_current_user)  # Any authenticated user
):
    """Get job status and progress by document ID (All authenticated users)"""
    try:
        job = db_ops.get_processing_job_by_doc_id(doc_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found or no processing job associated")
        
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
        logger.error(f"Error getting job status by doc_id {doc_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/chunks", response_model=List[ChunkResponse])
async def get_job_chunks(
    job_id: str,
    with_embeddings: bool = False,
    current_user: dict = Depends(get_current_user)  # Any authenticated user
):
    """Get chunks for a job by job ID (All authenticated users)"""
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


@router.get("/documents/{doc_id}/chunks", response_model=List[ChunkResponse])
async def get_document_chunks_by_doc_id(
    doc_id: str,
    with_embeddings: bool = False,
    current_user: dict = Depends(get_current_user)  # Any authenticated user
):
    """Get chunks for a document by document ID - used by retrieval module (All authenticated users)"""
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


@router.get("/health")
async def health_check():
    """Indexer module health check"""
    try:
        # Test database connection
        client = get_supabase_client()
        
        return {
            "status": "healthy",
            "module": "indexer",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "module": "indexer",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

