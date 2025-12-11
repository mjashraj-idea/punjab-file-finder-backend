#!/usr/bin/env python3
"""
Startup script for the Document Indexer service
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file from project root
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


def check_environment():
    """Check if required environment variables are set"""
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_KEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("ERROR: Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nPlease set these variables in your .env file or environment.")
        print("See .env.example for reference.")
        return False
    
    return True


def main():
    """Main startup function"""
    print("=" * 60)
    print("Starting Docling Document Indexer - INDEXER MODULE")
    print("=" * 60)
    print()
    
    # Check environment
    if not check_environment():
        sys.exit(1)
    
    # Import after environment check
    from indexer.core.config import settings
    
    print(f"Configuration:")
    print(f"  - Module: INDEXER")
    print(f"  - Host: {settings.host}")
    print(f"  - Port: {settings.port}")
    print(f"  - Debug: {settings.debug}")
    print(f"  - Embedding Model: {settings.embed_model_id}")
    print(f"  - Max Tokens: {settings.max_tokens}")
    print(f"  - Storage Bucket: {settings.supabase_storage_bucket}")
    print()
    
    print("Starting server...")
    print(f"API docs available at: http://{settings.host}:{settings.port}/docs")
    print()
    
    # Start uvicorn
    import uvicorn
    uvicorn.run(
        "indexer.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )


if __name__ == "__main__":
    main()

