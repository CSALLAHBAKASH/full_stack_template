import base64
import hashlib
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request as FastAPIRequest, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import LoginRequest, UserCreate, UserResponse, UserUpdate, normalize_email
from security import (
    clear_session_cookie,
    consume_oidc_state,
    create_oidc_state,
    create_session,
    delete_session,
    enforce_login_rate_limit,
    get_current_user,
    hash_password,
    redis_client,
    require_admin,
    set_session_cookie,
    verify_password,
)
from settings import settings

router = APIRouter()
oidc_router = APIRouter()


@router.post("/auth/login", response_model=UserResponse)
def login(
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    if not settings.password_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Password sign-in is disabled.",
        )
    enforce_login_rate_limit(credentials.email)
    user = db.scalar(select(User).where(User.email == credentials.email))
    if (
        user is None
        or not user.is_active
        or not verify_password(credentials.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    redis_client.delete(
        f"login-attempts:{hashlib.sha256(credentials.email.encode('utf-8')).hexdigest()}"
    )
    set_session_cookie(response, create_session(user))
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: FastAPIRequest,
    response: Response,
) -> Response:
    delete_session(request.cookies.get(settings.session_cookie_name))
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=UserResponse)
def current_user(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/auth/config")
def auth_config() -> dict[str, bool]:
    return {
        "password_enabled": settings.password_auth_enabled,
        "oidc_enabled": settings.oidc_enabled,
    }


@router.get("/users", response_model=list[UserResponse])
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())).all())


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = User(
        email=payload.email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists.",
        ) from exc
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    new_role = payload.role if payload.role is not None else user.role
    new_active = payload.is_active if payload.is_active is not None else user.is_active
    loses_admin = user.role == "admin" and (new_role != "admin" or not new_active)
    if user.id == admin.id and loses_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own active administrator access.",
        )
    if loses_admin:
        active_admins = db.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin",
                User.is_active.is_(True),
            )
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The last active administrator cannot be removed.",
            )

    user.role = new_role
    user.is_active = new_active
    db.commit()
    db.refresh(user)
    return user


def _oidc_configuration() -> dict:
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC sign-in is not configured.",
        )
    cache_key = f"oidc-discovery:{settings.oidc_issuer_url}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    discovery = _fetch_json(
        f"{settings.oidc_issuer_url}/.well-known/openid-configuration"
    )
    if discovery.get("issuer") != settings.oidc_issuer_url:
        raise HTTPException(status_code=502, detail="OIDC issuer did not match configuration.")
    required = ("authorization_endpoint", "token_endpoint", "jwks_uri")
    if any(not discovery.get(name) for name in required):
        raise HTTPException(status_code=502, detail="OIDC discovery document is incomplete.")
    redis_client.set(cache_key, json.dumps(discovery), ex=3600)
    return discovery


def _fetch_json(url: str, data: dict | None = None, headers: dict | None = None) -> dict:
    body = urlencode(data).encode("utf-8") if data is not None else None
    request = Request(
        url,
        data=body,
        headers=headers or {},
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="OIDC provider request failed.") from exc


@oidc_router.get("/start")
def oidc_start() -> RedirectResponse:
    discovery = _oidc_configuration()
    state, nonce, verifier = create_oidc_state()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    query = urlencode(
        {
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(
        f"{discovery['authorization_endpoint']}?{query}",
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        "oidc_state",
        state,
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/auth/oidc/callback",
    )
    return response


@oidc_router.get("/callback")
def oidc_callback(
    request: FastAPIRequest,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail="OIDC sign-in was not completed.")
    if (
        not code
        or not state
        or not secrets.compare_digest(state, request.cookies.get("oidc_state", ""))
    ):
        raise HTTPException(status_code=400, detail="Invalid OIDC callback state.")
    stored_state = consume_oidc_state(state)
    if not stored_state:
        raise HTTPException(status_code=400, detail="OIDC sign-in expired. Please try again.")
    expected_nonce, verifier = stored_state
    discovery = _oidc_configuration()
    basic = base64.b64encode(
        f"{settings.oidc_client_id}:{settings.oidc_client_secret}".encode()
    ).decode("ascii")
    token_response = _fetch_json(
        discovery["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.oidc_redirect_uri,
            "code_verifier": verifier,
        },
        {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    id_token = token_response.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="OIDC provider returned no ID token.")
    claims = _verify_id_token(id_token, discovery, expected_nonce)

    subject = claims.get("sub")
    email_claim = claims.get("email")
    if (
        not isinstance(subject, str)
        or not isinstance(email_claim, str)
        or claims.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=403,
            detail="OIDC sign-in requires a verified email address.",
        )
    try:
        email = normalize_email(email_claim)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="OIDC email address is invalid.") from exc
    user = db.scalar(
        select(User).where(
            User.oidc_issuer == settings.oidc_issuer_url,
            User.oidc_subject == subject,
        )
    )
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and (user.oidc_subject or user.oidc_issuer):
            raise HTTPException(
                status_code=409,
                detail="This email is already linked to another OIDC identity.",
            )
        if user is not None and not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled.")
        if user is None:
            full_name = claims.get("name")
            user = User(
                email=email,
                full_name=full_name[:200] if isinstance(full_name, str) else "",
                role="user",
            )
            db.add(user)
        user.oidc_issuer = settings.oidc_issuer_url
        user.oidc_subject = subject
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="OIDC account could not be linked.") from exc
        db.refresh(user)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled.")

    response = RedirectResponse(f"{settings.frontend_url}/", status_code=302)
    response.delete_cookie(
        "oidc_state",
        path="/auth/oidc/callback",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    set_session_cookie(response, create_session(user))
    return response


def _verify_id_token(id_token: str, discovery: dict, expected_nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise JWTError("Unsupported OIDC signing algorithm.")
        jwks_key = f"oidc-jwks:{settings.oidc_issuer_url}"
        cached = redis_client.get(jwks_key)
        jwks = json.loads(cached) if cached else _fetch_json(discovery["jwks_uri"])
        if not cached:
            redis_client.set(jwks_key, json.dumps(jwks), ex=3600)
        key = next(
            (item for item in jwks.get("keys", []) if item.get("kid") == header["kid"]),
            None,
        )
        if key is None:
            raise JWTError("OIDC signing key was not found.")
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer_url,
            options={
                "require_exp": True,
                "require_iat": True,
                "require_iss": True,
                "require_sub": True,
            },
        )
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not secrets.compare_digest(
            nonce, expected_nonce
        ):
            raise JWTError("OIDC nonce did not match.")
        return claims
    except (JWTError, StopIteration, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="OIDC ID token validation failed.") from exc
