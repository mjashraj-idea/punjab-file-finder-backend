#!/usr/bin/env python3
"""
Startup script for the unified FastAPI application
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Get project root (parent of scripts directory)
project_root = Path(__file__).parent.parent
os.chdir(project_root)  # Change to project root

# Add project root to Python path
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv(project_root / ".env")

# Check for required environment variables
required_vars = ["SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_STORAGE_BUCKET"]
missing_vars = [var for var in required_vars if not os.getenv(var)]

if missing_vars:
    print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
    print("\nPlease set these in your .env file:")
    for var in missing_vars:
        print(f"  {var}=your_value_here")
    sys.exit(1)

print("="*60)
print("Starting Unified API Server")
print("="*60)
print()
print("Configuration:")
print(f"  - Supabase URL: {os.getenv('SUPABASE_URL')}")
print(f"  - Storage Bucket: {os.getenv('SUPABASE_STORAGE_BUCKET')}")
print(f"  - Host: {os.getenv('HOST', '0.0.0.0')}")
print(f"  - Port: {os.getenv('PORT', '8001')}")
print(f"  - Debug/Reload: {os.getenv('DEBUG', 'True')}")
print()
print("Available modules:")
print(f"  - Auth: http://localhost:{os.getenv('PORT', '8001')}/api/auth")
print(f"  - Admin: http://localhost:{os.getenv('PORT', '8001')}/api/admin")
print(f"  - Indexer: http://localhost:{os.getenv('PORT', '8001')}/api/indexer")
print(f"  - Docs: http://localhost:{os.getenv('PORT', '8001')}/docs")
print()
print("Starting server...")
print("="*60)
print()

if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8001'))
    debug = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')
    
    # Start the FastAPI server
    import uvicorn
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info" if not debug else "debug"
    )

