from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4


# Database Models (matching Supabase schema)
class ProcessingJob(BaseModel):
    """Model for processing_jobs table"""
    id: Optional[UUID] = Field(default_factory=uuid4)
    doc_id: Optional[str] = None
    status: str = "pending"
    current_stage: str = "uploaded"
    progress_info: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = None
    error_message: Optional[str] = None
    file_storage_path: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class DocumentChunk(BaseModel):
    """Model for document_chunks table"""
    id: Optional[UUID] = Field(default_factory=uuid4)
    processing_job_id: Optional[UUID] = None
    doc_id: Optional[str] = None  # Document ID for cross-module reference
    sharepoint_file_id: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    content: str
    chunk_index: int
    page_number: int = 1
    char_count: int = 0
    type: List[str] = Field(default_factory=lambda: ["text"])
    original_content: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


# API Request/Response Models
class FileUploadRequest(BaseModel):
    """Request model for file upload"""
    file_name: str
    file_type: str
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FileUploadResponse(BaseModel):
    """Response model for file upload"""
    job_id: str
    doc_id: str  # Document ID for cross-module reference
    upload_url: str
    file_storage_path: str
    message: str


class IndexingRequest(BaseModel):
    """Request model for indexing a document"""
    job_id: str
    generate_embeddings: bool = True


class IndexingResponse(BaseModel):
    """Response model for indexing operation"""
    status: str
    job_id: str
    message: str
    data: Optional[Dict[str, Any]] = None


class JobStatusResponse(BaseModel):
    """Response model for job status"""
    id: str
    doc_id: Optional[str]
    status: str
    current_stage: str
    progress_info: Dict[str, Any]
    error_message: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class ChunkResponse(BaseModel):
    """Response model for document chunk"""
    id: str
    content: str
    chunk_index: int
    page_number: int
    char_count: int
    type: List[str]
    has_embedding: bool
    created_at: datetime

