"""Shared FastAPI request dependencies.

Provides reusable dependencies for route handlers:
  - `SessionDep`: Injected request-scoped asynchronous SQLAlchemy session.
  - `bearer_scheme`: HTTP Authorization header bearer extraction.
  - `get_current_user`: Authentication resolver decoding JWT bearer tokens to active User rows.
  - `CurrentUser`: Injected authenticated User instance dependency.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security import decode_access_token

# Bearer token extractor; auto_error=False allows handling missing credentials manually with custom responses
bearer_scheme = HTTPBearer(auto_error=False)

# Typed dependency for request-scoped database session
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> User:
    """Resolve the bearer token to a user, or reject the request.

    The token is issued by this API and forwarded by the Next.js proxy; the
    browser never holds it directly. Swapping in Clerk/Auth0 later means replacing this one
    function.
    
    Args:
        session: Active asynchronous database session.
        credentials: Extracted HTTP Bearer authorization credentials.
        
    Returns:
        User: The authenticated user database entity.
        
    Raises:
        HTTPException (401): If credentials are missing, invalid, expired, or the user does not exist.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Decode and verify JWT signature and claims
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Load user from database by subject ID
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


# Typed dependency for the currently authenticated User
CurrentUser = Annotated[User, Depends(get_current_user)]

