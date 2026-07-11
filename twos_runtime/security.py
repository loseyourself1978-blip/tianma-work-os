from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SessionToken, User, utc_now


HASH_NAME = "sha256"
HASH_ROUNDS = 240_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    password = password or ""
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters.")
    salt = salt or _b64(secrets.token_bytes(24))
    digest = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt.encode("ascii"), HASH_ROUNDS)
    return _b64(digest), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_owner(session: Session, username: str, password: str) -> User:
    if session.scalar(select(User)):
        raise ValueError("Owner account already exists.")
    password_hash, salt = hash_password(password)
    user = User(username=username.strip(), password_hash=password_hash, password_salt=salt, is_active=True)
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, username: str, password: str, ttl_seconds: int) -> tuple[User, str, SessionToken]:
    user = session.scalar(select(User).where(User.username == username, User.is_active == True))  # noqa: E712
    if not user or not verify_password(password, user.password_hash, user.password_salt):
        raise ValueError("Invalid username or password.")
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


def revoke_token(session: Session, raw_token: str) -> None:
    token = session.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw_token)))
    if token and not token.revoked_at:
        token.revoked_at = utc_now()


def user_for_token(session: Session, raw_token: str) -> User | None:
    token = session.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw_token)))
    if not token or token.revoked_at or token.expires_at <= utc_now():
        return None
    user = session.get(User, token.user_id)
    if not user or not user.is_active:
        return None
    return user
