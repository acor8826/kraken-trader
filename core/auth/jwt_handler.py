"""
JWT token generation and validation.
"""

import jwt
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)

# Configuration from environment
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "kraken-trading-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))


def create_access_token(user_id: str, email: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        user_id: User's UUID as string
        email: User's email address
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    payload = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a JWT token and return its payload.

    Args:
        token: JWT token string

    Returns:
        Token payload dict if valid, None if invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid token: {e}")
        return None


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode a JWT token without verification (for debugging).

    Args:
        token: JWT token string

    Returns:
        Token payload dict or None
    """
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None


def hash_token(token: str) -> str:
    """
    Create a hash of a token for storage (session tracking).

    Args:
        token: JWT token string

    Returns:
        SHA256 hash of the token
    """
    return hashlib.sha256(token.encode()).hexdigest()


def get_token_expiry_seconds() -> int:
    """Get token expiry time in seconds."""
    return ACCESS_TOKEN_EXPIRE_HOURS * 3600
