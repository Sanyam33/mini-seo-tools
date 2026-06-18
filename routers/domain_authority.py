"""
Domain Authority Estimator – derives a heuristic trust/authority score from
publicly observable signals (HTTPS, redirects, headers, response time, etc.).

NOTE: This is NOT Moz DA or Ahrefs DR. It is an independent heuristic score
suitable for quick UX display without requiring third-party API keys.
"""

import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request

from core.exceptions import FetchException, TimeoutException
from models.schemas import DomainAuthorityResponse, URLRequest
from utils.http import validate_url
from utils.response import ok

router = APIRouter()
TOOL = "domain_authority"


async def _fetch_with_timing(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[httpx.Response, float]:
    start = time.perf_counter()
    resp = await client.get(url, follow_redirects=True)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    return resp, elapsed_ms


def compute_score(
    https_enabled: bool,
    response_time_ms: float,
    www_redirect: bool,
    has_server_header: bool,
    content_length: Optional[int],
    redirect_count: int,
) -> tuple[int, dict]:
    score = 50  # baseline
    signals: dict = {}

    # HTTPS
    if https_enabled:
        score += 15
        signals["https"] = "✓ HTTPS enabled (+15)"
    else:
        score -= 20
        signals["https"] = "✗ No HTTPS (-20)"

    # Response time
    if response_time_ms < 500:
        score += 15
        signals["response_time"] = f"✓ Fast response {response_time_ms}ms (+15)"
    elif response_time_ms < 1500:
        score += 7
        signals["response_time"] = f"~ Moderate response {response_time_ms}ms (+7)"
    else:
        score -= 5
        signals["response_time"] = f"✗ Slow response {response_time_ms}ms (-5)"

    # WWW redirect (indicates proper canonical setup)
    if www_redirect:
        score += 5
        signals["www_redirect"] = "✓ www/non-www redirect configured (+5)"

    # Server header present (minor signal)
    if has_server_header:
        score += 2
        signals["server_header"] = "✓ Server header present (+2)"

    # Content delivered
    if content_length and content_length > 5000:
        score += 5
        signals["content_size"] = f"✓ Substantial content ({content_length:,} bytes) (+5)"
    elif content_length and content_length < 500:
        score -= 5
        signals["content_size"] = f"✗ Very small page ({content_length} bytes) (-5)"

    # Redirect chain
    if redirect_count == 0:
        score += 3
        signals["redirects"] = "✓ No redirect chain (+3)"
    elif redirect_count >= 3:
        score -= 5
        signals["redirects"] = f"✗ Long redirect chain ({redirect_count} hops) (-5)"

    return max(0, min(100, score)), signals


@router.post(
    "/domain-authority",
    summary="Heuristic domain authority score based on observable signals",
)
async def domain_authority(body: URLRequest, request: Request):
    url = validate_url(TOOL, body.url)
    client: httpx.AsyncClient = request.app.state.http_client
    parsed = urlparse(url)
    domain = parsed.netloc

    # Detect HTTPS
    https_enabled = url.startswith("https://")

    # Fetch with timing
    try:
        resp, elapsed_ms = await _fetch_with_timing(client, url)
    except httpx.TimeoutException:
        raise TimeoutException(TOOL, url)
    except httpx.RequestError as exc:
        raise FetchException(TOOL, url, str(exc))

    # WWW redirect detection
    initial_url = url
    final_url = str(resp.url)
    www_redirect = (
        ("www." in initial_url) != ("www." in final_url)
        or initial_url.rstrip("/") != final_url.rstrip("/")
    )

    # Redirect count via history
    redirect_count = len(resp.history)

    # Headers
    server_header = resp.headers.get("server")
    x_powered_by = resp.headers.get("x-powered-by")
    content_length: Optional[int] = None
    cl = resp.headers.get("content-length")
    if cl:
        try:
            content_length = int(cl)
        except ValueError:
            pass
    if content_length is None:
        content_length = len(resp.content)

    score, signals = compute_score(
        https_enabled=https_enabled,
        response_time_ms=elapsed_ms,
        www_redirect=www_redirect,
        has_server_header=bool(server_header),
        content_length=content_length,
        redirect_count=redirect_count,
    )

    result = DomainAuthorityResponse(
        url=url,
        domain=domain,
        estimated_authority_score=score,
        domain_age_hint=None,   # would require WHOIS — not in scope
        https_enabled=https_enabled,
        www_redirect=www_redirect,
        response_time_ms=elapsed_ms,
        server_header=server_header,
        x_powered_by=x_powered_by,
        content_length_bytes=content_length,
        signals=signals,
        note=(
            "This score is a heuristic estimate based on observable technical signals. "
            "It is not affiliated with Moz DA, Ahrefs DR, or any third-party metric."
        ),
    )

    return ok(TOOL, result.model_dump())
