"""Broken Link Checker – crawls a page and checks every link concurrently."""

import asyncio
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Request
from bs4 import BeautifulSoup

from core.config import settings
from core.exceptions import ParseException, PayloadTooLargeException
from models.schemas import BrokenLinkResponse, LinkResult, URLRequest
from utils.http import fetch_url, safe_head, validate_url
from utils.response import ok

router = APIRouter()
TOOL = "broken_link_checker"


def classify_link(href: str, base_domain: str) -> str:
    parsed = urlparse(href)
    link_domain = parsed.netloc.lower().lstrip("www.")
    base = base_domain.lower().lstrip("www.")
    return "internal" if (not parsed.netloc or link_domain == base) else "external"


async def check_link(
    request: Request,
    url: str,
    anchor: Optional[str],
    link_type: str,
    sem: asyncio.Semaphore,
) -> LinkResult:
    async with sem:
        status, reason = await safe_head(request, TOOL, url)

    is_broken = status == 0 or status >= 400
    is_redirect = status in (301, 302, 303, 307, 308)

    return LinkResult(
        url=url,
        status_code=status,
        status_text=reason,
        is_broken=is_broken,
        is_redirect=is_redirect,
        anchor_text=anchor[:120] if anchor else None,
        link_type=link_type,
    )


@router.post(
    "/broken-links",
    summary="Crawl a page and check all links for broken/redirect status",
)
async def broken_link_checker(body: URLRequest, request: Request):
    url = validate_url(TOOL, body.url)
    resp = await fetch_url(request, TOOL, url, raise_for_status=False)

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        raise ParseException(TOOL, str(exc))

    base_url = str(resp.url)
    base_domain = urlparse(base_url).netloc

    # Collect all <a href> links
    raw_links: List[tuple[str, Optional[str]]] = []
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        anchor = a_tag.get_text(strip=True) or None

        # Skip non-http links
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue

        # Resolve relative URLs
        resolved = urljoin(base_url, href)

        # Normalise (strip fragment)
        parsed = urlparse(resolved)
        normalised = parsed._replace(fragment="").geturl()

        if normalised not in seen:
            seen.add(normalised)
            raw_links.append((normalised, anchor))

    # Enforce limit
    if len(raw_links) > settings.MAX_LINKS_TO_CHECK:
        raw_links = raw_links[: settings.MAX_LINKS_TO_CHECK]

    # Concurrent HEAD checks
    sem = asyncio.Semaphore(settings.BROKEN_LINK_CONCURRENCY)
    tasks = [
        check_link(
            request,
            link_url,
            anchor,
            classify_link(link_url, base_domain),
            sem,
        )
        for link_url, anchor in raw_links
    ]
    results: List[LinkResult] = await asyncio.gather(*tasks)

    broken = [r for r in results if r.is_broken]
    redirects = [r for r in results if r.is_redirect]
    ok_links = [r for r in results if not r.is_broken and not r.is_redirect]

    issues: List[str] = []
    if broken:
        issues.append(
            f"{len(broken)} broken link(s) found — fix or remove them to avoid negative SEO impact."
        )
    if redirects:
        issues.append(
            f"{len(redirects)} redirect(s) detected — use permanent 301 redirects and update links to final URLs."
        )
    if len(raw_links) >= settings.MAX_LINKS_TO_CHECK:
        issues.append(
            f"Only the first {settings.MAX_LINKS_TO_CHECK} links were checked due to the request limit."
        )

    response = BrokenLinkResponse(
        url=base_url,
        total_links=len(results),
        broken_links=len(broken),
        redirects=len(redirects),
        ok_links=len(ok_links),
        results=[r.model_dump() for r in results],
        issues=issues,
    )

    return ok(TOOL, response.model_dump())
