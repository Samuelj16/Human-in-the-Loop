"""Password hashing and JWT issue/verify.

Auth lives in the API (not Clerk/NextAuth) so the whole stack runs with zero
third-party signups, and so `user_id` exists from the very first migration
instead of being retrofitted once reports need an owner. The Next.js side keeps
the token in an httpOnly cookie; swapping in Clerk later means replacing
`get_current_user` and nothing else.

Security Design Details:
  - SHA-256 pre-hashing: Bcrypt has a hard 72-byte truncation limit. Passwords are
    pre-hashed with SHA-256 to ensure every byte of arbitrary-length passwords
    contributes to entropy while feeding a fixed 32-byte digest to bcrypt.
  - Versioned prefix (`$bcrypt-sha256$`): Allows transparent migration of legacy
    raw bcrypt hashes when users log in.
  - Constant-time password verification via bcrypt.
  - Standard JWT token issuance with UTC-based expiration.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# Pre-hash new passwords so every accepted byte contributes while bcrypt always
# receives a fixed-size input. Unmarked hashes are legacy raw-bcrypt records.
_MAX_PASSWORD_BYTES = 72
_BCRYPT_SHA256_PREFIX = "$bcrypt-sha256$"


def _password_digest(password: str) -> bytes:
    """Compute binary SHA-256 digest of a plaintext password.
    
    Args:
        password: Raw password string.
        
    Returns:
        bytes: 32-byte binary SHA-256 hash.
    """
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    """Hash a password for secure storage using bcrypt over SHA-256.

    Pre-hashes with SHA-256 so that arbitrary-length passwords do not suffer
    from bcrypt's 72-byte truncation boundary, preventing long password collision attacks.
    Prepends `$bcrypt-sha256$` prefix to identify modern format.
    
    Args:
        password: The plaintext password to hash.
        
    Returns:
        str: Encoded password hash with prefix for database persistence.
    """
    hashed = bcrypt.hashpw(_password_digest(password), bcrypt.gensalt()).decode("utf-8")
    return _BCRYPT_SHA256_PREFIX + hashed


def verify_password(password: str, hashed: str) -> bool:
    """Check a password against a stored hash, returning False on malformed input.
    
    Supports both modern `$bcrypt-sha256$` hashed passwords and legacy raw bcrypt hashes.
    
    Args:
        password: Raw password entered by the user.
        hashed: Stored password hash from the database.
        
    Returns:
        bool: True if password matches the hash, False otherwise.
    """
    try:
        if hashed.startswith(_BCRYPT_SHA256_PREFIX):
            encoded = hashed.removeprefix(_BCRYPT_SHA256_PREFIX).encode("utf-8")
            return bcrypt.checkpw(_password_digest(password), encoded)
        # Compatibility for existing records. The login route replaces a legacy
        # hash with the versioned full-password form after successful verification.
        legacy = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
        return bcrypt.checkpw(legacy, hashed.encode("utf-8"))
    except ValueError:
        return False


def password_needs_rehash(hashed: str) -> bool:
    """True when a stored hash predates the current bcrypt-sha256 format.
    
    Args:
        hashed: The stored password hash string.
        
    Returns:
        bool: True if the hash should be upgraded upon next successful login.
    """
    return not hashed.startswith(_BCRYPT_SHA256_PREFIX)


def create_access_token(user_id: str) -> str:
    """Issue a signed JWT access token for a user.
    
    Args:
        user_id: The unique subject identifier for the user.
        
    Returns:
        str: Signed JWT string containing sub, exp, and iat claims.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Decode and validate a JWT access token.
    
    Verifies signature and expiration against configured secret and algorithm.
    
    Args:
        token: The raw JWT string from Authorization header.
        
    Returns:
        str | None: The user ID (sub claim) if valid, None if invalid or expired.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None

