import hashlib
import hmac
import secrets
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from redis import Redis
from sqlalchemy.orm import Session

from database import get_db
from models import User
from settings import settings

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


def hash_password(password: str) -> str:
    _validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None or len(password.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _validate_password(password: str) -> None:
    length = len(password.encode("utf-8"))
    if length < 12 or length > 72:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be between 12 and 72 UTF-8 bytes.",
        )


def session_key(token: str) -> str:
    digest = hmac.new(
        settings.session_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"session:{digest}"


def create_session(user: User) -> str:
    token = secrets.token_urlsafe(32)
    redis_client.set(
        session_key(token),
        str(user.id),
        ex=settings.session_ttl_seconds,
    )
    return token


def delete_session(token: str | None) -> None:
    if token:
        redis_client.delete(session_key(token))


def enforce_login_rate_limit(email: str) -> None:
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    key = f"login-attempts:{email_hash}"
    attempts = redis_client.incr(key)
    if attempts == 1:
        redis_client.expire(key, 60)
    if attempts > 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a minute.",
        )


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    user_id = redis_client.get(session_key(token))
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )
    user = db.get(User, UUID(user_id))
    if user is None or not user.is_active:
        delete_session(token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is unavailable.",
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )
    return user


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def create_oidc_state() -> tuple[str, str, str]:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    redis_client.set(
        f"oidc-state:{hashlib.sha256(state.encode()).hexdigest()}",
        f"{nonce}:{verifier}",
        ex=600,
    )
    return state, nonce, verifier


def consume_oidc_state(state: str) -> tuple[str, str] | None:
    key = f"oidc-state:{hashlib.sha256(state.encode()).hexdigest()}"
    stored = redis_client.getdel(key)
    if not stored or ":" not in stored:
        return None
    nonce, verifier = stored.split(":", 1)
    return nonce, verifier
