"""
Auth API routes - User-facing endpoints only
"""
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth.schemas import Token, UserResponse, UserUpdate, PasswordChange
from auth.services.auth_service import auth_service
from auth.core.rbac import get_current_user
from shared.core.database import get_supabase_client
from shared.services.db_operations import DatabaseOperations

router = APIRouter()
db_ops = DatabaseOperations(get_supabase_client())


# ============================================================
# PUBLIC ENDPOINTS (No Authentication Required)
# ============================================================

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint - Returns access token"""
    user = auth_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user's role information
    role = db_ops.get_user_role(user['id'])
    
    # Get user's groups
    groups = db_ops.get_user_groups(user['id'])
    
    # Create access token
    access_token = auth_service.create_access_token(
        data={
            "sub": user['username'],
            "user_id": str(user['id']),
            "role": role.get('name') if role else None
        }
    )
    
    # Log login activity
    db_ops.create_activity_log(
        user_id=user['id'],
        user_name=user['full_name'] or user['username'],
        action="login",
        details="User logged in successfully"
    )
    
    # Update last login
    db_ops.update_user_last_login(user['id'])
    
    # Build response user object (sanitize)
    user_resp = {k: v for k, v in user.items() if k != 'password'}
    user_resp['role'] = role.get('name') if role else None
    user_resp['groups'] = [g['name'] for g in groups]
    
    return {"access_token": access_token, "token_type": "bearer", "user": user_resp}


# ============================================================
# USER ENDPOINTS (All Authenticated Users)
# ============================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user profile"""
    role = db_ops.get_user_role(current_user['id'])
    groups = db_ops.get_user_groups(current_user['id'])
    
    user_resp = {k: v for k, v in current_user.items() if k != 'password'}
    user_resp['role'] = role.get('name') if role else None
    user_resp['groups'] = [g['name'] for g in groups]
    
    return user_resp


@router.post("/password")
async def change_password(
    password_data: PasswordChange,
    current_user: dict = Depends(get_current_user)
):
    """Change user password"""
    if not auth_service.verify_password(password_data.old_password, current_user['password']):
        raise HTTPException(status_code=400, detail="Incorrect old password")
        
    new_hash = auth_service.get_password_hash(password_data.new_password)
    db_ops.update_user(current_user['id'], {"password": new_hash})
    
    # Log password change
    db_ops.create_activity_log(
        user_id=current_user['id'],
        user_name=current_user['full_name'] or current_user['username'],
        action="password_change",
        details="User changed their password"
    )
    
    return {"success": True, "message": "Password updated successfully"}


