"""Sitemap Checker – discovers, fetches and validates XML sitemaps."""

from typing import List, Optional
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Request

from core.config import settings
from core.exceptions import FetchException, ParseException
from models.schemas import SitemapResponse, SitemapURL, URLRequest
from utils.http import fetch_url, validate_url
from utils.response import ok

router = APIRouter()
TOOL = "sitemap_checker"

# XML namespace helpers
NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "si": "http://www.sitemaps.org/schemas/sitemap-image/1.1",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
    "video": "http://www.google.com/schemas/sitemap-video/1.1",
}


def _strip_ns(tag: str) -> str:
    """Return local tag name without namespace prefix."""
    return tag.split("}")[-1] if "}" in tag else tag


def parse_sitemap(
    content: str,
    url: str,
) -> tuple[bool, List[str], List[SitemapURL]]:
    """
    Returns (is_index, child_sitemaps, urls).
    Handles both sitemap index and URL sitemap files.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ParseException(TOOL, f"Invalid XML in sitemap at {url}: {exc}")

    local = _strip_ns(root.tag)
    is_index = local == "sitemapindex"
    child_sitemaps: List[str] = []
    urls: List[SitemapURL] = []

    if is_index:
        for sitemap_el in root:
            loc_el = sitemap_el.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc_el is None:
                # try without namespace
                for child in sitemap_el:
                    if _strip_ns(child.tag) == "loc":
                        loc_el = child
                        break
            if loc_el is not None and loc_el.text:
                child_sitemaps.append(loc_el.text.strip())
    else:
        for url_el in root:
            entry: dict = {}
            for child in url_el:
                local_child = _strip_ns(child.tag)
                if local_child == "loc":
                    entry["loc"] = (child.text or "").strip()
                elif local_child == "lastmod":
                    entry["lastmod"] = (child.text or "").strip()
                elif local_child == "changefreq":
                    entry["changefreq"] = (child.text or "").strip()
                elif local_child == "priority":
                    try:
                        entry["priority"] = float(child.text or "0")
                    except ValueError:
                        pass
            if entry.get("loc"):
                urls.append(SitemapURL(**entry))

    return is_index, child_sitemaps, urls


async def discover_sitemap_url(
    request: "Request",
    base_url: str,
    robots_text: Optional[str],
) -> Optional[str]:
    """Try common sitemap locations."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    # 1. From robots.txt
    if robots_text:
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                return line.split(":", 1)[1].strip()

    # 2. Common paths
    candidates = [
        f"{root}/sitemap.xml",
        f"{root}/sitemap_index.xml",
        f"{root}/sitemap-index.xml",
        f"{root}/sitemap/sitemap.xml",
    ]
    for candidate in candidates:
        try:
            resp = await fetch_url(request, TOOL, candidate, raise_for_status=True)
            if resp.status_code == 200:
                return candidate
        except FetchException:
            continue
    return None


@router.post(
    "/sitemap",
    summary="Discover and validate the sitemap (supports sitemap index)",
)
async def sitemap_checker(body: URLRequest, request: Request):
    url = validate_url(TOOL, body.url)

    # Try to get robots.txt for sitemap declaration
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    robots_text: Optional[str] = None
    try:
        r = await fetch_url(request, TOOL, robots_url, raise_for_status=True)
        robots_text = r.text
    except FetchException:
        pass

    sitemap_url = await discover_sitemap_url(request, url, robots_text)

    issues: List[str] = []
    recs: List[str] = []

    if not sitemap_url:
        issues.append(
            "No sitemap.xml found. Submit one to Google Search Console to improve crawlability."
        )
        recs.append("Create a sitemap at /sitemap.xml and declare it in your robots.txt.")
        result = SitemapResponse(
            url=url,
            sitemap_url="",
            found=False,
            is_sitemap_index=False,
            child_sitemaps=[],
            total_urls=0,
            sample_urls=[],
            issues=issues,
            recommendations=recs,
        )
        return ok(TOOL, result.model_dump())

    # Fetch the sitemap
    resp = await fetch_url(request, TOOL, sitemap_url, raise_for_status=False)
    content = resp.text

    if resp.status_code >= 400:
        issues.append(
            f"Sitemap URL returned HTTP {resp.status_code} — fix the URL or ensure the file exists."
        )

    is_index, child_sitemaps, urls = parse_sitemap(content, sitemap_url)

    # If it's an index, optionally fetch the first child to get URL count
    if is_index and child_sitemaps:
        try:
            child_resp = await fetch_url(
                request, TOOL, child_sitemaps[0], raise_for_status=False
            )
            _, _, child_urls = parse_sitemap(child_resp.text, child_sitemaps[0])
            urls = child_urls
        except Exception:
            pass

    total = len(urls)
    sample = urls[:20]

    # Insights
    if total == 0 and not is_index:
        issues.append("Sitemap found but contains no URLs.")
    elif total > 50_000:
        issues.append(
            "Sitemap exceeds 50,000 URLs — split into multiple sitemaps and use a sitemap index."
        )
    elif total > settings.MAX_SITEMAP_URLS:
        recs.append(
            f"Large sitemap ({total} URLs). Consider splitting for faster crawling."
        )

    # Check priority usage
    no_priority = sum(1 for u in urls if u.priority is None)
    if no_priority > 0 and total > 0:
        recs.append(
            "Some URLs are missing <priority> tags — set priorities to guide crawlers."
        )

    no_lastmod = sum(1 for u in urls if u.lastmod is None)
    if no_lastmod > total * 0.5 and total > 10:
        recs.append(
            "More than half of URLs are missing <lastmod> tags — add them to improve crawl efficiency."
        )

    if robots_text and "sitemap" not in robots_text.lower():
        recs.append("Declare your sitemap URL in robots.txt: Sitemap: " + sitemap_url)

    result = SitemapResponse(
        url=url,
        sitemap_url=sitemap_url,
        found=True,
        is_sitemap_index=is_index,
        child_sitemaps=child_sitemaps[:20],
        total_urls=total,
        sample_urls=[u.model_dump() for u in sample],
        issues=issues,
        recommendations=recs,
    )
    return ok(TOOL, result.model_dump())
