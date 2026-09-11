from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    TG_API_ID: int = 0
    TG_API_HASH: str = ""
    SESSIONS_DIR: str = "./sessions"
    DB_URL: str = "sqlite+aiosqlite:///./app.db"
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT_SECONDS: float = 30.0
    DB_POOL_RECYCLE_SECONDS: int = 1800
    ENFORCE_SINGLE_INSTANCE: bool = True
    RATE_MIN: float = 0.7
    RATE_MAX: float = 1.5
    CONCURRENCY: int = 8
    STARTUP_CONCURRENCY: int = 10
    STATUS_CONCURRENCY: int = 10
    RECONNECT_BACKOFF_BASE_SECONDS: float = 30.0
    RECONNECT_BACKOFF_MAX_SECONDS: float = 900.0
    RECONNECT_BACKOFF_JITTER_RATIO: float = 0.2
    TG_RPC_TIMEOUT_SECONDS: float = 45.0
    API_REQUEST_TIMEOUT_SECONDS: float = 60.0
    AUTO_RECONNECT: bool = True
    NOTIFICATION_SOUND: bool = True
    ALLOWED_ORIGIN: str = ""

    APP_PASSWORD: str = ""
    SECRETS_ENCRYPTION_KEY: str = ""
    SESSION_DAYS: int = 14
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_WINDOW_MIN: int = 15
    PENDING_LOGIN_TTL_SECONDS: int = 600
    QR_PENDING_TTL_SECONDS: int = 600
    COOKIE_SECURE: bool = False
    TRUST_PROXY_HEADERS: bool = False
    CSRF_TRUSTED_ORIGINS: str = ""

    @property
    def database_url(self) -> str:
        raw = (self.DATABASE_URL or self.DB_URL).strip()
        if raw.startswith("postgres://"):
            return "postgresql+asyncpg://" + raw[len("postgres://"):]
        if raw.startswith("postgresql://"):
            return "postgresql+asyncpg://" + raw[len("postgresql://"):]
        return raw

    @property
    def sessions_path(self) -> Path:
        p = Path(self.SESSIONS_DIR)
        p.mkdir(parents=True, exist_ok=True)
        try:
            p.chmod(0o700)
        except OSError:
            pass
        return p


settings = Settings()
