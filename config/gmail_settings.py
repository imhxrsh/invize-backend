"""Gmail OAuth and scan settings."""

from pydantic import AliasChoices, Field
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
    """Max messages to fetch/classify per scan invocation (keeps Groq TPM under free-tier bursts)."""
    GMAIL_SCAN_MAX_MESSAGES: int = 5
    """Sub-batches within one scan; each chunk is followed by GMAIL_SCAN_BATCH_SLEEP_MS (if more remain)."""
    GMAIL_SCAN_BATCH_SIZE: int = 5
    """Pause between batches (ms), e.g. 120000 = 2 minutes."""
    GMAIL_SCAN_BATCH_SLEEP_MS: int = 120_000
    """Gmail search `after:YYYY/MM/DD` — only messages on or after this date (inbox)."""
    GMAIL_SCAN_AFTER_DATE: str = "2026/04/30"
    """Gmail label = this message was already ingested by our backend (fetched + classified + DB row). Not Gmail read/unread."""
    GMAIL_INGEST_LABEL_NAME: str = Field(
        default="Invize/Ingested",
        validation_alias=AliasChoices(
            "GMAIL_INGEST_LABEL_NAME",
            "GMAIL_PROCESSED_LABEL_NAME",
        ),
    )
    """If true, skip API+LLM when a GmailScanResult already exists (backend already ingested); still applies ingest label if missing."""
    GMAIL_SKIP_IF_ALREADY_INGESTED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "GMAIL_SKIP_IF_ALREADY_INGESTED",
            "GMAIL_SKIP_IF_ALREADY_IN_DB",
        ),
    )
    """Comma-separated categories that trigger document pipeline (invoice attachment → OCR path)."""
    GMAIL_PIPELINE_CATEGORIES: str = "invoice,receipt"
    GMAIL_PIPELINE_MAX_ATTACHMENT_MB: int = 50
    """Pause between messages (ms) after classify/pipeline to spread Groq TPM; 0 disables."""
    GMAIL_SCAN_LLM_DELAY_MS: int = 1500
    """0 = disabled. Otherwise seconds between automatic scans for all connected Gmail users (e.g. 43200 = 12h)."""
    GMAIL_AUTO_SCAN_INTERVAL_SECONDS: int = 0
    """Seconds to wait after app startup before the first automatic scan (stagger from boot)."""
    GMAIL_AUTO_SCAN_STARTUP_DELAY_SECONDS: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    def pipeline_category_set(self) -> set[str]:
        return {x.strip().lower() for x in self.GMAIL_PIPELINE_CATEGORIES.split(",") if x.strip()}
