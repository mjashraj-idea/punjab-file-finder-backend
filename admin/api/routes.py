"""
Admin API routes - Admin-only endpoints
"""
from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth.schemas import (
    UserCreate, UserResponse, UserUpdate,
    UserGroupCreate, UserGroupResponse,
    ActivityLogResponse, ErrorLogResponse
)
from auth.services.auth_service import auth_service
from auth.core.rbac import require_admin, require_permission
from shared.core.database import get_supabase_client
from shared.services.db_operations import DatabaseOperations

router = APIRouter()
db_ops = DatabaseOperations(get_supabase_client())


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/stats")
async def get_admin_stats(current_user: dict = Depends(require_admin)):
    """Get admin dashboard statistics for frontend cards"""
    from datetime import datetime, timedelta
    
    try:
        # Get total documents count
        docs_result = db_ops.client.table('processing_jobs').select('id', count='exact').execute()
        total_documents = docs_result.count if docs_result.count else 0
        
        # Get documents indexed today
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time()).isoformat()
        today_end = datetime.combine(today, datetime.max.time()).isoformat()
        
        today_jobs_result = db_ops.client.table('processing_jobs')\
            .select('id', count='exact')\
            .gte('created_at', today_start)\
            .lte('created_at', today_end)\
            .execute()
        indexed_today = today_jobs_result.count if today_jobs_result.count else 0
        
        # Get active users count
        active_users_result = db_ops.client.table('users')\
            .select('id', count='exact')\
            .eq('is_active', True)\
            .execute()
        active_users = active_users_result.count if active_users_result.count else 0
        
        # Get unresolved errors count
        unresolved_errors_result = db_ops.client.table('error_logs')\
            .select('id', count='exact')\
            .eq('resolved', False)\
            .execute()
        unresolved_errors = unresolved_errors_result.count if unresolved_errors_result.count else 0
        
        return {
            "total_documents": total_documents,
            "indexed_today": indexed_today,
            "active_users": active_users,
            "unresolved_errors": unresolved_errors
        }
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting admin stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard")
async def get_admin_dashboard(current_user: dict = Depends(require_admin)):
    """Get admin dashboard statistics (legacy endpoint)"""
    stats = db_ops.get_dashboard_statistics()
    return stats


# ============================================================
# USER MANAGEMENT
# ============================================================

@router.get("/users", response_model=List[UserResponse])
async def list_all_users(
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(require_admin)
):
    """Admin: List all users"""
    users = db_ops.get_all_users(limit=limit, offset=offset)
    
    # Enrich with role and permissions information
    for user in users:
        role = db_ops.get_user_role(user['id'])
        user['role'] = role.get('name') if role else None
        
        # Ensure permissions is a dict (it might be JSON string or None)
        if 'permissions' in user:
            if isinstance(user['permissions'], str):
                import json
                try:
                    user['permissions'] = json.loads(user['permissions'])
                except:
                    user['permissions'] = {}
            elif user['permissions'] is None:
                user['permissions'] = {}
        else:
            user['permissions'] = {}
        
        if 'password' in user:
            del user['password']  # Remove password from response
    
    return users


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    current_user: dict = Depends(require_admin)
):
    """Admin: Create new user"""
    hashed_password = auth_service.get_password_hash(user_in.password)
    
    try:
        new_user = db_ops.create_user(
            username=user_in.username,
            email=user_in.email,
            password=hashed_password,
            full_name=user_in.full_name,
            department=user_in.department,
            role_name=user_in.role,  # 'admin' or 'user'
            permissions=user_in.permissions
        )
        
        # Log user creation
        db_ops.create_activity_log(
            user_id=current_user['id'],
            user_name=current_user['full_name'] or current_user['username'],
            action="user_create",
            details=f"Created new user: {user_in.username}"
        )
        
        role = db_ops.get_user_role(new_user['id'])
        new_user['role'] = role.get('name') if role else None
        if 'password' in new_user:
            del new_user['password']
        
        return new_user
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Admin: Get user by ID"""
    user = db_ops.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = db_ops.get_user_role(user['id'])
    user['role'] = role.get('name') if role else None
    if 'password' in user:
        del user['password']
    
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_update: UserUpdate,
    current_user: dict = Depends(require_admin)
):
    """Admin: Update user"""
    update_data = user_update.dict(exclude_unset=True)
    
    # If password is being updated, hash it
    if 'password' in update_data:
        update_data['password'] = auth_service.get_password_hash(update_data['password'])
    
    updated_user = db_ops.update_user(user_id, update_data)
    
    # Log user update
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="user_update",
        details=f"Updated user: {user_id}"
    )
    
    role = db_ops.get_user_role(updated_user['id'])
    updated_user['role'] = role.get('name') if role else None
    if 'password' in updated_user:
        del updated_user['password']
    
    return updated_user


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Admin: Delete user (soft delete - set inactive)"""
    # Prevent self-deletion
    if user_id == current_user['id']:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    db_ops.update_user(user_id, {"is_active": False})
    
    # Log user deletion
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="user_delete",
        details=f"Deactivated user: {user_id}"
    )
    
    return {"success": True, "message": "User deactivated successfully"}


