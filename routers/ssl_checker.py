"""SSL Certificate Checker – inspects TLS certificate validity, expiry and issuer."""

import ssl
import socket
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Request

from core.exceptions import SEOToolException
from models.schemas import SSLResponse, URLRequest
from utils.http import validate_url
from utils.response import ok

router = APIRouter()
TOOL = "ssl_checker"

EXPIRY_WARNING_DAYS = 30


def _get_cert_info(hostname: str, port: int = 443) -> dict:
    """Synchronous SSL cert fetch (run in thread pool)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED

    try:
        conn = ctx.wrap_socket(
            socket.create_connection((hostname, port), timeout=10),
            server_hostname=hostname,
        )
    except ssl.SSLCertVerificationError as exc:
        # Cert is present but invalid — still return info
        ctx2 = ssl.create_default_context()
        ctx2.check_hostname = False
        ctx2.verify_mode = ssl.CERT_NONE
        conn = ctx2.wrap_socket(
            socket.create_connection((hostname, port), timeout=10),
            server_hostname=hostname,
        )
        cert = conn.getpeercert()
        conn.close()
        return {"cert": cert, "valid": False, "error": str(exc), "version": conn.version() if conn else None}

    cert = conn.getpeercert()
    version = conn.version()
    conn.close()
    return {"cert": cert, "valid": True, "error": None, "version": version}


def _parse_cert(
    info: dict,
    domain: str,
) -> SSLResponse:
    cert = info.get("cert") or {}
    ssl_valid = info.get("valid", False)

    # Issuer
    issuer_parts = cert.get("issuer", ())
    issuer = ", ".join(
        f"{k}={v}" for pair in issuer_parts for k, v in pair
    ) if issuer_parts else None

    # Subject
    subject_parts = cert.get("subject", ())
    subject = ", ".join(
        f"{k}={v}" for pair in subject_parts for k, v in pair
    ) if subject_parts else None

    # Validity dates
    not_before_str = cert.get("notBefore")
    not_after_str = cert.get("notAfter")

    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    days_until_expiry: Optional[int] = None
    is_expired = False
    is_expiring_soon = False

    fmt = "%b %d %H:%M:%S %Y %Z"
    now = datetime.now(timezone.utc)

    if not_before_str:
        try:
            valid_from = datetime.strptime(not_before_str, fmt).isoformat()
        except ValueError:
            valid_from = not_before_str

    if not_after_str:
        try:
            expiry_dt = datetime.strptime(not_after_str, fmt).replace(tzinfo=timezone.utc)
            valid_until = expiry_dt.isoformat()
            delta = expiry_dt - now
            days_until_expiry = delta.days
            is_expired = delta.days < 0
            is_expiring_soon = 0 <= delta.days <= EXPIRY_WARNING_DAYS
        except ValueError:
            valid_until = not_after_str

    # SAN domains
    san_list: List[str] = []
    for key, values in cert.get("subjectAltName", ()):
        if key == "DNS":
            san_list.append(values)

    # Issues & recs
    issues: List[str] = []
    recs: List[str] = []

    if not ssl_valid:
        issues.append(
            f"SSL certificate is INVALID: {info.get('error', 'verification failed')}. "
            "Browsers will show a security warning."
        )
    if is_expired:
        issues.append(
            f"SSL certificate EXPIRED {abs(days_until_expiry or 0)} day(s) ago. Renew immediately."
        )
    elif is_expiring_soon:
        issues.append(
            f"SSL certificate expires in {days_until_expiry} day(s). Renew it soon."
        )
    if ssl_valid and not is_expired and not is_expiring_soon:
        recs.append(f"Certificate is valid for {days_until_expiry} more day(s).")

    if not san_list:
        recs.append("No SAN domains found — consider a wildcard certificate.")

    return SSLResponse(
        url=f"https://{domain}",
        domain=domain,
        has_ssl=True,
        ssl_valid=ssl_valid,
        issuer=issuer,
        subject=subject,
        valid_from=valid_from,
        valid_until=valid_until,
        days_until_expiry=days_until_expiry,
        is_expiring_soon=is_expiring_soon,
        is_expired=is_expired,
        san_domains=san_list,
        protocol_version=info.get("version"),
        issues=issues,
        recommendations=recs,
    )


@router.post(
    "/ssl-checker",
    summary="Inspect SSL/TLS certificate validity, issuer, expiry and SANs",
)
async def ssl_checker(body: URLRequest, request: Request):
    url = validate_url(TOOL, body.url)
    parsed = urlparse(url)
    domain = parsed.hostname or parsed.netloc
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    if parsed.scheme != "https":
        result = SSLResponse(
            url=url,
            domain=domain,
            has_ssl=False,
            ssl_valid=False,
            issuer=None,
            subject=None,
            valid_from=None,
            valid_until=None,
            days_until_expiry=None,
            is_expiring_soon=False,
            is_expired=False,
            san_domains=[],
            protocol_version=None,
            issues=["URL uses HTTP — no SSL certificate to check. Switch to HTTPS immediately."],
            recommendations=["Obtain a free SSL certificate via Let's Encrypt (https://letsencrypt.org)."],
        )
        return ok(TOOL, result.model_dump())

    try:
        info = await asyncio.get_event_loop().run_in_executor(
            None, _get_cert_info, domain, port
        )
    except ConnectionRefusedError:
        raise SEOToolException(
            tool=TOOL,
            error_code="CONNECTION_REFUSED",
            message=f"Could not connect to {domain}:{port}. The server may be down or not serving HTTPS.",
            status_code=502,
        )
    except socket.timeout:
        raise SEOToolException(
            tool=TOOL,
            error_code="SSL_TIMEOUT",
            message=f"Connection to {domain}:{port} timed out.",
            status_code=504,
        )
    except socket.gaierror as exc:
        raise SEOToolException(
            tool=TOOL,
            error_code="DNS_RESOLUTION_FAILED",
            message=f"Cannot resolve hostname '{domain}'.",
            detail=str(exc),
            status_code=502,
        )
    except Exception as exc:
        raise SEOToolException(
            tool=TOOL,
            error_code="SSL_ERROR",
            message=f"Failed to retrieve SSL certificate for '{domain}'.",
            detail=str(exc),
            status_code=502,
        )

    result = _parse_cert(info, domain)
    return ok(TOOL, result.model_dump())
