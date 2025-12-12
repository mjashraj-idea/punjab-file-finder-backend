"""
Shared database connection and utilities for all modules
"""
from supabase import create_client, Client
from typing import Optional
import logging
import os

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
            supabase_url = os.getenv('SUPABASE_URL')
            supabase_key = os.getenv('SUPABASE_KEY')
            
            if not supabase_url or not supabase_key:
                raise ValueError("SUPABASE_URL and SUPABASE_KEY must be provided in environment variables")
            
            self._client = create_client(
                supabase_url=supabase_url,
                supabase_key=supabase_key
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
    
    def get_bucket(self, bucket_name: str):
        """Get Supabase storage bucket"""
        return self.client.storage.from_(bucket_name)


# Global instance (but client won't be initialized until first use)
supabase_connection = SupabaseConnection()


def get_supabase_client() -> Client:
    """Get Supabase client instance"""
    return supabase_connection.client


def get_storage_bucket(bucket_name: str = None):
    """Get Supabase storage bucket"""
    bucket_name = bucket_name or os.getenv('SUPABASE_STORAGE_BUCKET', 'documents')
    return supabase_connection.get_bucket(bucket_name)


