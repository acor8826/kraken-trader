"""
Google OAuth verification.
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


async def verify_google_token(credential: str) -> Optional[Dict[str, Any]]:
    """
    Verify Google ID token and extract user info.

    Args:
        credential: Google ID token from frontend

    Returns:
        Dict with google_id, email, name, picture or None if invalid
    """
    try:
        # Try to import google auth library
        from google.oauth2 import id_token
        from google.auth.transport import requests

        if not GOOGLE_CLIENT_ID:
            logger.error("[AUTH] GOOGLE_CLIENT_ID not configured")
            return None

        # Verify the token
        idinfo = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )

        # Verify issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            logger.warning("[AUTH] Invalid Google token issuer")
            return None

        return {
            "google_id": idinfo["sub"],
            "email": idinfo["email"],
            "name": idinfo.get("name"),
            "picture": idinfo.get("picture"),
            "email_verified": idinfo.get("email_verified", False),
        }

    except ImportError:
        logger.warning("[AUTH] google-auth library not installed, Google OAuth disabled")
        return None
    except ValueError as e:
        logger.warning(f"[AUTH] Invalid Google token: {e}")
        return None
    except Exception as e:
        logger.error(f"[AUTH] Google token verification error: {e}")
        return None
