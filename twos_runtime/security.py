from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SessionToken, User, utc_now


HASH_NAME = "sha256"
HASH_ROUNDS = 240_000
HASH_BYTES = hashlib.new(HASH_NAME).digest_size
SALT_BYTES = 24
GENERIC_AUTH_MESSAGE = "Incorrect username or password."


class AuthFailureReason(str, Enum):
    OWNER_NOT_FOUND = "owner_not_found"
    OWNER_INACTIVE = "owner_inactive"
    INVALID_OWNER_RECORD = "invalid_owner_record"
    PASSWORD_HASH_MISSING = "password_hash_missing"
    UNSUPPORTED_PASSWORD_HASH = "unsupported_password_hash"
    PASSWORD_VERIFICATION_FAILED = "password_verification_failed"
    DATABASE_READ_FAILED = "database_read_failed"


class AuthenticationError(ValueError):
    def __init__(self, reason: AuthFailureReason) -> None:
        self.reason = reason
        super().__init__(GENERIC_AUTH_MESSAGE)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _decode_b64(value: str) -> bytes | None:
    try:
        return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError):
        return None


def normalize_username(username: str) -> str:
    """Apply the one Owner username boundary rule without changing case."""
    if not isinstance(username, str):
        raise TypeError("Username must be text.")
    return username.strip()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if not isinstance(password, str):
        raise TypeError("Password must be text.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(password) > 200:
        raise ValueError("Password must be 200 characters or fewer.")
    salt = salt or _b64(secrets.token_bytes(SALT_BYTES))
    digest = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt.encode("ascii"), HASH_ROUNDS)
    return _b64(digest), salt


def password_record_issue(stored_hash: str | None, salt: str | None) -> AuthFailureReason | None:
    if not stored_hash:
        return AuthFailureReason.PASSWORD_HASH_MISSING
    if not isinstance(stored_hash, str):
        return AuthFailureReason.UNSUPPORTED_PASSWORD_HASH
    if not salt:
        return AuthFailureReason.UNSUPPORTED_PASSWORD_HASH
    if not isinstance(salt, str):
        return AuthFailureReason.UNSUPPORTED_PASSWORD_HASH
    decoded_hash = _decode_b64(stored_hash)
    decoded_salt = _decode_b64(salt)
    if decoded_hash is None or decoded_salt is None:
        return AuthFailureReason.UNSUPPORTED_PASSWORD_HASH
    if len(decoded_hash) != HASH_BYTES or len(decoded_salt) != SALT_BYTES:
        return AuthFailureReason.UNSUPPORTED_PASSWORD_HASH
    return None


def owner_record_issue(user: User | None) -> AuthFailureReason | None:
    if user is None:
        return AuthFailureReason.OWNER_NOT_FOUND
    if not isinstance(user.username, str):
        return AuthFailureReason.INVALID_OWNER_RECORD
    if not normalize_username(user.username):
        return AuthFailureReason.INVALID_OWNER_RECORD
    if not user.is_active:
        return AuthFailureReason.OWNER_INACTIVE
    return password_record_issue(user.password_hash, user.password_salt)


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    issue = password_record_issue(stored_hash, salt)
    if issue is not None:
        raise AuthenticationError(issue)
    candidate = _b64(
        hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt.encode("ascii"), HASH_ROUNDS)
    )
    return hmac.compare_digest(candidate, stored_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_owner(session: Session, username: str, password: str) -> User:
    if session.scalar(select(User)):
        raise ValueError("Owner account already exists.")
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Username is required.")
    if len(normalized_username) > 80:
        raise ValueError("Username must be 80 characters or fewer.")
    password_hash, salt = hash_password(password)
    user = User(username=normalized_username, password_hash=password_hash, password_salt=salt, is_active=True)
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, username: str, password: str, ttl_seconds: int) -> tuple[User, str, SessionToken]:
    normalized_username = normalize_username(username)
    user = session.scalar(select(User).order_by(User.id))
    if user is None:
        raise AuthenticationError(AuthFailureReason.OWNER_NOT_FOUND)
    issue = owner_record_issue(user)
    if issue is not None:
        raise AuthenticationError(issue)
    if normalize_username(user.username) != normalized_username:
        raise AuthenticationError(AuthFailureReason.OWNER_NOT_FOUND)
    if not verify_password(password, user.password_hash, user.password_salt):
        raise AuthenticationError(AuthFailureReason.PASSWORD_VERIFICATION_FAILED)
    if user.username != normalized_username:
        user.username = normalized_username
    raw_token = secrets.token_urlsafe(32)
    now = utc_now()
    token = SessionToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    session.add(token)
    session.flush()
    return user, raw_token, token


def recover_owner_credentials(
    session: Session,
    password: str,
    recovery_username: str | None = None,
    *,
    allow_valid_record: bool = False,
) -> User:
    """Repair exactly one Owner row from an explicit local maintenance flow."""
    users = session.scalars(select(User).order_by(User.id).limit(2)).all()
    if len(users) != 1 or (owner_record_issue(users[0]) is None and not allow_valid_record):
        raise ValueError("Owner recovery is unavailable.")
    user = users[0]
    username = normalize_username(user.username) if isinstance(user.username, str) else ""
    if not username or len(username) > 80:
        username = normalize_username(recovery_username or "")
    if not username:
        raise ValueError("Owner recovery requires a valid username.")
    if len(username) > 80:
        raise ValueError("Username must be 80 characters or fewer.")
    password_hash, salt = hash_password(password)
    user.username = username
    user.password_hash = password_hash
    user.password_salt = salt
    user.is_active = True
    now = utc_now()
    for token in session.scalars(select(SessionToken).where(SessionToken.user_id == user.id)).all():
        if token.revoked_at is None:
            token.revoked_at = now
    session.flush()
    if owner_record_issue(user) is not None:
        raise ValueError("Owner recovery could not create a valid Owner record.")
    return user


def revoke_token(session: Session, raw_token: str) -> None:
    token = session.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw_token)))
    if token and not token.revoked_at:
        token.revoked_at = utc_now()


def user_for_token(session: Session, raw_token: str) -> User | None:
    token = session.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw_token)))
    if not token or token.revoked_at or token.expires_at <= utc_now():
        return None
    user = session.get(User, token.user_id)
    if owner_record_issue(user) is not None:
        return None
    return user
