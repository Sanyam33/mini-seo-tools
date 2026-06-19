"""
SEO Tools API - Production Grade
Mini SEO utilities for link-building platforms.
Public-facing, no auth required.
"""

from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import time
from core.config import settings
from core.exceptions import SEOToolException
from routers import (
    word_counter,
    meta_analyzer,
    broken_link_checker,
    robots_checker,
    sitemap_checker,
    domain_authority,
    page_speed,
    ssl_checker,
    domain_rating,
    domain_age_checker
)


# ---------------------------------------------------------------------------
# Lifespan: shared async HTTP client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.HTTP_CONNECT_TIMEOUT,
            read=settings.HTTP_READ_TIMEOUT,
            write=10.0,
            pool=5.0,
        ),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        headers={"User-Agent": settings.USER_AGENT},
    )
    yield
    await app.state.http_client.aclose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SEO Tools API",
    description=(
        "Production-grade mini SEO utilities for link-building platforms. "
        "No authentication required — designed for public homepage use."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)

# Simple request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    return response


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(SEOToolException)
async def seo_tool_exception_handler(request: Request, exc: SEOToolException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "tool": exc.tool,
            "error": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "tool": "unknown",
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred. Please try again.",
            "detail": str(exc) if settings.DEBUG else None,
        },
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

PREFIX = "/api/v1/seo"

app.include_router(word_counter.router,       prefix=PREFIX, tags=["Word Counter"])
app.include_router(meta_analyzer.router,      prefix=PREFIX, tags=["Meta Analyzer"])
app.include_router(broken_link_checker.router, prefix=PREFIX, tags=["Broken Link Checker"])
app.include_router(robots_checker.router,     prefix=PREFIX, tags=["Robots.txt Checker"])
app.include_router(sitemap_checker.router,    prefix=PREFIX, tags=["Sitemap Checker"])
app.include_router(domain_authority.router,   prefix=PREFIX, tags=["Domain Authority"])
app.include_router(page_speed.router,         prefix=PREFIX, tags=["Page Speed"])
app.include_router(ssl_checker.router,        prefix=PREFIX, tags=["SSL Checker"])
app.include_router(domain_rating.router,        prefix=PREFIX, tags=["DR Checker"])
app.include_router(domain_age_checker.router, prefix=PREFIX, tags=["Domain Age Checker"])

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"], summary="Health check")
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "SEO Tools API",
        "docs": "/docs",
        "tools": [
            "/api/v1/seo/word-counter",
            "/api/v1/seo/meta-analyzer",
            "/api/v1/seo/broken-links",
            "/api/v1/seo/robots",
            "/api/v1/seo/sitemap",
            "/api/v1/seo/domain-authority",
            "/api/v1/seo/page-speed",
            "/api/v1/seo/ssl-checker",
            "/api/v1/seo/dr-checker",
            "/api/v1/seo/domain-age",
        ],
    }
