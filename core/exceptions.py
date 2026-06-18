"""Custom exceptions for the SEO Tools API."""

from typing import Optional


class SEOToolException(Exception):
    """Base exception raised by all SEO tools."""

    def __init__(
        self,
        tool: str,
        error_code: str,
        message: str,
        detail: Optional[str] = None,
        status_code: int = 400,
    ):
        self.tool = tool
        self.error_code = error_code
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)


# ── Convenience subclasses ──────────────────────────────────────────────────

class InvalidURLException(SEOToolException):
    def __init__(self, tool: str, url: str):
        super().__init__(
            tool=tool,
            error_code="INVALID_URL",
            message=f"The URL '{url}' is not valid. Provide a full URL including the scheme (https://).",
            status_code=422,
        )


class FetchException(SEOToolException):
    def __init__(self, tool: str, url: str, reason: str):
        super().__init__(
            tool=tool,
            error_code="FETCH_FAILED",
            message=f"Could not fetch the URL '{url}'.",
            detail=reason,
            status_code=502,
        )


class TimeoutException(SEOToolException):
    def __init__(self, tool: str, url: str):
        super().__init__(
            tool=tool,
            error_code="REQUEST_TIMEOUT",
            message=f"The request to '{url}' timed out. The server may be slow or unreachable.",
            status_code=504,
        )


class PayloadTooLargeException(SEOToolException):
    def __init__(self, tool: str, limit_label: str):
        super().__init__(
            tool=tool,
            error_code="PAYLOAD_TOO_LARGE",
            message=f"Input exceeds the allowed limit: {limit_label}.",
            status_code=413,
        )


class ParseException(SEOToolException):
    def __init__(self, tool: str, detail: str):
        super().__init__(
            tool=tool,
            error_code="PARSE_ERROR",
            message="Could not parse the response from the target URL.",
            detail=detail,
            status_code=422,
        )
