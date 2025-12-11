import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from typing import Optional

# Load .env from project root
project_root = Path(__file__).parent.parent.parent
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)


class Settings(BaseSettings):
    # Supabase Configuration
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_storage_bucket: str = "documents"
    
    # Embedding Model Configuration
    embed_model_id: str = "sentence-transformers/all-MiniLM-L6-v2"
    max_tokens: int = 512
    embedding_dimension: int = 384  # for all-MiniLM-L6-v2
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = True
    
    # Celery Configuration
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    # File Processing Configuration
    allowed_file_types: list = ['pdf', 'docx', 'pptx', 'xlsx', 'txt']
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    
    # Chunking Configuration
    chunk_overlap: int = 50
    
    class Config:
        env_file = ".env"
        extra = "ignore"


# Initialize settings
settings = Settings()


# Job states
JOB_STATES = {
    'pending': 'pending',
    'processing': 'processing',
    'completed': 'completed',
    'failed': 'failed',
}

# Processing stages
PROCESSING_STAGES = {
    'uploaded': 'uploaded',
    'downloading': 'downloading',
    'chunking': 'chunking',
    'embedding': 'embedding',
    'storing': 'storing',
    'completed': 'completed',
}

