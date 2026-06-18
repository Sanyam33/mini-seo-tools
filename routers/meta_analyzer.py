"""Meta Analyzer – extracts and scores all SEO-relevant meta information from a URL."""

import json
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from fastapi import APIRouter, Request
from bs4 import BeautifulSoup

from core.exceptions import ParseException
from models.schemas import MetaAnalyzerResponse, MetaTag, URLRequest
from utils.http import fetch_url, validate_url
from utils.response import ok

router = APIRouter()
TOOL = "meta_analyzer"


# ── Scoring helpers ──────────────────────────────────────────────────────────

def _score_and_issues(
    title: Optional[str],
    desc: Optional[str],
    canonical: Optional[str],
    h1_tags: List[str],
    og_tags: Dict,
    viewport: Optional[str],
    robots: Optional[str],
) -> tuple[int, List[str], List[str], List[str]]:
    score = 100
    issues: List[str] = []
    warnings: List[str] = []
    recs: List[str] = []

    # Title
    if not title:
        issues.append("Missing <title> tag — critical for SEO.")
        score -= 20
    elif len(title) < 30:
        warnings.append(f"Title is short ({len(title)} chars). Recommended: 50-60 chars.")
        score -= 5
    elif len(title) > 60:
        warnings.append(f"Title is long ({len(title)} chars). Google may truncate after 60.")
        score -= 5

    # Meta description
    if not desc:
        issues.append("Missing meta description — reduces CTR from search results.")
        score -= 15
    elif len(desc) < 70:
        warnings.append(f"Meta description is short ({len(desc)} chars). Aim for 120-160.")
        score -= 5
    elif len(desc) > 160:
        warnings.append(f"Meta description too long ({len(desc)} chars) — will be truncated.")
        score -= 5

    # H1
    if not h1_tags:
        issues.append("No <h1> tag found — every page should have exactly one H1.")
        score -= 10
    elif len(h1_tags) > 1:
        warnings.append(f"Multiple <h1> tags ({len(h1_tags)}) — use exactly one per page.")
        score -= 5

    # Canonical
    if not canonical:
        warnings.append("No canonical URL — consider adding one to prevent duplicate content issues.")
        score -= 5
    recs.append("Add a canonical tag if not already present.")

    # OG tags
    if not og_tags:
        warnings.append("No Open Graph tags — add og:title, og:description, og:image for social sharing.")
        score -= 5
        recs.append("Add Open Graph meta tags for better social media previews.")

    # Viewport
    if not viewport:
        issues.append("Missing viewport meta tag — page may not render well on mobile.")
        score -= 10

    # Robots
    if robots and ("noindex" in robots.lower()):
        warnings.append("Page is set to noindex — it will NOT be indexed by search engines.")

    return max(score, 0), issues, warnings, recs


# ── Router ───────────────────────────────────────────────────────────────────

@router.post(
    "/meta-analyzer",
    summary="Analyse all meta tags, OG, Twitter cards, schema & SEO score",
)
async def meta_analyzer(body: URLRequest, request: Request):
    url = validate_url(TOOL, body.url)
    resp = await fetch_url(request, TOOL, url, raise_for_status=False)

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        raise ParseException(TOOL, str(exc))

    # ── Title ──
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    # ── All meta tags ──
    raw_metas: List[MetaTag] = []
    og_tags: Dict[str, str] = {}
    tw_tags: Dict[str, str] = {}
    meta_desc: Optional[str] = None
    canonical_url: Optional[str] = None
    robots_content: Optional[str] = None
    viewport_content: Optional[str] = None
    charset_content: Optional[str] = None

    for tag in soup.find_all("meta"):
        attrs = tag.attrs
        name = attrs.get("name", "").lower()
        prop = attrs.get("property", "").lower()
        content = attrs.get("content", "")
        http_equiv = attrs.get("http-equiv", "")
        charset = attrs.get("charset", "")

        raw_metas.append(
            MetaTag(
                name=attrs.get("name"),
                property=attrs.get("property"),
                content=content or None,
                http_equiv=http_equiv or None,
            )
        )

        if name == "description":
            meta_desc = content
        elif name == "robots":
            robots_content = content
        elif name == "viewport":
            viewport_content = content
        elif prop.startswith("og:"):
            og_tags[prop[3:]] = content
        elif name.startswith("twitter:"):
            tw_tags[name[8:]] = content
        elif name.startswith("twitter:"):
            tw_tags[name] = content
        if charset:
            charset_content = charset

    # ── Canonical ──
    link_canonical = soup.find("link", rel="canonical")
    if link_canonical:
        canonical_url = link_canonical.get("href")

    # ── Hreflang ──
    hreflang_tags = [
        {"hreflang": tag.get("hreflang", ""), "href": tag.get("href", "")}
        for tag in soup.find_all("link", hreflang=True)
    ]

    # ── Headings ──
    h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1")][:5]
    h2_tags = [h.get_text(strip=True) for h in soup.find_all("h2")][:10]

    # ── JSON-LD schema types ──
    schema_types: List[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                t = data.get("@type")
                if t:
                    schema_types.append(t if isinstance(t, str) else str(t))
            elif isinstance(data, list):
                for item in data:
                    t = item.get("@type") if isinstance(item, dict) else None
                    if t:
                        schema_types.append(t)
        except Exception:
            pass

    # ── Score & insights ──
    score, issues, warnings, recs = _score_and_issues(
        title, meta_desc, canonical_url, h1_tags, og_tags, viewport_content, robots_content
    )

    result = MetaAnalyzerResponse(
        url=str(resp.url),
        title=title,
        title_length=len(title) if title else None,
        meta_description=meta_desc,
        meta_description_length=len(meta_desc) if meta_desc else None,
        canonical_url=canonical_url,
        robots=robots_content,
        viewport=viewport_content,
        charset=charset_content,
        og_tags=og_tags,
        twitter_tags=tw_tags,
        schema_types=schema_types,
        hreflang_tags=hreflang_tags,
        h1_tags=h1_tags,
        h2_tags=h2_tags,
        all_meta_tags=raw_metas,
        seo_score=score,
        issues=issues,
        warnings=warnings,
        recommendations=recs,
    )

    return ok(TOOL, result.model_dump())
