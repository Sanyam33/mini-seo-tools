"""
WHOIS Domain Age Checker
─────────────────────────
Uses the APILayer WHOIS API to retrieve registration data and computes
human-readable domain age, expiry countdown and trust signals.

Provider: https://apilayer.com/marketplace/whois-api
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from core.config import settings
from core.exceptions import SEOToolException, FetchException, TimeoutException
from utils.response import ok

router = APIRouter()
TOOL = "domain_age_checker"

WHOIS_API_URL = "https://api.apilayer.com/whois/query"
WHOIS_TIMEOUT = 20.0   # WHOIS lookups can be slow for some TLDs


# ── Config ────────────────────────────────────────────────────────────────────

class _WhoisSettings:
    """Read API key from environment so it is never hard-coded in source."""
    api_key: str = settings.WHOIS_API_KEY   # set in .env → WHOIS_API_KEY


# Add to core/config.py:  WHOIS_API_KEY: str = ""
# Then set in .env:        WHOIS_API_KEY=Q5iql9A3y3A9iCACpIpAaHcwROcJnh3O


# ── Request / Response models ─────────────────────────────────────────────────

class DomainAgeRequest(BaseModel):
    url: str = Field(
        ...,
        description="Domain or full URL to look up. Scheme is optional.",
        examples=["dadsmedia.com", "https://ahrefs.com"],
    )

    @field_validator("url")
    @classmethod
    def normalise(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v


class AgeBreakdown(BaseModel):
    total_days: int
    years: int
    months: int
    days: int
    human: str          # "6 years and 172 days"


class DomainAgeResponse(BaseModel):
    domain: str
    domain_name_raw: Optional[str]

    # Registration dates
    creation_date: Optional[str]        # ISO-8601 UTC
    creation_date_human: Optional[str]  # "December 31, 2019 06:26 UTC"
    expiration_date: Optional[str]
    expiration_date_human: Optional[str]
    updated_date: Optional[str]
    updated_date_human: Optional[str]

    # Age & expiry
    age: Optional[AgeBreakdown]
    days_until_expiry: Optional[int]
    is_expired: bool
    expires_soon: bool                  # within 60 days

    # Registrar details
    registrar: Optional[str]
    whois_server: Optional[str]
    name_servers: list[str]
    dnssec: Optional[str]
    status: list[str]
    emails: Optional[str]

    # Insights
    age_trust_label: str                # "New / Young / Established / Authoritative / Veteran"
    age_trust_hint: str
    issues: list[str]
    recommendations: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc
    # Strip www. — WHOIS works on the root domain
    return host.lower().lstrip("www.") if host else url.lower()


def _parse_whois_date(raw: str | list | None) -> Optional[datetime]:
    """
    APILayer can return a string or a list of date strings.
    Parse the first valid one and normalise to UTC.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not raw:
        return None

    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%b-%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(str(raw).strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _human_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime("%B %d, %Y %H:%M UTC")


def _compute_age(creation: datetime, now: datetime) -> AgeBreakdown:
    delta = now - creation
    total_days = delta.days

    years = total_days // 365
    remaining = total_days % 365
    months = remaining // 30
    days = remaining % 30

    parts: list[str] = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    if days or not parts:
        parts.append(f"{days} day{'s' if days != 1 else ''}")

    human = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]

    return AgeBreakdown(
        total_days=total_days,
        years=years,
        months=months,
        days=days,
        human=human,
    )


def _age_trust(age: Optional[AgeBreakdown]) -> tuple[str, str]:
    if age is None:
        return "Unknown", "Domain age could not be determined from WHOIS data."
    d = age.total_days
    if d < 90:
        return "New", "Brand-new domain (< 3 months). Search engines treat new domains cautiously."
    if d < 365:
        return "Young", "Less than a year old. Building trust takes time — focus on quality content and links."
    if d < 3 * 365:
        return "Established", "1-3 years old. Growing authority. Consistent SEO efforts will accelerate results."
    if d < 7 * 365:
        return "Authoritative", "3-7 years old. Well-established domain with good trust signals."
    return "Veteran", f"Over 7 years old ({age.years} years). Highly trusted by search engines."


