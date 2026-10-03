"""Authentication endpoints: register, login, and current-user retrieval.

Task: T012
Spec: FR-001 (authenticate users), plan.md §4 (auth router).

Endpoints:
- POST /register  — create a new user account
- POST /login     — authenticate and receive a JWT access token
- GET  /me        — retrieve the authenticated user's profile

All authentication and password logic is delegated to the T011
security/auth_service layer. This router is intentionally thin.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, oauth2_scheme
from app.db.models import User
from app.db.session import get_db_session
from app.services.auth_service import (
    DuplicateEmailError,
    InactiveUserError,
    auth_service,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ===========================================================================
# Request / Response schemas (Pydantic v2)
# ===========================================================================


class RegisterRequest(BaseModel):
    """Payload for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    """Payload for user login."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """JWT access token returned on successful login."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Public user profile — never includes the password hash."""

    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================================
# Endpoints
# ===========================================================================


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """Create a new user account.

    Returns the created user profile (without password) on success.
    Returns 409 if the email is already registered.
    """
    try:
        user = await auth_service.register_user(db, body.email, body.password)
    except DuplicateEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive an access token",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Authenticate with email and password.

    Returns a JWT access token on success.
    Returns 401 for invalid credentials.
    Returns 403 for inactive accounts.
    """
    try:
        user = await auth_service.authenticate_user(db, body.email, body.password)
    except InactiveUserError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email format",
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = auth_service.create_user_access_token(user)
    return TokenResponse(access_token=access_token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the profile of the currently authenticated user.

    Requires a valid Bearer token in the Authorization header.
    """
    return UserResponse.model_validate(current_user)
