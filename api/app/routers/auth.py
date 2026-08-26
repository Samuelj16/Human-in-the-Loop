"""Authentication and user lifecycle router (`/api/auth`).

Handles:
  - Account registration with IP-based sliding window rate limiting.
  - Password credential verification with bcrypt pre-hashing and JWT issuance.
  - Current authenticated user inspection (`/api/auth/me`).
  - Account deletion with full database cascading cleanup.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep
from app.models import User
from app.ratelimit import limit_login, limit_registration
from app.schemas import Credentials, TokenResponse, UserOut
from app.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_registration)],
)
async def register(body: Credentials, session: SessionDep) -> TokenResponse:
    """Register a new user account and return an access token.
    
    Throttled per IP: the per-user task quota only means something once an
    account exists, so registration needs its own limit.
    
    Args:
        body: Email and password payload.
        session: Scoped database session.
        
    Returns:
        TokenResponse: Issued JWT access token.
        
    Raises:
        HTTPException (409): If email is already registered.
    """
    email = body.email.lower()
    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered.",
        )

    user = User(email=email, hashed_password=hash_password(body.password))
    session.add(user)
    await session.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(limit_login)],
)
async def login(body: Credentials, session: SessionDep) -> TokenResponse:
    """Exchange credentials for an access token.
    
    Args:
        body: Email and password payload.
        session: Scoped database session.
        
    Returns:
        TokenResponse: Fresh access token.
        
    Raises:
        HTTPException (401): If credentials do not match.
    """
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    # Same message either way - do not leak which emails exist.
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Rehash if stored hash uses legacy prefix/parameters
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(body.password)
        await session.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    """Return the profile of the currently authenticated account.
    
    Args:
        user: Resolved User instance from JWT bearer token.
        
    Returns:
        User: User account details.
    """
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(user: CurrentUser, session: SessionDep) -> Response:
    """Delete the account and everything belonging to it.

    Reports, events, sources, and telemetry cascade from the user row, so this
    is a real deletion rather than a flag - which is what "we store your search
    history" obliges us to offer.
    
    Args:
        user: Authenticated user.
        session: Database session.
        
    Returns:
        Response: 204 No Content response.
    """
    await session.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