# ============================================================
# USER GROUPS MANAGEMENT
# ============================================================

@router.get("/groups", response_model=List[UserGroupResponse])
async def list_user_groups(
    current_user: dict = Depends(require_admin)
):
    """Admin: List all user groups"""
    groups = db_ops.get_all_user_groups()
    return groups


@router.post("/groups", response_model=UserGroupResponse)
async def create_user_group(
    group: UserGroupCreate,
    current_user: dict = Depends(require_admin)
):
    """Admin: Create new user group"""
    new_group = db_ops.create_user_group(
        name=group.name,
        description=group.description
    )
    
    # Log group creation
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="group_create",
        details=f"Created group: {group.name}"
    )
    
    return new_group


@router.post("/groups/{group_id}/members/{user_id}")
async def add_user_to_group(
    group_id: str,
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Admin: Add user to group"""
    db_ops.add_user_to_group(user_id, group_id)
    
    # Log membership addition
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="group_member_add",
        details=f"Added user {user_id} to group {group_id}"
    )
    
    return {"success": True, "message": "User added to group successfully"}


@router.delete("/groups/{group_id}/members/{user_id}")
async def remove_user_from_group(
    group_id: str,
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Admin: Remove user from group"""
    db_ops.remove_user_from_group(user_id, group_id)
    
    # Log membership removal
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="group_member_remove",
        details=f"Removed user {user_id} from group {group_id}"
    )
    
    return {"success": True, "message": "User removed from group successfully"}


@router.put("/groups/{group_id}", response_model=UserGroupResponse)
async def update_user_group(
    group_id: str,
    group_update: UserGroupCreate,
    current_user: dict = Depends(require_admin)
):
    """Admin: Update user group"""
    try:
        updated_group = db_ops.update_user_group(
            group_id=group_id,
            name=group_update.name,
            description=group_update.description
        )
        
        # Log group update
        db_ops.create_activity_log(
            user_id=current_user['id'],
            user_name=current_user['full_name'] or current_user['username'],
            action="group_update",
            details=f"Updated group: {group_update.name}"
        )
        
        return updated_group
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/groups/{group_id}")
async def delete_user_group(
    group_id: str,
    current_user: dict = Depends(require_admin)
):
    """Admin: Delete user group"""
    try:
        # Get group info before deletion for logging
        groups = db_ops.get_all_user_groups()
        group = next((g for g in groups if g['id'] == group_id), None)
        
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        db_ops.delete_user_group(group_id)
        
        # Log group deletion
        db_ops.create_activity_log(
            user_id=current_user['id'],
            user_name=current_user['full_name'] or current_user['username'],
            action="group_delete",
            details=f"Deleted group: {group.get('name', group_id)}"
        )
        
        return {"success": True, "message": "Group deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ACTIVITY LOGS
# ============================================================

@router.get("/activity-logs", response_model=List[ActivityLogResponse])
async def get_activity_logs(
    limit: int = 100,
    offset: int = 0,
    user_id: Optional[str] = None,
    current_user: dict = Depends(require_admin)
):
    """Admin: Get activity logs"""
    logs = db_ops.get_activity_logs(limit=limit, offset=offset, user_id=user_id)
    return logs


# ============================================================
# ERROR LOGS
# ============================================================

@router.get("/error-logs", response_model=List[ErrorLogResponse])
async def get_error_logs(
    limit: int = 100,
    offset: int = 0,
    resolved: Optional[bool] = None,
    current_user: dict = Depends(require_admin)
):
    """Admin: Get error logs"""
    logs = db_ops.get_error_logs(limit=limit, offset=offset, resolved=resolved)
    return logs


@router.put("/error-logs/{log_id}/resolve")
async def resolve_error_log(
    log_id: str,
    current_user: dict = Depends(require_admin)
):
    """Admin: Mark error log as resolved"""
    db_ops.resolve_error_log(log_id)
    
    # Log resolution
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="error_resolve",
        details=f"Resolved error log: {log_id}"
    )
    
    return {"success": True, "message": "Error log marked as resolved"}



# ============================================================
# DOCUMENT MANAGEMENT
# ============================================================

