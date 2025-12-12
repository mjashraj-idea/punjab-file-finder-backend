"""
Shared core module - Database connections and utilities
"""
from .database import (
    SupabaseConnection,
    supabase_connection,
    get_supabase_client,
    get_storage_bucket
)

__all__ = [
    'SupabaseConnection',
    'supabase_connection',
    'get_supabase_client',
    'get_storage_bucket'
]


