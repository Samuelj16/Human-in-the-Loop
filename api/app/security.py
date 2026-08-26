"""Password hashing and JWT issue/verify.

Auth lives in the API (not Clerk/NextAuth) so the whole stack runs with zero
third-party signups, and so `user_id` exists from the very first migration
instead of being retrofitted once reports need an owner. The Next.js side keeps
the token in an httpOnly cookie; swapping in Clerk later means replacing
`get_current_user` and nothing else.
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
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_password_digest(password), bcrypt.gensalt()).decode("utf-8")
    return _BCRYPT_SHA256_PREFIX + hashed


def verify_password(password: str, hashed: str) -> bool:
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
    return not hashed.startswith(_BCRYPT_SHA256_PREFIX)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the user id, or None if the token is invalid/expired."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
