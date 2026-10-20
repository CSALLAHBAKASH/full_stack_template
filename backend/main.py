from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy import select

from auth import oidc_router, router
from chatbot import router as chatbot_router
from database import SessionLocal, engine
from models import User
from schemas import normalize_email
from security import hash_password, redis_client
from settings import settings


def _bootstrap_admin() -> None:
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if bool(email) != bool(password):
        raise RuntimeError(
            "Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, or neither."
        )
    if not email:
        return
    try:
        email = normalize_email(email)
    except ValueError as exc:
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL must be a valid email address.") from exc
    if not 12 <= len(password.encode("utf-8")) <= 72:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be 12-72 UTF-8 bytes.")
    with SessionLocal.begin() as db:
        if engine.dialect.name == "postgresql":
            db.execute(
                postgres_insert(User)
                .values(
                    id=uuid4(),
                    email=email,
                    full_name="Administrator",
                    password_hash=hash_password(password),
                    role="admin",
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(index_elements=[User.email])
            )
        else:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                db.add(
                    User(
                        email=email,
                        full_name="Administrator",
                        password_hash=hash_password(password),
                        role="admin",
                    )
                )
                db.flush()
        user = db.scalar(select(User).where(User.email == email))
        if user is None or user.role != "admin" or not user.is_active:
            raise RuntimeError(
                "The bootstrap admin email exists but is not an active administrator."
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(settings.session_secret.encode("utf-8")) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 bytes.")
    if bool(settings.oidc_issuer_url) != bool(
        settings.oidc_client_id and settings.oidc_client_secret
    ):
        raise RuntimeError(
            "Configure OIDC_ISSUER_URL, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET together."
        )
    redis_client.ping()
    _bootstrap_admin()
    yield
    redis_client.close()
    engine.dispose()


app = FastAPI(title="Full Stack Template API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(router)
app.include_router(oidc_router, prefix="/auth/oidc", tags=["OIDC"])
app.include_router(chatbot_router, tags=["Chat"])


@app.middleware("http")
async def protect_cookie_mutations(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and origin
        and origin.rstrip("/") not in settings.cors_origins
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "Untrusted request origin."},
        )
    return await call_next(request)


@app.get("/")
def home() -> dict[str, str]:
    return {"home": "simple app for template"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness_check():
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        redis_client.ping()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "detail": "Database or Redis unavailable.",
            },
        )
    return {"status": "ready"}
