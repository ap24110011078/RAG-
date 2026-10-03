"""Security primitives for password hashing and JWT access tokens."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Argon2 is memory-hard and is the project's preferred password-hashing
# algorithm. Passwords are never stored or logged in plaintext.
_password_context = CryptContext(schemes=["argon2"], deprecated="auto")


class InvalidTokenError(ValueError):
    """Raised when a JWT is malformed, expired, or fails validation."""


def hash_password(password: str) -> str:
    """Return a one-way Argon2 hash for ``password``.

    The plaintext value exists only for the duration of this call and is never
    returned by any authentication API.
    """
    if not password:
        raise ValueError("Password must not be empty")
    return _password_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Safely verify a plaintext password against a stored hash."""
    if not plain_password or not password_hash:
        return False
    try:
        return _password_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        # Invalid/corrupt stored hashes are treated as failed credentials.
        return False


def create_access_token(
    subject: str,
    *,
    expires_delta: timedelta | None = None,
    additional_claims: Mapping[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token for a user subject.

    ``sub`` is the stable user identifier, normally the user's UUID string.
    ``exp`` is always present and is validated by :func:`decode_access_token`.
    Callers may add non-sensitive claims, but must never put passwords or
    other secrets in ``additional_claims``.
    """
    if not subject:
        raise ValueError("Token subject must not be empty")

    now = datetime.now(UTC)
    lifetime = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    if lifetime <= timedelta(0):
        raise ValueError("Token expiration must be in the future")

    claims: dict[str, Any] = dict(additional_claims or {})
    claims["sub"] = str(subject)
    claims["iat"] = now
    claims["exp"] = now + lifetime

    return jwt.encode(
        claims,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    `python-jose` validates the signature, algorithm, and expiration claim.
    A missing or empty ``sub`` is rejected because authentication cannot map
    such a token to a database user.
    """
    if not token:
        raise InvalidTokenError("Access token is required")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except (JWTError, ValueError, TypeError) as exc:
        raise InvalidTokenError("Invalid or expired access token") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise InvalidTokenError("Access token has no valid subject")

    return dict(payload)


# Conventional aliases make the helpers easy to use from an OAuth2-style
# router without duplicating the underlying security implementation.
get_password_hash = hash_password
verify_password_hash = verify_password
create_jwt = create_access_token
decode_jwt = decode_access_token
