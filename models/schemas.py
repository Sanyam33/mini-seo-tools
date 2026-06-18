"""Request & response Pydantic models for every SEO tool."""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, field_validator
import re


# ── Shared ──────────────────────────────────────────────────────────────────

class URLRequest(BaseModel):
    url: str = Field(..., description="Target URL including scheme (https://example.com)")

    @field_validator("url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https?://", v, re.IGNORECASE):
            v = "https://" + v
        return v


# ── Word Counter ─────────────────────────────────────────────────────────────

class WordCounterRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Plain text or HTML to analyse")
    strip_html: bool = Field(True, description="Strip HTML tags before counting")


class WordCounterResponse(BaseModel):
    word_count: int
    character_count: int
    character_count_no_spaces: int
    sentence_count: int
    paragraph_count: int
    average_word_length: float
    reading_time_minutes: float
    unique_words: int
    top_keywords: List[Dict[str, Any]]       # [{word, count, density%}]
    keyword_density: Dict[str, float]        # word → density %
    seo_insights: List[str]


# ── Meta Analyzer ────────────────────────────────────────────────────────────

class MetaTag(BaseModel):
    name: Optional[str] = None
    property: Optional[str] = None
    content: Optional[str] = None
    http_equiv: Optional[str] = None


class MetaAnalyzerResponse(BaseModel):
    url: str
    title: Optional[str]
    title_length: Optional[int]
    meta_description: Optional[str]
    meta_description_length: Optional[int]
    canonical_url: Optional[str]
    robots: Optional[str]
    viewport: Optional[str]
    charset: Optional[str]
    og_tags: Dict[str, str]
    twitter_tags: Dict[str, str]
    schema_types: List[str]
    hreflang_tags: List[Dict[str, str]]
    h1_tags: List[str]
    h2_tags: List[str]
    all_meta_tags: List[MetaTag]
    seo_score: int                           # 0-100
    issues: List[str]
    warnings: List[str]
    recommendations: List[str]


# ── Broken Link Checker ──────────────────────────────────────────────────────

class LinkResult(BaseModel):
    url: str
    status_code: int
    status_text: str
    is_broken: bool
    is_redirect: bool
    anchor_text: Optional[str]
    link_type: str                           # internal / external


class BrokenLinkResponse(BaseModel):
    url: str
    total_links: int
    broken_links: int
    redirects: int
    ok_links: int
    results: List[LinkResult]
    issues: List[str]


# ── Robots.txt ───────────────────────────────────────────────────────────────

class RobotsDirective(BaseModel):
    user_agent: str
    allow: List[str]
    disallow: List[str]
    crawl_delay: Optional[float]


class RobotsResponse(BaseModel):
    url: str
    robots_url: str
    found: bool
    raw_content: Optional[str]
    directives: List[RobotsDirective]
    sitemaps_declared: List[str]
    is_path_allowed: Optional[bool]          # populated when test_path given
    test_path: Optional[str]
    issues: List[str]
    recommendations: List[str]


class RobotsRequest(URLRequest):
    test_path: Optional[str] = Field(
        None, description="Optional path to test against robots rules (e.g. /blog/)"
    )
    user_agent: str = Field("*", description="User-agent to test against")


# ── Sitemap Checker ──────────────────────────────────────────────────────────

class SitemapURL(BaseModel):
    loc: str
    lastmod: Optional[str]
    changefreq: Optional[str]
    priority: Optional[float]


class SitemapResponse(BaseModel):
    url: str
    sitemap_url: str
    found: bool
    is_sitemap_index: bool
    child_sitemaps: List[str]
    total_urls: int
    sample_urls: List[SitemapURL]            # first 20
    issues: List[str]
    recommendations: List[str]


# ── Domain Authority (heuristic) ─────────────────────────────────────────────

class DomainAuthorityResponse(BaseModel):
    url: str
    domain: str
    estimated_authority_score: int           # 0-100 heuristic
    domain_age_hint: Optional[str]
    https_enabled: bool
    www_redirect: bool
    response_time_ms: float
    server_header: Optional[str]
    x_powered_by: Optional[str]
    content_length_bytes: Optional[int]
    signals: Dict[str, Any]
    note: str


# ── Page Speed ────────────────────────────────────────────────────────────────

class PageSpeedResponse(BaseModel):
    url: str
    response_time_ms: float
    ttfb_ms: float                           # time to first byte (approx)
    page_size_bytes: int
    page_size_kb: float
    transfer_encoding: Optional[str]
    content_type: Optional[str]
    cache_control: Optional[str]
    etag: Optional[str]
    compression_enabled: bool
    http_version: str
    redirects_count: int
    score: int                               # 0-100 simple heuristic
    issues: List[str]
    recommendations: List[str]


# ── SSL Checker ───────────────────────────────────────────────────────────────

class SSLResponse(BaseModel):
    url: str
    domain: str
    has_ssl: bool
    ssl_valid: bool
    issuer: Optional[str]
    subject: Optional[str]
    valid_from: Optional[str]
    valid_until: Optional[str]
    days_until_expiry: Optional[int]
    is_expiring_soon: bool                   # < 30 days
    is_expired: bool
    san_domains: List[str]
    protocol_version: Optional[str]
    issues: List[str]
    recommendations: List[str]
