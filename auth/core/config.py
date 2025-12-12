import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env from project root
project_root = Path(__file__).parent.parent.parent
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

class Settings(BaseSettings):
    # Supabase Configuration (Shared)
    supabase_url: str = ""
    supabase_key: str = ""
    
    # Auth Configuration
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8002 # Different port from indexer
    debug: bool = True
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
