"""Registration and login."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep
from app.ratelimit import limit_login, limit_registration
from app.models import User
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
    status_code=201,
    dependencies=[Depends(limit_registration)],
)
async def register(body: Credentials, session: SessionDep) -> TokenResponse:
    # SECURITY NOTE: Rate limiting bounds bursts, but self-registration still
    # creates a fresh per-user paid-work quota. Public deployments should require
    # a non-self-issued entitlement here (invitation, verified organization, or
    # billing tenant) rather than treating email uniqueness as an abuse boundary.
    """Create an account and return an access token.

    Throttled per IP: the per-user task quota only means something once an
    account exists, so registration needs its own limit.
    """
    email = body.email.lower()
    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="That email is already registered")

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
    """Exchange credentials for an access token."""
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    # Same message either way - do not leak which emails exist.
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(body.password)
        await session.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    """Return the authenticated account."""
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(user: CurrentUser, session: SessionDep) -> Response:
    """Delete the account and everything belonging to it.

    Reports, events, sources, and telemetry cascade from the user row, so this
    is a real deletion rather than a flag - which is what "we store your search
    history" obliges us to offer.
    """
    await session.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
