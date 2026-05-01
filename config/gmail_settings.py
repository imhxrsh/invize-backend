"""Gmail OAuth and scan settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class GmailSettings(BaseSettings):
    GMAIL_OAUTH_CLIENT_ID: str = ""
    GMAIL_OAUTH_CLIENT_SECRET: str = ""
    """Registered redirect URI (must match Google Cloud console exactly)."""
    GMAIL_OAUTH_REDIRECT_URI: str = "http://127.0.0.1:8000/gmail/oauth/callback"
    """Browser URL after successful connect (e.g. Next.js settings with query hint)."""
    GMAIL_OAUTH_FRONTEND_SUCCESS_URL: str = "http://localhost:3000/dashboard/settings?tab=integrations&gmail=connected"
    """Optional Fernet key (urlsafe base64). If empty, derived from JWT_SECRET."""
    GMAIL_TOKEN_FERNET_KEY: str = ""
    GMAIL_SCAN_MAX_MESSAGES: int = 25
    """Comma-separated categories that trigger document pipeline (invoice attachment → OCR path)."""
    GMAIL_PIPELINE_CATEGORIES: str = "invoice,receipt"
    GMAIL_PIPELINE_MAX_ATTACHMENT_MB: int = 50
    """Pause between messages (ms) after classify/pipeline to spread Groq TPM; 0 disables."""
    GMAIL_SCAN_LLM_DELAY_MS: int = 1500

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    def pipeline_category_set(self) -> set[str]:
        return {x.strip().lower() for x in self.GMAIL_PIPELINE_CATEGORIES.split(",") if x.strip()}
