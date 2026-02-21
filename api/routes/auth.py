"""
Authentication API Routes.

Endpoints:
- POST /api/auth/signup        - Create account (returns generated password)
- POST /api/auth/signin        - Email + password login
- POST /api/auth/google        - Google OAuth token exchange
- POST /api/auth/change-password - Change password (authenticated)
- POST /api/auth/signout       - Invalidate session
- GET  /api/auth/me            - Get current user info
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import logging

from core.auth.models import (
    SignupRequest,
    SignupResponse,
    SigninRequest,
    TokenResponse,
    ChangePasswordRequest,
    UserResponse,
    MessageResponse,
    GoogleAuthRequest,
)
from core.auth.dependencies import get_current_user, security
from core.auth.service import auth_service
from core.auth.google_oauth import verify_google_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest):
    """
    Create a new user account.

    System generates a secure password and returns it ONCE.
    User should be prompted to save it immediately.
    """
    try:
        result = await auth_service.signup(request.email)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    except Exception as e:
        logger.error(f"[AUTH] Signup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account"
        )


@router.post("/signin", response_model=TokenResponse)
async def signin(request: SigninRequest):
    """
    Authenticate with email + password.
    Returns JWT access token on success.
    """
    try:
        result = await auth_service.signin(request.email, request.password)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    except Exception as e:
        logger.error(f"[AUTH] Signin error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )


@router.post("/google", response_model=TokenResponse)
async def google_auth(request: GoogleAuthRequest):
    """
    Exchange Google OAuth credential for JWT.
    Creates account if first login with Google.
    """
    try:
        # Verify Google token
        google_user = await verify_google_token(request.credential)
        if not google_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google credentials"
            )

        # Authenticate or create user
        result = await auth_service.google_auth(
            google_id=google_user["google_id"],
            email=google_user["email"],
            name=google_user.get("name")
        )
        return result

    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    except Exception as e:
        logger.error(f"[AUTH] Google auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google authentication failed"
        )


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Change password for authenticated user.
    Requires current password verification.
    """
    try:
        await auth_service.change_password(
            user_id=current_user["user_id"],
            current_password=request.current_password,
            new_password=request.new_password
        )
        return MessageResponse(success=True, message="Password updated successfully")

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"[AUTH] Change password error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )


@router.post("/signout", response_model=MessageResponse)
async def signout(
    current_user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Sign out and invalidate current session.
    """
    try:
        token = credentials.credentials if credentials else ""
        await auth_service.signout(current_user["user_id"], token)
        return MessageResponse(success=True, message="Signed out successfully")

    except Exception as e:
        logger.error(f"[AUTH] Signout error: {e}")
        # Still return success - best effort logout
        return MessageResponse(success=True, message="Signed out")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user info.
    """
    try:
        user = await auth_service.get_user(current_user["user_id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Get user error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user info"
        )
