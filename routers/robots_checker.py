"""Robots.txt Checker – fetches, parses and validates robots.txt files."""

import re
from typing import List, Optional
from urllib.parse import urlparse, urljoin

from fastapi import APIRouter, Request

from core.exceptions import FetchException
from models.schemas import RobotsDirective, RobotsRequest, RobotsResponse
from utils.http import fetch_url, validate_url
from utils.response import ok

router = APIRouter()
TOOL = "robots_checker"


def parse_robots(content: str) -> tuple[List[RobotsDirective], List[str]]:
    """Parse robots.txt into structured directives."""
    directives: List[RobotsDirective] = []
    sitemaps: List[str] = []

    current_agents: List[str] = []
    allow: List[str] = []
    disallow: List[str] = []
    crawl_delay: Optional[float] = None

    def flush():
        if current_agents:
            for agent in current_agents:
                directives.append(
                    RobotsDirective(
                        user_agent=agent,
                        allow=allow[:],
                        disallow=disallow[:],
                        crawl_delay=crawl_delay,
                    )
                )

    for raw_line in content.splitlines():
        line = raw_line.split("#")[0].strip()  # strip comments
        if not line:
            if current_agents and (allow or disallow):
                flush()
                current_agents = []
                allow = []
                disallow = []
                crawl_delay = None
            continue

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if current_agents and (allow or disallow or crawl_delay is not None):
                flush()
                current_agents = []
                allow = []
                disallow = []
                crawl_delay = None
            current_agents.append(value)
        elif key == "allow":
            allow.append(value)
        elif key == "disallow":
            disallow.append(value)
        elif key == "crawl-delay":
            try:
                crawl_delay = float(value)
            except ValueError:
                pass
        elif key == "sitemap":
            sitemaps.append(value)

    flush()
    return directives, sitemaps


def is_path_allowed(
    directives: List[RobotsDirective],
    path: str,
    user_agent: str,
) -> bool:
    """Check if a path is allowed for a given user agent (simplified matcher)."""
    def matches(pattern: str, p: str) -> bool:
        if not pattern:
            return False
        regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\$", "$")
        return bool(re.match(regex, p))

    # Gather applicable rules (specific agent > wildcard)
    rules: List[tuple[str, bool]] = []  # (pattern, is_allow)

    for directive in directives:
        agent = directive.user_agent.lower()
        if agent == user_agent.lower() or agent == "*":
            priority = 1 if agent == "*" else 2
            for p in directive.allow:
                rules.append((p, True, priority))       # type: ignore[misc]
            for p in directive.disallow:
                rules.append((p, False, priority))      # type: ignore[misc]

    # Sort by specificity (longer pattern wins) then priority
    rules.sort(key=lambda r: (len(r[0]), r[2]), reverse=True)  # type: ignore[misc]

    for pattern, allowed, _ in rules:  # type: ignore[misc]
        if matches(pattern, path):
            return allowed

    return True  # Default: allowed


def build_issues(
    found: bool,
    directives: List[RobotsDirective],
    sitemaps: List[str],
) -> tuple[List[str], List[str]]:
    issues: List[str] = []
    recs: List[str] = []

    if not found:
        issues.append("No robots.txt found — search engines will crawl all pages by default.")
        recs.append("Create a robots.txt file at the root of your domain.")
        return issues, recs

    all_disallowed = {d for dir_ in directives for d in dir_.disallow}
    if "/" in all_disallowed:
        issues.append(
            "Disallow: / detected — your entire site may be blocked from indexing!"
        )

    wildcard = [d for d in directives if d.user_agent == "*"]
    if not wildcard:
        recs.append("Add a wildcard (*) user-agent block to cover all crawlers.")

    if not sitemaps:
        recs.append("Declare your sitemap URL in robots.txt: Sitemap: https://yourdomain.com/sitemap.xml")

    for d in directives:
        if d.crawl_delay and d.crawl_delay > 10:
            issues.append(
                f"Crawl-Delay of {d.crawl_delay}s for '{d.user_agent}' is very high — "
                "this may significantly slow indexing."
            )

    return issues, recs


@router.post(
    "/robots",
    summary="Fetch and parse robots.txt, test path allow/disallow rules",
)
async def robots_checker(body: RobotsRequest, request: Request):
    url = validate_url(TOOL, body.url)
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    found = True
    raw_content: Optional[str] = None
    directives: List[RobotsDirective] = []
    sitemaps: List[str] = []

    try:
        resp = await fetch_url(request, TOOL, robots_url, raise_for_status=True)
        raw_content = resp.text[:50_000]   # cap at 50KB
        directives, sitemaps = parse_robots(raw_content)
    except FetchException:
        found = False

    issues, recs = build_issues(found, directives, sitemaps)

    # Test path
    path_allowed: Optional[bool] = None
    if body.test_path and found:
        path_allowed = is_path_allowed(directives, body.test_path, body.user_agent)
        if not path_allowed:
            issues.append(
                f"Path '{body.test_path}' is DISALLOWED for user-agent '{body.user_agent}'."
            )

    result = RobotsResponse(
        url=url,
        robots_url=robots_url,
        found=found,
        raw_content=raw_content,
        directives=[d.model_dump() for d in directives],
        sitemaps_declared=sitemaps,
        is_path_allowed=path_allowed,
        test_path=body.test_path,
        issues=issues,
        recommendations=recs,
    )

    return ok(TOOL, result.model_dump())
