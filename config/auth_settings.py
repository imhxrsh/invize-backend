from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    MONGO_URI: str = "mongodb://localhost:27017/invize"
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14
    JWT_ISSUER: str = "invize-backend"
    JWT_AUDIENCE: str = "invize-client"
    REFRESH_TOKEN_TRANSPORT: str = "cookie"  # or "header"
    
    # Pydantic v2 settings configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",  # ignore unrelated env keys
    )