def _build_insights(
    age: Optional[AgeBreakdown],
    days_until_expiry: Optional[int],
    is_expired: bool,
    dnssec: Optional[str],
    name_servers: list[str],
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    recs: list[str] = []

    if is_expired:
        issues.append("Domain has EXPIRED. It may be dropped or transferred soon.")
    elif days_until_expiry is not None and days_until_expiry <= 60:
        issues.append(
            f"Domain expires in {days_until_expiry} day(s). Renew immediately to avoid losing it."
        )
    elif days_until_expiry is not None and days_until_expiry <= 180:
        recs.append(f"Domain expires in {days_until_expiry} days — consider renewing early.")

    if age and age.total_days < 90:
        issues.append("Very new domain — Google's 'sandbox effect' may limit rankings for 3-6 months.")

    if dnssec and dnssec.lower() == "unsigned":
        recs.append("DNSSEC is unsigned. Enable DNSSEC via your registrar for added DNS security.")

    parking_ns = {"dns-parking", "parkingcrew", "sedoparking", "above.com", "bodis.com"}
    ns_lower = " ".join(name_servers).lower()
    if any(p in ns_lower for p in parking_ns):
        issues.append(
            "Domain appears to be parked (parking name servers detected). "
            "It is not serving real content."
        )

    if not name_servers:
        issues.append("No name servers found — domain may not be configured or is pending setup.")

    return issues, recs


# ── WHOIS API call ────────────────────────────────────────────────────────────

async def _fetch_whois(client: httpx.AsyncClient, domain: str, api_key: str) -> dict:
    try:
        resp = await client.get(
            WHOIS_API_URL,
            params={"domain": domain},
            headers={"apikey": api_key, "Accept": "application/json"},
            timeout=WHOIS_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise TimeoutException(TOOL, WHOIS_API_URL)
    except httpx.ConnectError as exc:
        raise FetchException(TOOL, WHOIS_API_URL, f"Could not reach WHOIS API: {exc}")
    except httpx.RequestError as exc:
        raise FetchException(TOOL, WHOIS_API_URL, str(exc))

    if resp.status_code == 401:
        raise SEOToolException(
            tool=TOOL,
            error_code="INVALID_API_KEY",
            message="WHOIS API key is missing or invalid. Check your WHOIS_API_KEY in .env.",
            status_code=401,
        )
    if resp.status_code == 429:
        raise SEOToolException(
            tool=TOOL,
            error_code="RATE_LIMITED",
            message="WHOIS API rate limit reached. Please wait and try again.",
            status_code=429,
        )
    if resp.status_code == 404:
        raise SEOToolException(
            tool=TOOL,
            error_code="DOMAIN_NOT_FOUND",
            message=f"No WHOIS record found for this domain. It may not be registered.",
            status_code=404,
        )
    if resp.status_code >= 500:
        raise SEOToolException(
            tool=TOOL,
            error_code="WHOIS_UPSTREAM_ERROR",
            message="WHOIS API returned a server error. Try again shortly.",
            detail=f"HTTP {resp.status_code}",
            status_code=502,
        )
    if resp.status_code >= 400:
        raise SEOToolException(
            tool=TOOL,
            error_code="WHOIS_REQUEST_ERROR",
            message=f"WHOIS API returned HTTP {resp.status_code}.",
            detail=resp.text[:300],
            status_code=502,
        )

    try:
        return resp.json()
    except Exception as exc:
        raise SEOToolException(
            tool=TOOL,
            error_code="PARSE_ERROR",
            message="Could not parse the WHOIS API response.",
            detail=str(exc),
            status_code=502,
        )


# ── Router ────────────────────────────────────────────────────────────────────

@router.post(
    "/domain-age",
    summary="WHOIS-based domain age, expiry, registrar and trust signals",
    description=(
        "Looks up WHOIS registration data via APILayer and returns domain age, "
        "creation/expiry dates, registrar info, name servers and actionable SEO insights."
    ),
)
async def domain_age_checker(body: DomainAgeRequest, request: Request):
    api_key: str = settings.WHOIS_API_KEY
    if not api_key:
        raise SEOToolException(
            tool=TOOL,
            error_code="CONFIGURATION_ERROR",
            message="WHOIS_API_KEY is not configured. Add it to your .env file.",
            status_code=500,
        )

    domain = _extract_domain(body.url)
    if not domain or "." not in domain:
        raise SEOToolException(
            tool=TOOL,
            error_code="INVALID_DOMAIN",
            message=f"'{domain}' does not look like a valid domain name.",
            status_code=422,
        )

    client: httpx.AsyncClient = request.app.state.http_client
    raw = await _fetch_whois(client, domain, api_key)

    # APILayer wraps data under "result"
    data: dict = raw.get("result") or raw

    if not data:
        raise SEOToolException(
            tool=TOOL,
            error_code="NO_WHOIS_DATA",
            message=f"WHOIS returned an empty response for '{domain}'.",
            status_code=404,
        )

    # ── Parse dates ──
    now = datetime.now(timezone.utc)

    creation_dt = _parse_whois_date(data.get("creation_date"))
    expiration_dt = _parse_whois_date(data.get("expiration_date"))
    updated_dt = _parse_whois_date(data.get("updated_date"))

    # ── Age ──
    age: Optional[AgeBreakdown] = None
    if creation_dt:
        age = _compute_age(creation_dt, now)

    # ── Expiry ──
    days_until_expiry: Optional[int] = None
    is_expired = False
    expires_soon = False
    if expiration_dt:
        delta = expiration_dt - now
        days_until_expiry = delta.days
        is_expired = delta.days < 0
        expires_soon = 0 <= delta.days <= 60

    # ── Name servers ──
    raw_ns = data.get("name_servers") or []
    if isinstance(raw_ns, str):
        raw_ns = [raw_ns]
    name_servers = [ns.strip() for ns in raw_ns if ns]

    # ── Status ──
    raw_status = data.get("status") or []
    if isinstance(raw_status, str):
        raw_status = [raw_status]
    status_list = [s.strip() for s in raw_status if s]

    # ── Trust label ──
    trust_label, trust_hint = _age_trust(age)

    # ── Issues ──
    issues, recs = _build_insights(age, days_until_expiry, is_expired, data.get("dnssec"), name_servers)

    result = DomainAgeResponse(
        domain=domain,
        domain_name_raw=data.get("domain_name"),
        creation_date=creation_dt.isoformat() if creation_dt else None,
        creation_date_human=_human_date(creation_dt),
        expiration_date=expiration_dt.isoformat() if expiration_dt else None,
        expiration_date_human=_human_date(expiration_dt),
        updated_date=updated_dt.isoformat() if updated_dt else None,
        updated_date_human=_human_date(updated_dt),
        age=age,
        days_until_expiry=days_until_expiry,
        is_expired=is_expired,
        expires_soon=expires_soon,
        registrar=data.get("registrar"),
        whois_server=data.get("whois_server"),
        name_servers=name_servers,
        dnssec=data.get("dnssec"),
        status=status_list,
        emails=data.get("emails"),
        age_trust_label=trust_label,
        age_trust_hint=trust_hint,
        issues=issues,
        recommendations=recs,
    )

    return ok(TOOL, result.model_dump())