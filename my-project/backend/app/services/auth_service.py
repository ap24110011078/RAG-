"""Authentication business logic for users and JWT access tokens."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models import User


class AuthenticationError(Exception):
    """Base error for expected authentication failures."""


class DuplicateEmailError(AuthenticationError):
    """Raised when registration uses an email already owned by a user."""


class InvalidCredentialsError(AuthenticationError):
    """Raised when a login does not match an active user."""


class InactiveUserError(AuthenticationError):
    """Raised when an inactive user attempts to authenticate."""


class AuthService:
    """Async authentication service used by the future auth router (T012)."""

    @staticmethod
    def normalize_email(email: str) -> str:
        """Normalize email identity consistently for lookup and registration."""
        normalized = email.strip().casefold()
        if not normalized or "@" not in normalized:
            raise ValueError("A valid email address is required")
        return normalized

    async def get_user_by_email(
        self,
        session: AsyncSession,
        email: str,
    ) -> User | None:
        """Return the user for an email, or ``None`` when it is not registered."""
        normalized_email = self.normalize_email(email)
        result = await session.execute(select(User).where(User.email == normalized_email))
        return result.scalar_one_or_none()

    async def get_user_by_id(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> User | None:
        """Return a user by UUID without exposing password material."""
        return await session.get(User, user_id)

    async def register_user(
        self,
        session: AsyncSession,
        email: str,
        password: str,
    ) -> User:
        """Create and persist a user with a one-way password hash.

        The pre-check gives a useful domain error in normal operation. The
        unique database constraint remains authoritative for concurrent
        registrations; a race is handled by checking the row after rollback.
        """
        normalized_email = self.normalize_email(email)
        if not password:
            raise ValueError("Password must not be empty")

        existing_user = await self.get_user_by_email(session, normalized_email)
        if existing_user is not None:
            raise DuplicateEmailError("An account with this email already exists")

        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            is_active=True,
        )
        session.add(user)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            concurrent_user = await self.get_user_by_email(session, normalized_email)
            if concurrent_user is not None:
                raise DuplicateEmailError("An account with this email already exists") from exc
            raise

        await session.refresh(user)
        return user

    async def authenticate_user(
        self,
        session: AsyncSession,
        email: str,
        password: str,
    ) -> User | None:
        """Verify login credentials and return the user on success.

        ``None`` represents invalid email/password credentials so the router
        can return one generic response and avoid revealing which emails are
        registered. Inactive accounts have a distinct domain error because a
        valid credential must not activate or authorize them.
        """
        user = await self.get_user_by_email(session, email)
        if user is None or not verify_password(password, user.password_hash):
            return None
        if not user.is_active:
            raise InactiveUserError("User account is inactive")
        return user

    def create_user_access_token(
        self,
        user: User,
        *,
        additional_claims: Mapping[str, Any] | None = None,
    ) -> str:
        """Create an access token whose subject is the user's UUID."""
        if user.id is None:
            raise ValueError("User must be persisted before creating a token")
        return create_access_token(str(user.id), additional_claims=additional_claims)

    async def get_user_from_token(
        self,
        session: AsyncSession,
        token: str,
    ) -> User:
        """Resolve a valid JWT to an active database user.

        Invalid, expired, malformed, or user-less tokens all raise
        ``InvalidTokenError``. A valid token for an inactive account raises
        ``InactiveUserError``.
        """
        payload = decode_access_token(token)
        subject = payload["sub"]
        try:
            user_id = uuid.UUID(subject)
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidTokenError("Access token has an invalid user subject") from exc

        user = await self.get_user_by_id(session, user_id)
        if user is None:
            raise InvalidTokenError("Access token user does not exist")
        if not user.is_active:
            raise InactiveUserError("User account is inactive")
        return user


# A stateless service instance is safe to reuse across requests.
auth_service = AuthService()


# Module-level wrappers keep T012 imports concise while retaining a testable
# service class for callers that prefer dependency injection.
async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await auth_service.get_user_by_email(session, email)


async def register_user(session: AsyncSession, email: str, password: str) -> User:
    return await auth_service.register_user(session, email, password)


async def authenticate_user(
    session: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    return await auth_service.authenticate_user(session, email, password)


async def get_user_from_token(session: AsyncSession, token: str) -> User:
    return await auth_service.get_user_from_token(session, token)
