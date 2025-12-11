#!/usr/bin/env python3
"""
Start Celery worker for document processing
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
        print("WARNING: Missing environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nCelery worker may not function properly without these.")
        return False
    
    return True


def main():
    """Main function to start Celery worker"""
    print("=" * 60)
    print("Starting Celery Worker - INDEXER MODULE")
    print("=" * 60)
    print()
    
    # Check environment
    check_environment()
    
    # Import after environment check
    from indexer.core.config import settings
    
    print(f"Configuration:")
    print(f"  - Module: INDEXER")
    print(f"  - Broker: {settings.celery_broker_url}")
    print(f"  - Backend: {settings.celery_result_backend}")
    print(f"  - Embedding Model: {settings.embed_model_id}")
    print()
    
    print("Starting Celery worker...")
    print("Press Ctrl+C to stop")
    print()
    
    # Start Celery worker using os.system
    os.system(
        'celery -A indexer.services.celery_tasks worker '
        '--loglevel=info '
        '--concurrency=2 '
        '--max-tasks-per-child=10 '
        '--task-events '
        '--without-gossip '
        '--without-mingle '
        '--without-heartbeat'
    )


if __name__ == "__main__":
    main()

