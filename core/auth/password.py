"""
Password generation and hashing utilities.
"""

import secrets
import string
import bcrypt


def generate_password(length: int = 16) -> str:
    """
    Generate a secure random password.

    Args:
        length: Password length (default 16)

    Returns:
        Secure random password with mixed characters
    """
    # Character sets
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%&*"

    # Ensure at least one of each type
    password = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]

    # Fill the rest randomly from all characters
    alphabet = uppercase + lowercase + digits + symbols
    password += [secrets.choice(alphabet) for _ in range(length - 4)]

    # Shuffle to randomize position of guaranteed characters
    secrets.SystemRandom().shuffle(password)

    return ''.join(password)


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Bcrypt hash of the password
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        password: Plain text password to verify
        hashed: Bcrypt hash to compare against

    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False
