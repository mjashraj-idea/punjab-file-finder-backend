#!/usr/bin/env python3
"""
Start all services: FastAPI server and Celery worker together
Run this to start the complete application stack
"""
import subprocess
import sys
import os
import time
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file from project root
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


def check_redis():
    """Check if Redis is available"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=2)
        r.ping()
        print("✓ Redis is running")
        return True
    except Exception as e:
        print(f"✗ Redis is not running: {str(e)}")
        print("\nPlease start Redis before running the services:")
        print("  - Windows: Start redis-server.exe")
        print("  - Linux/Mac: redis-server")
        print("  - Docker: docker run -d -p 6379:6379 redis:latest")
        return False


def main():
    """Start all services"""
    print("=" * 60)
    print("Starting Complete Application Stack")
    print("=" * 60)
    print()
    
    # Check if Redis is available
    if not check_redis():
        sys.exit(1)
    
    print()
    print("Starting services...")
    print()
    
    # Get the scripts directory
    scripts_dir = Path(__file__).parent
    
    # Start FastAPI server
    print("1. Starting FastAPI API Server on port 8001...")
    api_process = subprocess.Popen(
        [sys.executable, str(scripts_dir / "run_api_server.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait a bit for API to start
    time.sleep(2)
    
    # Start Celery worker
    print("2. Starting Celery Background Worker...")
    worker_process = subprocess.Popen(
        [sys.executable, str(scripts_dir / "run_celery_worker.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    print()
    print("=" * 60)
    print("✅ All services started successfully!")
    print("=" * 60)
    print()
    print("Services running:")
    print(f"  📡 FastAPI API Server: http://localhost:8001")
    print(f"  📚 API Documentation: http://localhost:8001/docs")
    print(f"  🔐 Auth Module: http://localhost:8001/api/auth")
    print(f"  📄 Indexer Module: http://localhost:8001/api/indexer")
    print(f"  ⚙️  Celery Worker: PID {worker_process.pid}")
    print()
    print("Press Ctrl+C to stop all services")
    print()
    
    try:
        # Keep both processes running
        api_process.wait()
        worker_process.wait()
    except KeyboardInterrupt:
        print("\n\nStopping services...")
        api_process.terminate()
        worker_process.terminate()
        print("✓ Services stopped.")


if __name__ == "__main__":
    main()