@router.get("/documents")
async def list_documents(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    current_user: dict = Depends(require_admin)
):
    """Admin: List all documents with pagination"""
    try:
        query = db_ops.client.table('processing_jobs').select('*')
        
        if status:
            query = query.eq('status', status)
        if file_type:
            query = query.eq('file_type', file_type)
        
        # Get total count
        count_query = db_ops.client.table('processing_jobs').select('id', count='exact')
        if status:
            count_query = count_query.eq('status', status)
        if file_type:
            count_query = count_query.eq('file_type', file_type)
        
        count_result = count_query.execute()
        total = count_result.count if count_result.count else 0
        
        # Get paginated results
        result = query.order('created_at', desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        documents = result.data if result.data else []
        
        # Format documents for frontend
        formatted_docs = []
        for doc in documents:
            formatted_docs.append({
                'id': doc.get('doc_id') or doc.get('id'),
                'name': doc.get('file_name', 'Unknown'),
                'type': doc.get('file_type', 'unknown'),
                'size': f"{doc.get('file_size', 0) / (1024 * 1024):.2f} MB" if doc.get('file_size') else "0 MB",
                'uploadedAt': doc.get('created_at'),
                'accessedAt': doc.get('updated_at'),
                'category': doc.get('metadata', {}).get('category', 'Uncategorized') if isinstance(doc.get('metadata'), dict) else 'Uncategorized',
                'tags': doc.get('metadata', {}).get('tags', []) if isinstance(doc.get('metadata'), dict) else [],
                'department': doc.get('metadata', {}).get('department', 'Unknown') if isinstance(doc.get('metadata'), dict) else 'Unknown',
                'restricted': doc.get('metadata', {}).get('restricted', False) if isinstance(doc.get('metadata'), dict) else False,
                'status': doc.get('status', 'unknown')
            })
        
        return {
            'data': formatted_docs,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': offset + limit < total
            }
        }
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error listing documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: dict = Depends(require_permission('can_delete'))
):
    """Admin/Permission: Force delete a document and all associated data"""
    try:
        # Check if document exists (via job lookup as main entry point)
        job = db_ops.get_processing_job_by_doc_id(doc_id)
        if not job:
            # Try checking chunks if job is missing (unlikely but possible for orphaned chunks)
            chunks = db_ops.get_chunks_by_doc_id(doc_id)
            if not chunks:
                 raise HTTPException(status_code=404, detail="Document not found")
        
        success = db_ops.delete_document(doc_id)
        
        if success:
            # Log deletion
            db_ops.create_activity_log(
                user_id=current_user['id'],
                user_name=current_user['full_name'] or current_user['username'],
                action="document_delete",
                details=f"Force deleted document: {doc_id}"
            )
            return {"success": True, "message": "Document deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete document")
            
    except HTTPException:
        raise
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error deleting document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# FILE ANALYTICS
# ============================================================

