from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    # replicaSet + directConnection: Docker Compose single-node RS; host connects via published 27017
    MONGO_URI: str = "mongodb://127.0.0.1:27017/invize?replicaSet=rs0&directConnection=true"
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14
    JWT_ISSUER: str = "invize-backend"
    JWT_AUDIENCE: str = "invize-client"
    REFRESH_TOKEN_TRANSPORT: str = "cookie"  # or "header"
    # Must match how the browser calls auth: Next.js rewrites /api/auth/* → backend /auth/*
    # so Path should be /api/auth (default). Use /auth if clients hit the API origin only.
    REFRESH_COOKIE_PATH: str = "/api/auth"

    # Pydantic v2 settings configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",  # ignore unrelated env keys
    )