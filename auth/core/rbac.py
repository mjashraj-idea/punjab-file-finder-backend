"""
Role-Based Access Control (RBAC) dependencies and utilities
Supports both individual user roles and group-based permissions
"""
from fastapi import HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from typing import List
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth.services.auth_service import auth_service
from shared.core.database import get_supabase_client
from shared.services.db_operations import DatabaseOperations

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
db_ops = DatabaseOperations(get_supabase_client())


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get current authenticated user"""
    token_data = auth_service.decode_access_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db_ops.get_user_by_username(token_data.username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.get('is_active'):
        raise HTTPException(status_code=403, detail="User account is inactive")
    
    return user


async def get_current_active_user(current_user: dict = Depends(get_current_user)):
    """Get current active user"""
    if not current_user.get('is_active'):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def check_user_has_role(user_id: str, required_role: str) -> bool:
    """Check if user has the required role"""
    role = db_ops.get_user_role(user_id)
    return role and role.get('name') == required_role


def check_user_in_groups(user_id: str, required_groups: List[str]) -> bool:
    """Check if user belongs to any of the required groups"""
    user_groups = db_ops.get_user_groups(user_id)
    user_group_names = [g['name'] for g in user_groups]
    return any(group in user_group_names for group in required_groups)


async def require_admin(current_user: dict = Depends(get_current_user)):
    """Require user to be admin (checks both role and admin group)"""
    # Get user's role
    role = db_ops.get_user_role(current_user['id'])
    
    # Check if user has admin role
    if role and role.get('name') == 'admin':
        return current_user
    
    # Check if user is in admin group
    if check_user_in_groups(current_user['id'], ['admin', 'administrators']):
        return current_user
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required. You don't have permission to perform this action."
    )


def require_roles(required_roles: List[str]):
    """Require user to have one of the specified roles"""
    async def role_checker(current_user: dict = Depends(get_current_user)):
        # Get user's role
        role = db_ops.get_user_role(current_user['id'])
        
        if not role or role.get('name') not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(required_roles)}"
            )
        
        return current_user
    
    return role_checker


def require_groups(required_groups: List[str]):
    """Require user to be in one of the specified groups"""
    async def group_checker(current_user: dict = Depends(get_current_user)):
        if not check_user_in_groups(current_user['id'], required_groups):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required groups: {', '.join(required_groups)}"
            )
        
        return current_user
    
    return group_checker


def require_role_or_group(required_role: str, required_groups: List[str]):
    """Require user to have either the specified role OR be in one of the specified groups"""
    async def role_or_group_checker(current_user: dict = Depends(get_current_user)):
        # Check role
        has_role = check_user_has_role(current_user['id'], required_role)
        
        # Check groups
        in_group = check_user_in_groups(current_user['id'], required_groups)
        
        if not (has_role or in_group):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required: role '{required_role}' OR groups {required_groups}"
            )
        
        return current_user
    
    return role_or_group_checker


def require_permission(permission_name: str):
    """
    Require user to have a specific permission flag in their 'permissions' JSON column.
    Admin role always grants access.
    """
    async def permission_checker(current_user: dict = Depends(get_current_user)):
        # 1. Admin always has access
        role = db_ops.get_user_role(current_user['id'])
        if role and role.get('name') == 'admin':
            return current_user
        
        # 2. Check permissions JSON
        user_permissions = current_user.get('permissions', {})
        # Warning: JSON might be null in DB, ensure it's a dict
        if user_permissions is None:
            user_permissions = {}
        
        # Handle string JSON if needed
        if isinstance(user_permissions, str):
            import json
            try:
                user_permissions = json.loads(user_permissions)
            except:
                user_permissions = {}
            
        # 3. Check specific flag - support both snake_case and camelCase
        # Mapping UI names to keys:
        # "Search Files" -> can_search or canSearch
        # "Upload Files" -> can_upload or canUpload
        # "Update Files" -> can_update or canUpdate
        # "Delete Files" -> can_delete or canDelete
        
        # Convert permission_name to both formats for checking
        # If permission_name is 'can_search', also check 'canSearch'
        # If permission_name is 'canSearch', also check 'can_search'
        def to_camel_case(snake_str: str) -> str:
            """Convert snake_case to camelCase"""
            components = snake_str.split('_')
            return components[0] + ''.join(x.capitalize() for x in components[1:])
        
        def to_snake_case(camel_str: str) -> str:
            """Convert camelCase to snake_case"""
            import re
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', camel_str)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        # Check both formats
        has_permission = (
            user_permissions.get(permission_name, False) or
            user_permissions.get(to_camel_case(permission_name), False) or
            user_permissions.get(to_snake_case(permission_name), False)
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required permission: {permission_name}"
            )
        
        return current_user

    return permission_checker

