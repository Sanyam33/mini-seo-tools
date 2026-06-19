"""
Ahrefs Domain Rating Checker
─────────────────────────────
Uses the free, no-auth Ahrefs public endpoint to retrieve the official
Domain Rating (DR) for any domain.

Attribution required by Ahrefs terms of use:
  "Domain Rating by Ahrefs" — https://ahrefs.com/
  License: http://ahrefs.com/legal/domain-rating-license
"""

from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from core.exceptions import SEOToolException, FetchException, TimeoutException
from utils.http import validate_url
from utils.response import ok

router = APIRouter()
TOOL = "dr_checker"

AHREFS_DR_URL = "https://api.ahrefs.com/v3/public/domain-rating-free"
AHREFS_TIMEOUT = 15.0   # Ahrefs can be slightly slow; give it headroom


# ── Request / Response models ────────────────────────────────────────────────

class DRRequest(BaseModel):
    url: str = Field(
        ...,
        description="Target domain or URL. Scheme is optional — 'example.com' works too.",
        examples=["https://example.com", "example.com"],
    )

    @field_validator("url")
    @classmethod
    def normalise(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v


class DRResponse(BaseModel):
    domain: str
    domain_rating: Optional[float]          # 0-100, None if Ahrefs has no data
    ahrefs_rank: Optional[int]              # global rank in Ahrefs index
    dr_label: str                           # "Low / Medium / High / Very High / Authority"
    backlinks_hint: str                     # contextual copy for the UI
    data_available: bool
    attribution: str
    attribution_url: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc
    # Strip www. for cleaner display; Ahrefs accepts both
    return host.lstrip("www.") if host else url


def _dr_label(dr: Optional[float]) -> tuple[str, str]:
    """Return (label, hint copy) based on DR score."""
    if dr is None:
        return "No data", "Ahrefs has no DR data for this domain yet."
    if dr < 10:
        return "Very Low", "Brand-new or very small domain. Focus on building quality backlinks."
    if dr < 30:
        return "Low", "Early-stage domain. Consistent link-building will grow this score."
    if dr < 50:
        return "Medium", "Decent authority. Continue building diverse, high-quality backlinks."
    if dr < 70:
        return "High", "Strong backlink profile. This domain carries good authority."
    if dr < 85:
        return "Very High", "Excellent domain authority. A strong link-building foundation."
    return "Authority", "Top-tier domain authority. Highly trusted by search engines."


# ── Ahrefs API call ──────────────────────────────────────────────────────────

async def _fetch_dr(client: httpx.AsyncClient, domain: str) -> dict:
    """Call the Ahrefs free DR endpoint and return raw JSON."""
    try:
        resp = await client.get(
            AHREFS_DR_URL,
            params={"target": domain},
            headers={"Accept": "application/json"},
            timeout=AHREFS_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise TimeoutException(TOOL, AHREFS_DR_URL)
    except httpx.ConnectError as exc:
        raise FetchException(TOOL, AHREFS_DR_URL, f"Could not reach Ahrefs API: {exc}")
    except httpx.RequestError as exc:
        raise FetchException(TOOL, AHREFS_DR_URL, str(exc))

    if resp.status_code == 429:
        raise SEOToolException(
            tool=TOOL,
            error_code="RATE_LIMITED",
            message="Ahrefs API rate limit reached. Please wait a moment and try again.",
            status_code=429,
        )
    if resp.status_code == 422:
        raise SEOToolException(
            tool=TOOL,
            error_code="INVALID_TARGET",
            message="Ahrefs rejected the target domain. Ensure it is a valid registered domain.",
            detail=resp.text[:300],
            status_code=422,
        )
    if resp.status_code >= 500:
        raise SEOToolException(
            tool=TOOL,
            error_code="AHREFS_UPSTREAM_ERROR",
            message="Ahrefs API returned a server error. Try again shortly.",
            detail=f"HTTP {resp.status_code}",
            status_code=502,
        )
    if resp.status_code >= 400:
        raise SEOToolException(
            tool=TOOL,
            error_code="AHREFS_REQUEST_ERROR",
            message=f"Ahrefs API returned HTTP {resp.status_code}.",
            detail=resp.text[:300],
            status_code=502,
        )

    try:
        return resp.json()
    except Exception as exc:
        raise SEOToolException(
            tool=TOOL,
            error_code="PARSE_ERROR",
            message="Could not parse the response from Ahrefs API.",
            detail=str(exc),
            status_code=502,
        )


# ── Router ───────────────────────────────────────────────────────────────────

@router.post(
    "/dr-checker",
    summary="Get the official Ahrefs Domain Rating (DR) for any domain",
    description=(
        "Returns the real Ahrefs DR score (0-100) via the free public Ahrefs endpoint. "
        "No API key required. **Attribution:** Domain Rating by [Ahrefs](https://ahrefs.com/). "
        "Usage subject to the [Domain Rating License](http://ahrefs.com/legal/domain-rating-license)."
    ),
    response_description="DR score, rank, label and contextual insights",
)
async def dr_checker(body: DRRequest, request: Request):
    validate_url(TOOL, body.url)
    domain = _extract_domain(body.url)

    if not domain:
        raise SEOToolException(
            tool=TOOL,
            error_code="INVALID_DOMAIN",
            message="Could not extract a valid domain from the provided URL.",
            status_code=422,
        )

    client: httpx.AsyncClient = request.app.state.http_client
    raw = await _fetch_dr(client, domain)

    # ── Parse Ahrefs response ──
    # The free endpoint returns: { "domain": "...", "domain_rating": 42, "ahrefs_rank": 12345 }
    # If the domain has no data, domain_rating may be 0 or absent.
    
    dr_object = raw.get("domain_rating", {})
    if isinstance(dr_object, dict):
        dr_raw = dr_object.get("domain_rating")
    else:
        dr_raw = dr_object 
        
    ahrefs_rank = raw.get("ahrefs_rank") or raw.get("ahrefs_top")

    dr_value: Optional[float] = None
    data_available = False

    if dr_raw is not None:
        try:
            dr_value = float(dr_raw)
            data_available = True
        except (TypeError, ValueError):
            pass

    label, hint = _dr_label(dr_value)

    result = DRResponse(
        domain=domain,
        domain_rating=dr_value,
        ahrefs_rank=int(ahrefs_rank) if ahrefs_rank else None,
        dr_label=label,
        backlinks_hint=hint,
        data_available=data_available,
        attribution="Domain Rating by Ahrefs",
        attribution_url="https://ahrefs.com/",
    )

    return ok(
        TOOL,
        result.model_dump(),
        meta={
            "source": "Ahrefs Free DR API",
            "license": "http://ahrefs.com/legal/domain-rating-license",
        },
    )