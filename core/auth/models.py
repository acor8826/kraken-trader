"""
Pydantic models for authentication.
"""

from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional
from uuid import UUID


class SignupRequest(BaseModel):
    """Request model for user signup."""
    email: EmailStr


class SignupResponse(BaseModel):
    """Response model for signup - includes generated password (shown once)."""
    user_id: str
    email: str
    generated_password: str  # Shown ONCE to user
    message: str = "Account created. Save your password - it won't be shown again!"


class SigninRequest(BaseModel):
    """Request model for user signin."""
    email: EmailStr
    password: str = Field(..., min_length=1)


class GoogleAuthRequest(BaseModel):
    """Request model for Google OAuth."""
    credential: str  # Google ID token


class TokenResponse(BaseModel):
    """Response model for successful authentication."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserResponse"


class ChangePasswordRequest(BaseModel):
    """Request model for password change."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class UserResponse(BaseModel):
    """User data response model."""
    id: str
    email: str
    display_name: Optional[str] = None
    is_google_linked: bool = False
    created_at: datetime


class MessageResponse(BaseModel):
    """Generic message response."""
    success: bool
    message: str


class User(BaseModel):
    """Internal user model."""
    id: UUID
    email: str
    password_hash: str
    display_name: Optional[str] = None
    is_active: bool = True
    google_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


# Update forward reference
TokenResponse.model_rebuild()
