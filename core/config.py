"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    DEBUG: bool = False
    USER_AGENT: str = (
        "SEOToolsBot/1.0 (+https://yourdomain.com/bot)"
    )

    # HTTP client timeouts (seconds)
    HTTP_CONNECT_TIMEOUT: float = 10.0
    HTTP_READ_TIMEOUT: float = 20.0

    # Rate / size limits
    MAX_TEXT_CHARS: int = 100_000          # word counter
    MAX_LINKS_TO_CHECK: int = 50           # broken link checker
    MAX_SITEMAP_URLS: int = 500            # sitemap checker
    BROKEN_LINK_CONCURRENCY: int = 10      # concurrent link checks

    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]     # lock down in production

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
