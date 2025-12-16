from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import UUID
import logging
import re
from supabase import Client
from shared.core.database import get_storage_bucket

logger = logging.getLogger(__name__)


def preprocess_search_query(query: str) -> str:
    """
    Preprocess search query to handle camelCase, normalize spacing, and improve matching.
    
    Examples:
    - "casediarydetails" -> "case diary details" (splits camelCase)
    - "CaseDiaryDetails" -> "case diary details"
    - "case diary details" -> "case diary details" (normalized)
    
    Args:
        query: Raw search query
        
    Returns:
        Preprocessed query string
    """
    if not query:
        return ""
    
    # Remove extra whitespace
    query = ' '.join(query.split())
    
    # Split camelCase/PascalCase into separate words
    # Pattern: insert space before capital letters (but not at start)
    query = re.sub(r'(?<!^)(?=[A-Z])', ' ', query)
    
    # Normalize to lowercase
    query = query.lower()
    
    # Remove extra spaces again after splitting
    query = ' '.join(query.split())
    
    return query


class DatabaseOperations:
    """Shared database operations for all modules (Auth, Indexer, Retriever, etc.)"""
    
    def __init__(self, client: Client):
        self.client = client
    
    # ============================================================
    # DOCUMENTS OPERATIONS (Indexer Module)
    # ============================================================

    def create_document(
        self,
        doc_id: str,
        name: str,
        type: str,
        size_bytes: Optional[int] = None,
        category: Optional[str] = None,
        department: Optional[str] = None,
        tags: Optional[List[str]] = None,
        restricted: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new document master record"""
        try:
            doc_data = {
                'id': doc_id,
                'name': name,
                'type': type,
                'size_bytes': size_bytes,
                'category': category,
                'department': department,
                'tags': tags,
                'restricted': restricted,
                'uploaded_at': datetime.utcnow().isoformat()
            }
            
            # Add metadata if provided
            if metadata:
                doc_data['metadata'] = metadata
            
            result = self.client.table('documents').insert(doc_data).execute()
            
            if result.data:
                logger.info(f"Created document record: {doc_id}")
                return result.data[0]
            else:
                raise Exception("Failed to create document record")
                
        except Exception as e:
            logger.error(f"Error creating document record: {str(e)}")
            raise
    
    def update_document_metadata(self, doc_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Update document metadata in the documents table"""
        try:
            update_data = {
                'metadata': metadata,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            result = self.client.table('documents')\
                .update(update_data)\
                .eq('id', doc_id)\
                .execute()
            
            if result.data:
                logger.info(f"Updated document metadata for: {doc_id}")
                return result.data[0]
            else:
                raise Exception(f"Document {doc_id} not found or update failed")
                
        except Exception as e:
            logger.error(f"Error updating document metadata: {str(e)}")
            raise

    # ============================================================
    # PROCESSING JOBS OPERATIONS (Indexer Module)
    # ============================================================
    
    def create_processing_job(
        self,
        doc_id: str,
        file_storage_path: str,
        file_name: str,
        file_type: str,
        file_size: Optional[int] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = 'pending',
        current_stage: str = 'uploaded'
    ) -> Dict[str, Any]:
        """Create a new processing job"""
        try:
            job_data = {
                'doc_id': doc_id,
                'file_storage_path': file_storage_path,
                'file_name': file_name,
                'file_type': file_type,
                'file_size': file_size,
                'user_id': user_id,
                'metadata': metadata or {},
                'status': status,
                'current_stage': current_stage
            }
            
            result = self.client.table('processing_jobs').insert(job_data).execute()
            
            if result.data:
                logger.info(f"Created processing job: {result.data[0]['id']} with doc_id: {doc_id}")
                return result.data[0]
            else:
                raise Exception("Failed to create processing job")
                
        except Exception as e:
            logger.error(f"Error creating processing job: {str(e)}")
            raise
    
    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get processing job by ID"""
        try:
            result = self.client.table('processing_jobs').select('*').eq('id', job_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting processing job: {str(e)}")
            return None
    
    def get_processing_job_by_doc_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get processing job by document ID"""
        try:
            result = self.client.table('processing_jobs').select('*').eq('doc_id', doc_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting processing job by doc_id: {str(e)}")
            return None
    
    def update_processing_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        current_stage: Optional[str] = None,
        progress_info: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Update processing job"""
        try:
            update_data = {'updated_at': datetime.utcnow().isoformat()}
            
            if status is not None:
                update_data['status'] = status
            if current_stage is not None:
                update_data['current_stage'] = current_stage
            if progress_info is not None:
                update_data['progress_info'] = progress_info
            if error_message is not None:
                update_data['error_message'] = error_message
            if started_at is not None:
                update_data['started_at'] = started_at.isoformat()
            if completed_at is not None:
                update_data['completed_at'] = completed_at.isoformat()
            
            result = self.client.table('processing_jobs').update(update_data).eq('id', job_id).execute()
            
            if result.data:
                return result.data[0]
            else:
                raise Exception(f"Failed to update job {job_id}")
                
        except Exception as e:
            logger.error(f"Error updating processing job: {str(e)}")
            raise
    
    def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document and all related data (chunks, jobs, access control)
        
        Args:
            doc_id: The UUID of the document to delete
            
        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # 1. Delete file from storage
            # First get the storage path from the job
            job = self.get_processing_job_by_doc_id(doc_id)
            if job and job.get('file_storage_path'):
                try:
                    storage_bucket = get_storage_bucket()
                    storage_bucket.remove([job['file_storage_path']])
                    logger.info(f"Deleted file from storage: {job['file_storage_path']}")
                except Exception as e:
                    logger.error(f"Error deleting file from storage: {str(e)}")
                    # Continue with DB deletion even if storage deletion fails
            
            # 2. Delete from database
            # Note: cascading deletes should handle chunks and access control if configured,
            # but we'll do explicit deletions to be safe and ensure order
            
            # Delete processing job (this often holds the main reference)
            self.client.table('processing_jobs').delete().eq('doc_id', doc_id).execute()
            
            # Delete document metadata (if it exists in a separate table, though schema seemed to link via jobs)
            # Based on schema check: `documents` table exists.
            self.client.table('documents').delete().eq('id', doc_id).execute()
            
            logger.info(f"Deleted document and related data for doc_id: {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {str(e)}")
            raise
            

    # ============================================================
    # DOCUMENT CHUNKS OPERATIONS (Indexer Module)
    # ============================================================
    
    def create_document_chunks_batch(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create multiple document chunks in batch"""
        try:
            # Process chunks in batches of 100 (Supabase limit)
            batch_size = 100
            all_results = []
            
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                
                # Prepare batch data
                batch_data = []
                for chunk in batch:
                    chunk_dict = {
                        'processing_job_id': str(chunk['processing_job_id']),
                        'doc_id': chunk.get('doc_id'),
                        'file_path': chunk.get('file_path'),
                        'file_name': chunk.get('file_name'),
                        'content': chunk['content'],
                        'chunk_index': chunk['chunk_index'],
                        'page_number': chunk.get('page_number', 1),
                        'char_count': chunk.get('char_count', 0),
                        'type': chunk.get('chunk_type', ['text']),
                        'original_content': chunk.get('original_content', {}),
                        'embedding': chunk.get('embedding')
                    }
                    batch_data.append(chunk_dict)
                
                result = self.client.table('document_chunks').insert(batch_data).execute()
                
                if result.data:
                    all_results.extend(result.data)
                else:
                    raise Exception(f"Failed to insert batch {i//batch_size + 1}")
            
            logger.info(f"Created {len(all_results)} document chunks")
            return all_results
            
        except Exception as e:
            logger.error(f"Error creating document chunks batch: {str(e)}")
            raise
    
    def get_chunks_by_job_id(self, job_id: str, with_embeddings: bool = False) -> List[Dict[str, Any]]:
        """Get all chunks for a processing job"""
        try:
            select_fields = '*' if with_embeddings else 'id,processing_job_id,doc_id,content,chunk_index,page_number,char_count,type,created_at'
            
            result = self.client.table('document_chunks')\
                .select(select_fields)\
                .eq('processing_job_id', job_id)\
                .order('chunk_index')\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting chunks by job_id: {str(e)}")
            return []
    
    def get_chunks_by_doc_id(self, doc_id: str, with_embeddings: bool = False) -> List[Dict[str, Any]]:
        """Get all chunks for a document by doc_id"""
        try:
            select_fields = '*' if with_embeddings else 'id,processing_job_id,doc_id,content,chunk_index,page_number,char_count,type,created_at'
            
            result = self.client.table('document_chunks')\
                .select(select_fields)\
                .eq('doc_id', doc_id)\
                .order('chunk_index')\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting chunks by doc_id: {str(e)}")
            return []
    
    # ============================================================
    # USER OPERATIONS (Auth Module)
    # ============================================================
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        department: Optional[str] = None,
        role_name: str = 'user',  # 'admin' or 'user'
        permissions: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new user"""
        try:
            # Get role_id from role name
            role = self.client.table('roles').select('id').eq('name', role_name).execute()
            role_id = role.data[0]['id'] if role.data else None
            
            user_data = {
                'username': username,
                'email': email,
                'password': password,
                'full_name': full_name,
                'department': department,
                'permissions': permissions or {},
                'role_id': role_id,
                'is_active': True
            }
            
            result = self.client.table('users').insert(user_data).execute()
            
            if result.data:
                logger.info(f"Created user: {username}")
                return result.data[0]
            else:
                raise Exception("Failed to create user")
                
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            raise
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username"""
        try:
            result = self.client.table('users').select('*').eq('username', username).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting user by username: {str(e)}")
            return None
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        try:
            result = self.client.table('users').select('*').eq('email', email).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting user by email: {str(e)}")
            return None
    
    def get_all_users(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get all users with pagination"""
        try:
            result = self.client.table('users')\
                .select('*')\
                .range(offset, offset + limit - 1)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting all users: {str(e)}")
            return []
    
    def update_user(self, user_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update user"""
        try:
            update_data['updated_at'] = datetime.utcnow().isoformat()
            
            result = self.client.table('users').update(update_data).eq('id', user_id).execute()
            
            if result.data:
                return result.data[0]
            else:
                raise Exception(f"Failed to update user {user_id}")
                
        except Exception as e:
            logger.error(f"Error updating user: {str(e)}")
            raise
    
    def get_user_role(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's role information"""
        try:
            result = self.client.table('users')\
                .select('role_id, roles(id, name, description)')\
                .eq('id', user_id)\
                .execute()
            
            if result.data and result.data[0].get('roles'):
                return result.data[0]['roles']
            return None
        except Exception as e:
            logger.error(f"Error getting user role: {str(e)}")
            return None
    
    def update_user_last_login(self, user_id: str):
        """Update user's last login timestamp"""
        try:
            self.client.table('users')\
                .update({'last_login': datetime.utcnow().isoformat()})\
                .eq('id', user_id)\
                .execute()
        except Exception as e:
            logger.error(f"Error updating last login: {str(e)}")
    
    # ============================================================
    # USER GROUPS OPERATIONS (Auth Module)
    # ============================================================
    
    def create_user_group(
        self,
        name: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a user group"""
        try:
            group_data = {
                'name': name,
                'description': description
            }
            
            result = self.client.table('user_groups').insert(group_data).execute()
            
            if result.data:
                logger.info(f"Created user group: {name}")
                return result.data[0]
            else:
                raise Exception("Failed to create user group")
                
        except Exception as e:
            logger.error(f"Error creating user group: {str(e)}")
            raise
    
    def get_all_user_groups(self) -> List[Dict[str, Any]]:
        """Get all user groups"""
        try:
            result = self.client.table('user_groups').select('*').execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting user groups: {str(e)}")
            return []
    
    def get_user_groups(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all groups that a user belongs to"""
        try:
            result = self.client.table('user_group_memberships')\
                .select('group_id, user_groups(id, name, description)')\
                .eq('user_id', user_id)\
                .execute()
            
            if result.data:
                return [membership['user_groups'] for membership in result.data if membership.get('user_groups')]
            return []
        except Exception as e:
            logger.error(f"Error getting user groups: {str(e)}")
            return []
    
    def add_user_to_group(self, user_id: str, group_id: str):
        """Add user to a group"""
        try:
            membership_data = {
                'user_id': user_id,
                'group_id': group_id
            }
            
            self.client.table('user_group_memberships').insert(membership_data).execute()
            logger.info(f"Added user {user_id} to group {group_id}")
        except Exception as e:
            logger.error(f"Error adding user to group: {str(e)}")
            raise
    
    def remove_user_from_group(self, user_id: str, group_id: str):
        """Remove user from a group"""
        try:
            self.client.table('user_group_memberships')\
                .delete()\
                .eq('user_id', user_id)\
                .eq('group_id', group_id)\
                .execute()
            logger.info(f"Removed user {user_id} from group {group_id}")
        except Exception as e:
            logger.error(f"Error removing user from group: {str(e)}")
            raise
    
    def update_user_group(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update a user group"""
        try:
            update_data = {}
            if name is not None:
                update_data['name'] = name
            if description is not None:
                update_data['description'] = description
            
            if not update_data:
                raise ValueError("At least one field (name or description) must be provided")
            
            update_data['updated_at'] = datetime.utcnow().isoformat()
            
            result = self.client.table('user_groups')\
                .update(update_data)\
                .eq('id', group_id)\
                .execute()
            
            if result.data:
                logger.info(f"Updated user group: {group_id}")
                return result.data[0]
            else:
                raise Exception(f"Group {group_id} not found")
                
        except Exception as e:
            logger.error(f"Error updating user group: {str(e)}")
            raise
    
    def delete_user_group(self, group_id: str):
        """Delete a user group"""
        try:
            # First, delete all memberships for this group
            self.client.table('user_group_memberships')\
                .delete()\
                .eq('group_id', group_id)\
                .execute()
            
            # Then delete the group itself
            self.client.table('user_groups')\
                .delete()\
                .eq('id', group_id)\
                .execute()
            
            logger.info(f"Deleted user group: {group_id}")
        except Exception as e:
            logger.error(f"Error deleting user group: {str(e)}")
            raise
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            result = self.client.table('users').select('*').eq('id', user_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting user by ID: {str(e)}")
            return None
    
    def get_file_analytics(self) -> Dict[str, Any]:
        """Get file processing analytics"""
        try:
            # Get file type distribution
            jobs = self.client.table('processing_jobs').select('file_type, status').execute()
            
            file_types = {}
            status_counts = {}
            
            if jobs.data:
                for job in jobs.data:
                    # Count file types
                    file_type = job.get('file_type', 'unknown')
                    file_types[file_type] = file_types.get(file_type, 0) + 1
                    
                    # Count statuses
                    status = job.get('status', 'unknown')
                    status_counts[status] = status_counts.get(status, 0) + 1
            
            return {
                'file_types': file_types,
                'status_distribution': status_counts,
                'total_files': len(jobs.data) if jobs.data else 0
            }
        except Exception as e:
            logger.error(f"Error getting file analytics: {str(e)}")
            return {}
    
    # ============================================================
    # ACTIVITY & ERROR LOGS OPERATIONS (Auth Module)
    # ============================================================
    
    def get_activity_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get activity logs with optional user filter"""
        try:
            query = self.client.table('activity_logs').select('*')
            
            if user_id:
                query = query.eq('user_id', user_id)
            
            result = query.order('timestamp', desc=True)\
                .range(offset, offset + limit - 1)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting activity logs: {str(e)}")
            return []
    
    def get_error_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        resolved: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Get error logs with optional resolved filter"""
        try:
            query = self.client.table('error_logs').select('*')
            
            if resolved is not None:
                query = query.eq('resolved', resolved)
            
            result = query.order('timestamp', desc=True)\
                .range(offset, offset + limit - 1)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting error logs: {str(e)}")
            return []
    
    def resolve_error_log(self, log_id: str):
        """Mark an error log as resolved"""
        try:
            self.client.table('error_logs')\
                .update({'resolved': True})\
                .eq('id', log_id)\
                .execute()
            logger.info(f"Resolved error log: {log_id}")
        except Exception as e:
            logger.error(f"Error resolving error log: {str(e)}")
            raise
    
    def get_dashboard_statistics(self) -> Dict[str, Any]:
        """Get dashboard statistics for admin"""
        try:
            # Get user count
            users_result = self.client.table('users').select('id', count='exact').execute()
            total_users = users_result.count if users_result.count else 0
            
            # Get active users count
            active_users_result = self.client.table('users').select('id', count='exact').eq('is_active', True).execute()
            active_users = active_users_result.count if active_users_result.count else 0
            
            # Get total documents/jobs
            jobs_result = self.client.table('processing_jobs').select('id', count='exact').execute()
            total_jobs = jobs_result.count if jobs_result.count else 0
            
            # Get completed jobs
            completed_jobs_result = self.client.table('processing_jobs').select('id', count='exact').eq('status', 'completed').execute()
            completed_jobs = completed_jobs_result.count if completed_jobs_result.count else 0
            
            # Get failed jobs
            failed_jobs_result = self.client.table('processing_jobs').select('id', count='exact').eq('status', 'failed').execute()
            failed_jobs = failed_jobs_result.count if failed_jobs_result.count else 0
            
            # Get unresolved errors
            error_logs_result = self.client.table('error_logs').select('id', count='exact').eq('resolved', False).execute()
            unresolved_errors = error_logs_result.count if error_logs_result.count else 0
            
            return {
                'users': {
                    'total': total_users,
                    'active': active_users,
                    'inactive': total_users - active_users
                },
                'documents': {
                    'total': total_jobs,
                    'completed': completed_jobs,
                    'failed': failed_jobs,
                    'processing': total_jobs - completed_jobs - failed_jobs
                },
                'errors': {
                    'unresolved': unresolved_errors
                }
            }
        except Exception as e:
            logger.error(f"Error getting dashboard statistics: {str(e)}")
            return {}
    
    # ============================================================
    # ACTIVITY LOG OPERATIONS (Auth Module)
    # ============================================================
    
    def create_activity_log(
        self,
        user_id: str,
        user_name: str,
        action: str,
        details: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create activity log entry"""
        try:
            log_data = {
                'user_id': user_id,
                'user_name': user_name,
                'action': action,
                'details': details,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Add ip_address if provided
            if ip_address:
                log_data['ip_address'] = ip_address
            
            # Note: metadata column doesn't exist in activity_logs table
            # If metadata is needed, it can be stored in the details field as JSON string
            # or the schema needs to be updated to include a metadata jsonb column
            
            result = self.client.table('activity_logs').insert(log_data).execute()
            
            if result.data:
                return result.data[0]
            else:
                raise Exception("Failed to create activity log")
                
        except Exception as e:
            logger.error(f"Error creating activity log: {str(e)}")
            raise

    # ============================================================
    # RETRIEVER OPERATIONS (New)
    # ============================================================
    
    def get_accessible_documents(self, user_id: str) -> Optional[List[str]]:
        """
        Get list of document IDs that the user has access to.
        Returns None if user is admin (access all), otherwise returns list of Allowed UUIDs.
        """
        try:
            # Check if user is admin
            possible_roles = self.get_user_role(user_id)
            # Handle list or dict return
            if isinstance(possible_roles, list):
                is_admin = any(r.get('name') == 'admin' for r in possible_roles)
            else:
                is_admin = (possible_roles and possible_roles.get('name') == 'admin')

            if is_admin:
                return None  # None means all access in our search logic

            # 1. Get all Public documents
            public_docs = self.client.table('documents').select('id').eq('restricted', False).execute()
            doc_ids = {item['id'] for item in public_docs.data} if public_docs.data else set()

            # 2. Get documents explicitly shared with user
            user_access = self.client.table('document_access_control') \
                .select('document_id') \
                .eq('accessor_type', 'user') \
                .eq('accessor_id', user_id) \
                .execute()
            if user_access.data:
                doc_ids.update(item['document_id'] for item in user_access.data)

            # 3. Get documents shared with user's groups
            user_groups = self.get_user_groups(user_id)
            if user_groups:
                group_ids = [g['id'] for g in user_groups]
                if group_ids:
                    group_access = self.client.table('document_access_control') \
                        .select('document_id') \
                        .eq('accessor_type', 'group') \
                        .in_('accessor_id', group_ids) \
                        .execute()
                    if group_access.data:
                        doc_ids.update(item['document_id'] for item in group_access.data)
            
            return list(doc_ids)

        except Exception as e:
            logger.error(f"Error getting accessible documents: {str(e)}")
            # Fail safe: return empty list logic must be handled by caller or here
            # Returning empty list means 'no documents'
            return []

    def search_documents(
        self,
        query_text: str,
        query_embedding: Optional[List[float]],
        match_count: int = 1,  # Return only best chunk
        filter_doc_ids: Optional[List[str]] = None,
        mode: str = 'keyword',  # keyword, semantic, fuzzy
        similarity_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Search document chunks using RPC functions with enhanced matching.
        Supports camelCase splitting, partial matching, and fuzzy search.
        """
        try:
            # Preprocess query to handle camelCase and normalize
            processed_query = preprocess_search_query(query_text)
            
            params = {
                'match_count': match_count,
                'filter_doc_ids': filter_doc_ids
            }

            rpc_function = ''
            
            if mode == 'semantic':
                if not query_embedding:
                     raise ValueError("Query embedding required for semantic search")
                # Use Hybrid Search (Semantic = Hybrid in this context)
                rpc_function = 'hybrid_search_chunks'
                params.update({
                    'query_embedding': query_embedding,
                    'query_text': processed_query,  # Use processed query
                    'vector_weight': 0.75,
                    'keyword_weight': 0.25,
                    'similarity_threshold': similarity_threshold
                })
            
            elif mode == 'keyword':
                # Enhanced keyword search with FTS + ILIKE fallback
                # Using _enhanced suffix to keep old function as backup
                rpc_function = 'keyword_search_chunks_enhanced'
                params.update({
                    'query_text': processed_query  # Use processed query
                })
                
            elif mode == 'fuzzy':
                # Use dedicated fuzzy search function with pattern matching
                # Using _enhanced suffix to keep old function as backup
                rpc_function = 'fuzzy_search_chunks_enhanced'
                params.update({
                    'query_text': processed_query  # Use processed query
                })
            
            else:
                raise ValueError(f"Invalid search mode: {mode}")

            result = self.client.rpc(rpc_function, params).execute()
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"Error searching documents ({mode}): {str(e)}")
            return []

