"""
Authentication service - business logic for user management.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID
import asyncpg

from .password import generate_password, hash_password, verify_password
from .jwt_handler import create_access_token, hash_token, get_token_expiry_seconds
from .models import UserResponse, SignupResponse, TokenResponse

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication service for user management."""

    def __init__(self, pool: Optional[asyncpg.Pool] = None):
        """
        Initialize auth service.

        Args:
            pool: PostgreSQL connection pool (optional, can be set later)
        """
        self.pool = pool

    def set_pool(self, pool: asyncpg.Pool):
        """Set the database connection pool."""
        self.pool = pool

    async def signup(self, email: str) -> SignupResponse:
        """
        Create a new user with generated password.

        Args:
            email: User's email address

        Returns:
            SignupResponse with generated password (shown once)

        Raises:
            ValueError: If email already exists
        """
        if not self.pool:
            raise RuntimeError("Database not connected")

        # Check if user exists
        existing = await self.pool.fetchrow(
            "SELECT id FROM users WHERE email = $1",
            email.lower()
        )
        if existing:
            raise ValueError("Email already registered")

        # Generate password
        password = generate_password(16)
        password_hash = hash_password(password)

        # Create user
        user_id = await self.pool.fetchval(
            """
            INSERT INTO users (email, password_hash)
            VALUES ($1, $2)
            RETURNING id
            """,
            email.lower(),
            password_hash
        )

        logger.info(f"[AUTH] New user created: {email}")

        return SignupResponse(
            user_id=str(user_id),
            email=email.lower(),
            generated_password=password,
        )

    async def signin(self, email: str, password: str) -> TokenResponse:
        """
        Authenticate user with email and password.

        Args:
            email: User's email
            password: User's password

        Returns:
            TokenResponse with JWT access token

        Raises:
            ValueError: If credentials are invalid
        """
        if not self.pool:
            raise RuntimeError("Database not connected")

        # Get user
        user = await self.pool.fetchrow(
            """
            SELECT id, email, password_hash, display_name, google_id, created_at
            FROM users
            WHERE email = $1 AND is_active = true
            """,
            email.lower()
        )

        if not user:
            raise ValueError("Invalid email or password")

        # Verify password
        if not verify_password(password, user["password_hash"]):
            raise ValueError("Invalid email or password")

        # Update last login
        await self.pool.execute(
            "UPDATE users SET last_login = NOW() WHERE id = $1",
            user["id"]
        )

        # Create token
        token = create_access_token(str(user["id"]), user["email"])

        # Store session
        await self._create_session(user["id"], token)

        logger.info(f"[AUTH] User signed in: {email}")

        return TokenResponse(
            access_token=token,
            expires_in=get_token_expiry_seconds(),
            user=UserResponse(
                id=str(user["id"]),
                email=user["email"],
                display_name=user["display_name"],
                is_google_linked=user["google_id"] is not None,
                created_at=user["created_at"],
            )
        )

    async def google_auth(self, google_id: str, email: str, name: Optional[str] = None) -> TokenResponse:
        """
        Authenticate or create user via Google OAuth.

        Args:
            google_id: Google user ID
            email: User's email from Google
            name: User's name from Google (optional)

        Returns:
            TokenResponse with JWT access token
        """
        if not self.pool:
            raise RuntimeError("Database not connected")

        # Check if user exists by google_id or email
        user = await self.pool.fetchrow(
            """
            SELECT id, email, display_name, google_id, created_at
            FROM users
            WHERE google_id = $1 OR email = $2
            """,
            google_id,
            email.lower()
        )

        if user:
            # Update google_id if not set
            if not user["google_id"]:
                await self.pool.execute(
                    "UPDATE users SET google_id = $1 WHERE id = $2",
                    google_id,
                    user["id"]
                )
            # Update last login
            await self.pool.execute(
                "UPDATE users SET last_login = NOW() WHERE id = $1",
                user["id"]
            )
            user_id = user["id"]
            display_name = user["display_name"] or name
            created_at = user["created_at"]
        else:
            # Create new user with Google (no password)
            password_hash = hash_password(generate_password(32))  # Random unused password
            user_id = await self.pool.fetchval(
                """
                INSERT INTO users (email, password_hash, display_name, google_id, last_login)
                VALUES ($1, $2, $3, $4, NOW())
                RETURNING id
                """,
                email.lower(),
                password_hash,
                name,
                google_id
            )
            display_name = name
            created_at = datetime.now(timezone.utc)
            logger.info(f"[AUTH] New Google user created: {email}")

        # Create token
        token = create_access_token(str(user_id), email.lower())

        # Store session
        await self._create_session(user_id, token)

        logger.info(f"[AUTH] Google signin: {email}")

        return TokenResponse(
            access_token=token,
            expires_in=get_token_expiry_seconds(),
            user=UserResponse(
                id=str(user_id),
                email=email.lower(),
                display_name=display_name,
                is_google_linked=True,
                created_at=created_at,
            )
        )

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """
        Change user's password.

        Args:
            user_id: User's UUID
            current_password: Current password for verification
            new_password: New password to set

        Returns:
            True if successful

        Raises:
            ValueError: If current password is wrong
        """
        if not self.pool:
            raise RuntimeError("Database not connected")

        # Get current password hash
        user = await self.pool.fetchrow(
            "SELECT password_hash FROM users WHERE id = $1",
            UUID(user_id)
        )

        if not user:
            raise ValueError("User not found")

        # Verify current password
        if not verify_password(current_password, user["password_hash"]):
            raise ValueError("Current password is incorrect")

        # Update password
        new_hash = hash_password(new_password)
        await self.pool.execute(
            "UPDATE users SET password_hash = $1 WHERE id = $2",
            new_hash,
            UUID(user_id)
        )

        logger.info(f"[AUTH] Password changed for user: {user_id}")
        return True

    async def signout(self, user_id: str, token: str) -> bool:
        """
        Sign out user by invalidating their session.

        Args:
            user_id: User's UUID
            token: Current JWT token to invalidate

        Returns:
            True if successful
        """
        if not self.pool:
            return True  # No DB, nothing to invalidate

        token_hash = hash_token(token)
        await self.pool.execute(
            "DELETE FROM user_sessions WHERE user_id = $1 AND token_hash = $2",
            UUID(user_id),
            token_hash
        )

        logger.info(f"[AUTH] User signed out: {user_id}")
        return True

    async def get_user(self, user_id: str) -> Optional[UserResponse]:
        """
        Get user info by ID.

        Args:
            user_id: User's UUID

        Returns:
            UserResponse or None
        """
        if not self.pool:
            return None

        user = await self.pool.fetchrow(
            """
            SELECT id, email, display_name, google_id, created_at
            FROM users
            WHERE id = $1 AND is_active = true
            """,
            UUID(user_id)
        )

        if not user:
            return None

        return UserResponse(
            id=str(user["id"]),
            email=user["email"],
            display_name=user["display_name"],
            is_google_linked=user["google_id"] is not None,
            created_at=user["created_at"],
        )

    async def _create_session(self, user_id: UUID, token: str):
        """Create a session record for the token."""
        if not self.pool:
            return

        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=get_token_expiry_seconds())

        await self.pool.execute(
            """
            INSERT INTO user_sessions (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            user_id,
            hash_token(token),
            expires_at
        )


# Global service instance
auth_service = AuthService()
