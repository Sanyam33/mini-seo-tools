"""Shared HTTP fetch utilities with unified error handling."""

import httpx
from fastapi import Request

from core.exceptions import FetchException, InvalidURLException, TimeoutException
from urllib.parse import urlparse


def validate_url(tool: str, url: str) -> str:
    """Ensure URL has a valid scheme and netloc; return normalised URL."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise InvalidURLException(tool, url)
        if not parsed.netloc:
            raise InvalidURLException(tool, url)
    except InvalidURLException:
        raise
    except Exception:
        raise InvalidURLException(tool, url)
    return url


async def fetch_url(
    request: Request,
    tool: str,
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    raise_for_status: bool = True,
) -> httpx.Response:
    """Fetch a URL using the shared async HTTP client with standardised errors."""
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.request(method, url, headers=headers or {})
        if raise_for_status and resp.status_code >= 400:
            raise FetchException(
                tool, url, f"HTTP {resp.status_code}: {resp.reason_phrase}"
            )
        return resp
    except httpx.TimeoutException:
        raise TimeoutException(tool, url)
    except (FetchException, TimeoutException):
        raise
    except httpx.TooManyRedirects:
        raise FetchException(tool, url, "Too many redirects.")
    except httpx.ConnectError as exc:
        raise FetchException(tool, url, f"Connection error: {exc}")
    except httpx.RequestError as exc:
        raise FetchException(tool, url, str(exc))


async def safe_head(
    request: Request,
    tool: str,
    url: str,
) -> tuple[int, str]:
    """HEAD request returning (status_code, reason). Never raises."""
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.head(url, follow_redirects=True)
        return resp.status_code, resp.reason_phrase
    except httpx.TimeoutException:
        return 0, "Timeout"
    except httpx.TooManyRedirects:
        return 0, "Too many redirects"
    except httpx.ConnectError:
        return 0, "Connection error"
    except httpx.RequestError as exc:
        return 0, str(exc)
