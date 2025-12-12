"""
Main FastAPI application - Unified router for all modules
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Document Processing & Auth System",
    description="Unified API for Authentication, Document Indexing, and Administration",
    version="2.0.0",
    openapi_tags=[
        {
            "name": "auth",
            "description": "Authentication and user management"
        },
        {
            "name": "admin",
            "description": "Admin-only operations - dashboard, user management, logs, analytics"
        },
        {
            "name": "indexer",
            "description": "Document indexing operations - upload, process, and store documents"
        },
        {
            "name": "retriever",
            "description": "Document retrieval and search operations (Coming soon)"
        },
        {
            "name": "health",
            "description": "Health check endpoints"
        }
    ]
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import routers
from auth.api.routes import router as auth_router
from admin.api.routes import router as admin_router
from indexer.api.routes import router as indexer_router
from retriever.api.routes import router as retriever_router

# Include routers
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(indexer_router, prefix="/api/indexer", tags=["indexer"])
app.include_router(retriever_router, prefix="/api/retriever", tags=["retriever"])


@app.get("/", tags=["health"])
async def root():
    """Root endpoint"""
    return {
        "message": "Document Processing & Auth System API",
        "version": "2.0.0",
        "modules": {
            "auth": "/api/auth",
            "admin": "/api/admin",
            "indexer": "/api/indexer",
            "docs": "/docs"
        }
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "modules": {
            "auth": "active",
            "admin": "active",
            "indexer": "active",
            "retriever": "coming_soon"
        }
    }


# System health endpoint
@app.get("/api/system/health", tags=["health"])
async def system_health():
    """Get detailed system health status"""
    from shared.core.database import get_supabase_client
    from datetime import datetime
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
    # Check database connection
    try:
        client = get_supabase_client()
        # Simple query to test connection
        result = client.table('users').select('id', count='exact').limit(1).execute()
        health_status["checks"]["database"] = {
            "status": "healthy",
            "connected": True
        }
    except Exception as e:
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "connected": False,
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check Celery worker status (if available)
    try:
        from indexer.services.celery_tasks import celery_app
        # Try to inspect active workers
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        
        if active_workers:
            health_status["checks"]["celery"] = {
                "status": "healthy",
                "workers_active": len(active_workers),
                "workers": list(active_workers.keys())
            }
        else:
            health_status["checks"]["celery"] = {
                "status": "warning",
                "workers_active": 0,
                "message": "No active workers found"
            }
    except Exception as e:
        health_status["checks"]["celery"] = {
            "status": "unknown",
            "error": str(e)
        }
    
    return health_status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST"), port=int(os.getenv("PORT")))