@router.get("/analytics/files")
async def get_file_analytics(
    current_user: dict = Depends(require_admin)
):
    """Admin: Get file processing analytics with enhanced data from documents table"""
    from datetime import datetime, timedelta
    from collections import defaultdict
    import json
    
    try:
        # Get all documents from the documents table
        docs_result = db_ops.client.table('documents')\
            .select('id, name, type, size_bytes, created_at, uploaded_at, department, metadata')\
            .execute()
            
        documents = docs_result.data if docs_result.data else []
        
        # File type distribution
        file_types = defaultdict(int)
        total_storage = 0
        
        # Indexed files by date (last 7 days including today)
        indexed_by_date = defaultdict(list)
        # Calculate date range for last 7 days (including today)
        today = datetime.utcnow().date()
        seven_days_ago_date = today - timedelta(days=6)  # Last 7 days including today
        
        # Stats for last 7 days
        stats_by_date = defaultdict(lambda: {'pdf': 0, 'doc': 0, 'ppt': 0, 'txt': 0, 'total': 0})
        
        for doc in documents:
            file_type = doc.get('type', 'unknown').lower()
            file_size = doc.get('size_bytes', 0) or 0
            # Use uploaded_at if available, otherwise created_at
            created_at = doc.get('uploaded_at') or doc.get('created_at')
            
            # Count file types (all files, not just last 7 days)
            if file_type == 'pdf':
                file_types['pdf'] += 1
            elif file_type in ['doc', 'docx']:
                file_types['doc'] += 1
            elif file_type in ['ppt', 'pptx']:
                file_types['ppt'] += 1
            elif file_type == 'txt':
                file_types['txt'] += 1
            
            # Calculate storage (all files)
            total_storage += file_size
            
            # Group by date for last 7 days (including today)
            if created_at:
                try:
                    # Parse the created_at timestamp
                    # Handle PostgreSQL timestamp format: '2025-12-12 12:58:42.508758+00'
                    doc_date = None
                    
                    if isinstance(created_at, str):
                        # Strategy 1: Extract just the date part (YYYY-MM-DD) - simplest and most reliable
                        # PostgreSQL format: '2025-12-12 12:58:42.508758+00'
                        # ISO format: '2025-12-12T12:58:42.508758+00:00'
                        # Both start with YYYY-MM-DD
                        try:
                            # Extract date part (first 10 characters should be YYYY-MM-DD)
                            date_str = created_at[:10]
                            # Validate it's a valid date format
                            if len(date_str) == 10 and date_str.count('-') == 2:
                                # Parse as date directly
                                from datetime import date as date_class
                                year, month, day = map(int, date_str.split('-'))
                                doc_date = date_class(year, month, day)
                            else:
                                raise ValueError(f"Invalid date format: {date_str}")
                        except Exception as date_parse_error:
                            # Fallback: try full datetime parsing
                            try:
                                # Handle PostgreSQL format with timezone
                                normalized = created_at
                                if '+' in normalized and normalized.count('+') == 1:
                                    # Replace '+00' with '+00:00' for proper ISO format
                                    normalized = normalized.replace('+00', '+00:00')
                                if ' ' in normalized and 'T' not in normalized:
                                    # Replace space with T for ISO format
                                    normalized = normalized.replace(' ', 'T', 1)
                                
                                doc_date_obj = datetime.fromisoformat(normalized)
                                doc_date = doc_date_obj.date()
                            except Exception as dt_parse_error:
                                logger = logging.getLogger(__name__)
                                logger.warning(f"Failed to parse date '{created_at}': {str(dt_parse_error)}")
                                continue  # Skip this document
                    elif isinstance(created_at, datetime):
                        doc_date = created_at.date()
                    elif hasattr(created_at, 'date'):
                        doc_date = created_at.date()
                    else:
                        # Unknown type, skip
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Unknown date type for document {doc.get('id')}: {type(created_at)}")
                        continue
                    
                    # Check if document is within last 7 days (including today)
                    # Compare dates directly (not datetime)
                    if doc_date >= seven_days_ago_date:
                        date_str = doc_date.isoformat()
                        
                        # Parse metadata if it's a string
                        doc_metadata = doc.get('metadata', {})
                        if isinstance(doc_metadata, str):
                            try:
                                doc_metadata = json.loads(doc_metadata)
                            except:
                                doc_metadata = {}
                        
                        # Get department from metadata or direct field
                        department = doc.get('department')
                        if not department and isinstance(doc_metadata, dict):
                            department = doc_metadata.get('department', 'Unknown')
                        if not department:
                            department = 'Unknown'
                        
                        indexed_by_date[date_str].append({
                            'id': str(doc.get('id', '')),
                            'name': doc.get('name', 'Unknown'),
                            'type': file_type,
                            'indexedAt': created_at if isinstance(created_at, str) else (created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)),
                            'size': f"{file_size / (1024 * 1024):.2f} MB" if file_size > 0 else "0 MB",
                            'department': department
                        })
                        
                        # Update stats by date
                        if file_type == 'pdf':
                            stats_by_date[date_str]['pdf'] += 1
                        elif file_type in ['doc', 'docx']:
                            stats_by_date[date_str]['doc'] += 1
                        elif file_type in ['ppt', 'pptx']:
                            stats_by_date[date_str]['ppt'] += 1
                        elif file_type == 'txt':
                            stats_by_date[date_str]['txt'] += 1
                        stats_by_date[date_str]['total'] += 1
                    else:
                        # Debug: log why file was excluded
                        logger = logging.getLogger(__name__)
                        logger.debug(f"Document {doc.get('id')} excluded: doc_date={doc_date}, seven_days_ago={seven_days_ago_date}, today={today}")
                except Exception as e:
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Error parsing date for document {doc.get('id')}: {created_at} (type: {type(created_at)}) - {str(e)}", exc_info=True)
                    pass
        
        # Format stats for last 7 days (fill missing dates with zeros)
        indexing_stats = []
        for i in range(7):
            date = (datetime.utcnow() - timedelta(days=6-i)).date()
            date_str = date.isoformat()
            stats = stats_by_date.get(date_str, {'pdf': 0, 'doc': 0, 'ppt': 0, 'txt': 0, 'total': 0})
            indexing_stats.append({
                'date': date_str,
                'pdf': stats['pdf'],
                'doc': stats['doc'],
                'ppt': stats['ppt'],
                'txt': stats['txt'],
                'total': stats['total']
            })
        
        return {
            'file_types': dict(file_types),
            'status_distribution': {},
            'total_files': len(documents),
            'total_storage_bytes': total_storage,
            'total_storage_mb': round(total_storage / (1024 * 1024), 2),
            'indexing_stats': indexing_stats,
            'indexed_files_by_date': dict(indexed_by_date)
        }
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting file analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
