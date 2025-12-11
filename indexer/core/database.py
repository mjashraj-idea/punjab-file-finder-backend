from supabase import create_client, Client
from typing import Optional
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from indexer.core.config import settings

logger = logging.getLogger(__name__)


class SupabaseConnection:
    """Singleton Supabase connection manager"""
    
    _instance: Optional['SupabaseConnection'] = None
    _client: Optional[Client] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SupabaseConnection, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Don't initialize client here - do it lazily
        pass
    
    def _initialize_client(self):
        """Initialize Supabase client"""
        try:
            if not settings.supabase_url or not settings.supabase_key:
                raise ValueError("Supabase URL and Key must be provided in environment variables")
            
            self._client = create_client(
                supabase_url=settings.supabase_url,
                supabase_key=settings.supabase_key
            )
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {str(e)}")
            raise
    
    @property
    def client(self) -> Client:
        """Get Supabase client (lazy initialization)"""
        if self._client is None:
            self._initialize_client()
        return self._client
    
    def get_storage(self):
        """Get Supabase storage client"""
        return self.client.storage
    
    def get_bucket(self, bucket_name: str = None):
        """Get Supabase storage bucket"""
        bucket_name = bucket_name or settings.supabase_storage_bucket
        return self.client.storage.from_(bucket_name)


# Global instance (but client won't be initialized until first use)
supabase_connection = SupabaseConnection()


def get_supabase_client() -> Client:
    """Get Supabase client instance"""
    return supabase_connection.client


def get_storage_bucket(bucket_name: str = None):
    """Get storage bucket instance"""
    return supabase_connection.get_bucket(bucket_name)

