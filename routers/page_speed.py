"""Page Speed Analyzer – measures server response time, page size and caching headers."""

import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request

from core.exceptions import FetchException, TimeoutException
from models.schemas import PageSpeedResponse, URLRequest
from utils.http import validate_url
from utils.response import ok

router = APIRouter()
TOOL = "page_speed"


def score_page_speed(
    response_ms: float,
    page_size_bytes: int,
    compression_enabled: bool,
    cache_control: Optional[str],
    redirect_count: int,
) -> tuple[int, list, list]:
    score = 100
    issues = []
    recs = []

    # Response time
    if response_ms > 3000:
        score -= 30
        issues.append(
            f"Very slow server response ({response_ms:.0f}ms). Target < 200ms TTFB."
        )
    elif response_ms > 1000:
        score -= 15
        issues.append(
            f"Slow server response ({response_ms:.0f}ms). Target < 200ms TTFB."
        )
    elif response_ms > 500:
        score -= 5
        recs.append("Response time is acceptable but could be improved with caching or a CDN.")

    # Page size
    if page_size_bytes > 5_000_000:  # 5MB
        score -= 25
        issues.append(
            f"Page is very large ({page_size_bytes / 1024:.0f}KB). Optimise images and remove unused JS/CSS."
        )
    elif page_size_bytes > 1_000_000:  # 1MB
        score -= 10
        issues.append(
            f"Page is large ({page_size_bytes / 1024:.0f}KB). Consider compressing assets."
        )
    elif page_size_bytes > 500_000:  # 500KB
        score -= 5
        recs.append("Page size is moderate. Aim for under 500KB for faster load times.")

    # Compression
    if not compression_enabled:
        score -= 15
        issues.append(
            "GZIP/Brotli compression is not enabled. Enable it to reduce transfer size by 60-80%."
        )
    else:
        recs.append("Compression is enabled — good for performance.")

    # Caching
    if not cache_control:
        score -= 10
        issues.append(
            "No Cache-Control header found. Add caching headers to reduce repeat visit load times."
        )
    elif "no-cache" in (cache_control or "").lower() or "no-store" in (cache_control or "").lower():
        score -= 5
        recs.append(
            "Cache-Control is set to no-cache/no-store for this resource — fine for HTML but ensure static assets are cached."
        )

    # Redirects
    if redirect_count >= 3:
        score -= 10
        issues.append(
            f"Redirect chain of {redirect_count} hops detected. Minimise redirects to reduce latency."
        )
    elif redirect_count > 0:
        score -= 3
        recs.append("Reduce redirect chain to improve TTFB.")

    return max(0, score), issues, recs


@router.post(
    "/page-speed",
    summary="Measure server response time, page size, compression and caching",
)
async def page_speed(body: URLRequest, request: Request):
    url = validate_url(TOOL, body.url)
    client: httpx.AsyncClient = request.app.state.http_client

    try:
        start = time.perf_counter()
        resp = await client.get(url, follow_redirects=True)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    except httpx.TimeoutException:
        raise TimeoutException(TOOL, url)
    except httpx.RequestError as exc:
        raise FetchException(TOOL, url, str(exc))

    headers = resp.headers
    content = resp.content
    page_size_bytes = len(content)

    encoding = headers.get("content-encoding", "")
    compression_enabled = any(enc in encoding.lower() for enc in ("gzip", "br", "deflate", "zstd"))

    cache_control = headers.get("cache-control")
    content_type = headers.get("content-type")
    etag = headers.get("etag")
    transfer_encoding = headers.get("transfer-encoding")
    redirect_count = len(resp.history)

    # HTTP version
    http_version = f"HTTP/{resp.http_version}" if hasattr(resp, "http_version") else "HTTP/1.1"

    # Rough TTFB approximation from elapsed (we can't split at transport level without hooks)
    ttfb_ms = round(elapsed_ms * 0.3, 2)  # heuristic: ~30% of total is server processing

    score, issues, recs = score_page_speed(
        response_ms=elapsed_ms,
        page_size_bytes=page_size_bytes,
        compression_enabled=compression_enabled,
        cache_control=cache_control,
        redirect_count=redirect_count,
    )

    result = PageSpeedResponse(
        url=str(resp.url),
        response_time_ms=elapsed_ms,
        ttfb_ms=ttfb_ms,
        page_size_bytes=page_size_bytes,
        page_size_kb=round(page_size_bytes / 1024, 2),
        transfer_encoding=transfer_encoding,
        content_type=content_type,
        cache_control=cache_control,
        etag=etag,
        compression_enabled=compression_enabled,
        http_version=http_version,
        redirects_count=redirect_count,
        score=score,
        issues=issues,
        recommendations=recs,
    )

    return ok(TOOL, result.model_dump())
