import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


class Settings:
    app_env = os.getenv("APP_ENV", "development").lower()
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://app:devpassword@localhost:5432/app",
    )
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    session_secret = os.getenv("SESSION_SECRET", "")
    session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "300"))
    session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "app_session")
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    cors_origins = [
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", frontend_url).split(",")
        if origin.strip()
    ]
    cookie_secure = _get_bool("COOKIE_SECURE", app_env == "production")
    password_auth_enabled = _get_bool("PASSWORD_AUTH_ENABLED", True)
    bootstrap_admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    bootstrap_admin_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    oidc_issuer_url = os.getenv("OIDC_ISSUER_URL", "").rstrip("/")
    oidc_client_id = os.getenv("OIDC_CLIENT_ID", "")
    oidc_client_secret = os.getenv("OIDC_CLIENT_SECRET", "")
    oidc_redirect_uri = os.getenv(
        "OIDC_REDIRECT_URI", "http://localhost:8000/auth/oidc/callback"
    )
    groq_api_key = os.getenv("GROQ_API_KEY", "")

    @property
    def oidc_enabled(self) -> bool:
        return bool(
            self.oidc_issuer_url
            and self.oidc_client_id
            and self.oidc_client_secret
            and self.oidc_redirect_uri
        )


settings = Settings()
