from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class Token(BaseModel):
    access_token: str
    token_type: str
    user: Dict[str, Any]

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    department: Optional[str] = None
    role: str = 'user'  # 'admin' or 'user'
    permissions: Optional[Dict[str, bool]] = {}

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    password: Optional[str] = None
    permissions: Optional[Dict[str, bool]] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str]
    department: Optional[str]
    role: Optional[str]
    permissions: Optional[Dict[str, Any]]
    is_active: bool
    created_at: str

class UserGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

class UserGroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str

class ActivityLogResponse(BaseModel):
    id: str
    user_id: Optional[str]
    user_name: Optional[str]
    action: str
    details: Optional[str]
    timestamp: str

class ErrorLogResponse(BaseModel):
    id: str
    type: Optional[str]
    message: Optional[str]
    details: Optional[str]
    resolved: bool
    timestamp: str
