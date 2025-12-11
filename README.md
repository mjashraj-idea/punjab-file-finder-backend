# Document Indexer Module

**Part of a Multi-Module RAG System: Indexer → Retriever → LLM**

A modular document indexing service built with FastAPI, Docling, Celery, and Supabase. This is the **INDEXER MODULE** responsible for processing documents, generating embeddings, and storing chunks for later retrieval.

## System Architecture

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   INDEXER    │  →   │  RETRIEVER   │  →   │     LLM      │
│  (This Module)│      │   (Future)   │      │   (Future)   │
└──────────────┘      └──────────────┘      └──────────────┘
      ↓                     ↓                      ↓
   Supabase             Read from              LLM Provider
   Write Chunks         document_chunks
```

See [MODULE_ARCHITECTURE.md](MODULE_ARCHITECTURE.md) for complete system design.

## Indexer Module - Features

- **Document Upload**: Upload documents to Supabase storage
- **Async Processing**: Celery-based background task processing with Redis
- **Smart Chunking**: Uses Docling's HybridChunker for intelligent document segmentation
- **Multi-modal Support**: Handles text, images, and tables
- **Embedding Generation**: Optional automatic embedding generation using Sentence Transformers
- **RESTful API**: Clean API endpoints for all operations
- **Progress Tracking**: Real-time job status and progress tracking
- **Scalable**: Celery workers can be scaled horizontally
- **Modular Architecture**: Well-organized codebase with separation of concerns

## Architecture

```
docling-exp/
├── config.py              # Configuration and settings
├── database.py            # Supabase connection manager
├── db_operations.py       # Database CRUD operations
├── document_processor.py  # Document processing and chunking logic
├── models.py              # Pydantic models for API and database
├── main.py                # FastAPI application and endpoints
├── celery_tasks.py        # Celery tasks for background processing
├── search_api.py          # Search functionality (text, vector, hybrid)
├── start.py               # Start FastAPI server
├── start_worker.py        # Start Celery worker
├── start_services.py      # Start all services together
├── requirements.txt       # Python dependencies
├── .env.example           # Example environment variables
└── README.md              # This file
```

## Database Schema

### processing_jobs Table
```sql
CREATE TABLE public.processing_jobs (
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
```

### document_chunks Table
```sql
CREATE TABLE public.document_chunks (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  processing_job_id uuid,
  sharepoint_file_id text,
  file_path text,
  file_name text,
  content text,
  chunk_index integer,
  page_number integer DEFAULT 1,
  char_count integer DEFAULT 0,
  type ARRAY DEFAULT ARRAY['text'::text],
  original_content jsonb,
  embedding vector(384),  -- Enable pgvector extension
  fts tsvector DEFAULT to_tsvector('english'::regconfig, content),
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT document_chunks_pkey PRIMARY KEY (id),
  CONSTRAINT document_chunks_processing_job_id_fkey 
    FOREIGN KEY (processing_job_id) REFERENCES public.processing_jobs(id)
);
```

## Installation

1. **Clone the repository**
```bash
cd docling-exp
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Install and start Redis**
   - Windows: Download from https://github.com/microsoftarchive/redis/releases or use Docker
   - Linux: `sudo apt-get install redis-server && redis-server`
   - Mac: `brew install redis && brew services start redis`
   - Docker: `docker run -d -p 6379:6379 redis:latest`

5. **Set up Supabase**
   - Create a Supabase project at https://supabase.com
   - Enable the `pgvector` extension in your database
   - Create the tables using the SQL schema in `setup_database.sql`
   - Create a storage bucket named `documents`

6. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your Supabase credentials and Redis settings
```

## Configuration

Edit `.env` file with your settings:

```env
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_STORAGE_BUCKET=documents

# Celery/Redis Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
REDIS_HOST=localhost
REDIS_PORT=6379

# Embedding Model Configuration
EMBED_MODEL_ID=sentence-transformers/all-MiniLM-L6-v2
MAX_TOKENS=512
EMBEDDING_DIMENSION=384

# Server Configuration
HOST=0.0.0.0
PORT=8001
DEBUG=True
```

## Usage

### Start the Services

**Option 1: Start all services together (Recommended)**
```bash
python start_services.py
```

**Option 2: Start services separately**

Terminal 1 - FastAPI Server:
```bash
python start.py
```

Terminal 2 - Celery Worker:
```bash
python start_worker.py
```

**Option 3: Using Docker Compose**
```bash
docker-compose up -d
```

This starts Redis, FastAPI server, and Celery worker.

### Indexer Endpoints (Port 8001)

#### 1. Health Check
```bash
GET /health
GET /     # Returns module info
```

#### 2. Upload Document (Auto-starts Processing)
```bash
POST /api/indexer/upload
Content-Type: multipart/form-data

Parameters:
- file: File (required)
- user_id: string (optional)
- generate_embeddings: boolean (default: true)

Response:
{
  "job_id": "uuid",
  "upload_url": "supabase://...",
  "file_storage_path": "...",
  "message": "File uploaded successfully and processing started. Task ID: abc123"
}
```

**Note**: Processing now starts automatically via Celery task on upload!

#### 3. Check Task Status (New!)
```bash
GET /api/indexer/tasks/{task_id}

Response:
{
  "task_id": "abc123",
  "status": "SUCCESS",
  "ready": true,
  "successful": true,
  "failed": false
}
```

#### 4. Retry Failed Job
```bash
POST /api/indexer/retry
Content-Type: application/json

Body:
{
  "job_id": "uuid",
  "generate_embeddings": true
}

Response:
{
  "status": "started",
  "job_id": "uuid",
  "message": "Document indexing (re)started. Task ID: xyz789"
}
```

**Note**: This endpoint is now primarily for retrying failed jobs.

#### 5. Get Job Status
```bash
GET /api/indexer/jobs/{job_id}

Response:
{
  "id": "uuid",
  "status": "completed",
  "current_stage": "completed",
  "progress_info": {...},
  "file_name": "document.pdf",
  "file_size": 1024000,
  "started_at": "2024-01-01T00:00:00",
  "completed_at": "2024-01-01T00:01:00",
  "created_at": "2024-01-01T00:00:00"
}
```

#### 6. Get All Jobs
```bash
GET /api/indexer/jobs?status=completed&limit=100

Response: [
  {...job details...}
]
```

#### 7. Get Job Chunks
```bash
GET /api/indexer/jobs/{job_id}/chunks?with_embeddings=false

Response: [
  {
    "id": "uuid",
    "content": "chunk text...",
    "chunk_index": 0,
    "page_number": 1,
    "char_count": 500,
    "type": ["text", "table"],
    "has_embedding": true,
    "created_at": "2024-01-01T00:00:00"
  }
]
```

#### 8. Get Statistics
```bash
GET /api/indexer/stats

Response:
{
  "jobs": {
    "pending": 0,
    "processing": 1,
    "completed": 10,
    "failed": 0,
    "total": 11
  },
  "chunks": {
    "total_chunks": 150,
    "chunks_with_embeddings": 150,
    "chunks_without_embeddings": 0
  },
  "timestamp": "2024-01-01T00:00:00"
}
```

## Example Workflow

```python
import requests
import time

# 1. Upload document (processing starts automatically!)
with open('document.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8001/api/indexer/upload',
        files={'file': f},
        data={
            'user_id': 'user123',
            'generate_embeddings': 'true'
        }
    )
    result = response.json()
    job_id = result['job_id']
    print(f"Uploaded! Job ID: {job_id}")
    print(f"Message: {result['message']}")  # Includes Task ID

# 2. Poll for completion
while True:
    response = requests.get(f'http://localhost:8001/api/indexer/jobs/{job_id}')
    status = response.json()
    
    print(f"Status: {status['status']}, Stage: {status['current_stage']}")
    
    if status['status'] in ['completed', 'failed']:
        break
    
    time.sleep(2)

# 3. Get chunks when completed
if status['status'] == 'completed':
    response = requests.get(f'http://localhost:8001/api/indexer/jobs/{job_id}/chunks')
    chunks = response.json()
    print(f"Retrieved {len(chunks)} chunks")
```

## Document Processing Pipeline

1. **Upload**: File is uploaded to Supabase storage
2. **Download**: File is downloaded from storage for processing
3. **Chunking**: Document is processed using Docling:
   - Text extraction with context
   - Image extraction (base64 encoded)
   - Table extraction (markdown + HTML)
   - Smart chunking with token limits
4. **Embedding**: Optional embedding generation using Sentence Transformers
5. **Storage**: Chunks stored in Supabase with metadata

## Chunk Structure

Each chunk contains:
- **text**: Contextualized text content with %%IMAGE%% placeholders
- **images**: List of base64-encoded images with metadata
- **tables_markdown**: Tables in markdown format
- **tables_html**: Tables in HTML format
- **embedding**: Vector embedding (if enabled)
- **type**: List of content types (text, image, table)

## Supported File Types

- PDF (.pdf)
- Word Documents (.docx)
- PowerPoint (.pptx)
- Excel (.xlsx)
- Text Files (.txt)

## Module Scope

**This Indexer Module Handles**:
- ✅ Document upload to Supabase storage
- ✅ Background processing with Celery
- ✅ Document chunking with Docling
- ✅ Embedding generation
- ✅ Storage in `document_chunks` table
- ✅ Job tracking and status

**Future Modules Will Handle**:
- 🔲 **Retriever Module**: Search and retrieve chunks (text, vector, hybrid search)
- 🔲 **LLM Module**: RAG-based question answering with LLM

See [MODULE_ARCHITECTURE.md](MODULE_ARCHITECTURE.md) for the complete system design.

## Error Handling

The service includes comprehensive error handling:
- Invalid file types rejected
- File size limits enforced
- Database connection errors logged
- Processing errors captured in job status

## Development

### Running in Development Mode

```bash
python main.py
```

The server will reload automatically on code changes.

### Testing the API

Use the interactive docs at:
- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## Production Deployment

1. Set `DEBUG=False` in environment
2. Use production ASGI server (Gunicorn + Uvicorn)
3. Configure proper CORS origins
4. Set up SSL/TLS
5. Configure logging and monitoring
6. Use environment-specific Supabase credentials

## License

MIT License

## Contributing

Contributions are welcome! Please follow the existing code structure and include tests for new features.

