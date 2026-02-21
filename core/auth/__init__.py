"""
Authentication module for Kraken Trading Dashboard.

Provides:
- Password generation and hashing (bcrypt)
- JWT token creation and validation
- FastAPI dependencies for route protection
- Google OAuth integration
"""

from .models import (
    SignupRequest,
    SignupResponse,
    SigninRequest,
    TokenResponse,
    ChangePasswordRequest,
    UserResponse,
    MessageResponse,
    GoogleAuthRequest,
)
from .password import generate_password, hash_password, verify_password
from .jwt_handler import create_access_token, verify_token, decode_token
from .dependencies import get_current_user, get_current_user_optional

__all__ = [
    # Models
    "SignupRequest",
    "SignupResponse",
    "SigninRequest",
    "TokenResponse",
    "ChangePasswordRequest",
    "UserResponse",
    "MessageResponse",
    "GoogleAuthRequest",
    # Password
    "generate_password",
    "hash_password",
    "verify_password",
    # JWT
    "create_access_token",
    "verify_token",
    "decode_token",
    # Dependencies
    "get_current_user",
    "get_current_user_optional",
]
