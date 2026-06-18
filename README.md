# SEO Tools API

Production-grade FastAPI mini-SEO utilities for link-building platforms. Designed for the **public homepage** — no auth required.

---

## Tools included

| # | Tool | Endpoint | Method |
|---|------|----------|--------|
| 1 | Word Counter | `/api/v1/seo/word-counter` | POST |
| 2 | Meta Analyzer | `/api/v1/seo/meta-analyzer` | POST |
| 3 | Broken Link Checker | `/api/v1/seo/broken-links` | POST |
| 4 | Robots.txt Checker | `/api/v1/seo/robots` | POST |
| 5 | Sitemap Checker | `/api/v1/seo/sitemap` | POST |
| 6 | Domain Authority | `/api/v1/seo/domain-authority` | POST |
| 7 | Page Speed Analyzer | `/api/v1/seo/page-speed` | POST |
| 8 | SSL Checker | `/api/v1/seo/ssl-checker` | POST |

---

## Project structure

```
seo_tools_api/
├── main.py                    # App entry point, middleware, routers
├── requirements.txt
├── .env.example
├── core/
│   ├── config.py              # Pydantic-settings config
│   └── exceptions.py          # Custom exception hierarchy
├── models/
│   └── schemas.py             # All Pydantic request/response models
├── routers/
│   ├── word_counter.py
│   ├── meta_analyzer.py
│   ├── broken_link_checker.py
│   ├── robots_checker.py
│   ├── sitemap_checker.py
│   ├── domain_authority.py
│   ├── page_speed.py
│   └── ssl_checker.py
└── utils/
    ├── http.py                # Shared fetch helpers with error handling
    └── response.py            # Uniform success envelope
```

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env as needed

# 3. Run
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: http://localhost:8000/docs  
ReDoc: http://localhost:8000/redoc

---

## API reference

### Uniform response envelope

Every successful response is wrapped in:

```json
{
  "success": true,
  "tool": "tool_name",
  "timestamp": "2025-01-01T00:00:00+00:00",
  "data": { ... }
}
```

Every error response:

```json
{
  "success": false,
  "tool": "tool_name",
  "error": "ERROR_CODE",
  "message": "Human-readable message",
  "detail": "Optional technical detail"
}
```

### Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `INVALID_URL` | 422 | Bad or missing scheme in URL |
| `FETCH_FAILED` | 502 | Could not retrieve target URL |
| `REQUEST_TIMEOUT` | 504 | Target server timed out |
| `PAYLOAD_TOO_LARGE` | 413 | Input exceeds configured limit |
| `PARSE_ERROR` | 422 | Response could not be parsed |
| `SSL_ERROR` | 502 | SSL handshake or cert error |
| `DNS_RESOLUTION_FAILED` | 502 | Hostname not found |
| `INTERNAL_SERVER_ERROR` | 500 | Unexpected server error |

---

### 1. Word Counter

**POST** `/api/v1/seo/word-counter`

Analyses plain text or HTML for word count, sentence count, reading time, keyword density and SEO insights.

```json
// Request
{
  "text": "Your content or raw HTML here...",
  "strip_html": true
}

// Response data
{
  "word_count": 342,
  "character_count": 2104,
  "character_count_no_spaces": 1762,
  "sentence_count": 18,
  "paragraph_count": 5,
  "average_word_length": 5.1,
  "reading_time_minutes": 1.7,
  "unique_words": 198,
  "top_keywords": [
    { "word": "backlinks", "count": 12, "density_percent": 3.5 }
  ],
  "keyword_density": { "backlinks": 3.5 },
  "seo_insights": ["Good content length (342 words)."]
}
```

**Limits:** Max 100,000 characters.

---

### 2. Meta Analyzer

**POST** `/api/v1/seo/meta-analyzer`

Fetches a URL and extracts all SEO metadata: title, meta description, canonical, OG/Twitter cards, JSON-LD schema, hreflang, headings, and computes an SEO score.

```json
// Request
{ "url": "https://example.com" }

// Response data (sample)
{
  "url": "https://example.com",
  "title": "Example Domain",
  "title_length": 14,
  "meta_description": null,
  "meta_description_length": null,
  "canonical_url": "https://example.com/",
  "og_tags": {},
  "twitter_tags": {},
  "schema_types": ["WebSite"],
  "h1_tags": ["Example Domain"],
  "seo_score": 65,
  "issues": ["Missing meta description"],
  "warnings": [],
  "recommendations": ["Add Open Graph meta tags"]
}
```

---

### 3. Broken Link Checker

**POST** `/api/v1/seo/broken-links`

Crawls a page, extracts all `<a href>` links (max 50), and concurrently HEAD-checks each one. Returns broken links, redirects and healthy links.

```json
// Request
{ "url": "https://example.com/blog" }

// Response data
{
  "url": "https://example.com/blog",
  "total_links": 23,
  "broken_links": 2,
  "redirects": 3,
  "ok_links": 18,
  "results": [
    {
      "url": "https://example.com/old-page",
      "status_code": 404,
      "status_text": "Not Found",
      "is_broken": true,
      "is_redirect": false,
      "anchor_text": "Read more",
      "link_type": "internal"
    }
  ],
  "issues": ["2 broken link(s) found"]
}
```

**Limits:** Max 50 links, 10 concurrent HEAD requests.

---

### 4. Robots.txt Checker

**POST** `/api/v1/seo/robots`

Fetches and parses `/robots.txt`, returns structured directives per user-agent. Optionally tests if a specific path is allowed.

```json
// Request
{
  "url": "https://example.com",
  "test_path": "/admin/",
  "user_agent": "Googlebot"
}

// Response data
{
  "robots_url": "https://example.com/robots.txt",
  "found": true,
  "directives": [
    {
      "user_agent": "*",
      "allow": ["/public/"],
      "disallow": ["/admin/", "/private/"],
      "crawl_delay": null
    }
  ],
  "sitemaps_declared": ["https://example.com/sitemap.xml"],
  "is_path_allowed": false,
  "test_path": "/admin/",
  "issues": ["Path '/admin/' is DISALLOWED for user-agent 'Googlebot'."],
  "recommendations": []
}
```

---

### 5. Sitemap Checker

**POST** `/api/v1/seo/sitemap`

Discovers the sitemap (via robots.txt or common paths), parses XML (including sitemap index files), and returns URL count, sample URLs and validation issues.

```json
// Request
{ "url": "https://example.com" }

// Response data
{
  "sitemap_url": "https://example.com/sitemap.xml",
  "found": true,
  "is_sitemap_index": false,
  "child_sitemaps": [],
  "total_urls": 142,
  "sample_urls": [
    {
      "loc": "https://example.com/blog/post-1",
      "lastmod": "2025-01-15",
      "changefreq": "monthly",
      "priority": 0.8
    }
  ],
  "issues": [],
  "recommendations": ["Add <lastmod> tags to improve crawl efficiency."]
}
```

---

### 6. Domain Authority (Heuristic)

**POST** `/api/v1/seo/domain-authority`

Returns a 0-100 heuristic authority score based on observable signals: HTTPS, response time, redirect chain, compression, content size. **Not affiliated with Moz DA or Ahrefs DR.**

```json
// Request
{ "url": "https://example.com" }

// Response data
{
  "domain": "example.com",
  "estimated_authority_score": 72,
  "https_enabled": true,
  "www_redirect": false,
  "response_time_ms": 231.4,
  "server_header": "ECS (nyb/1D13)",
  "signals": {
    "https": "✓ HTTPS enabled (+15)",
    "response_time": "✓ Fast response 231.4ms (+15)"
  },
  "note": "Heuristic estimate based on observable technical signals..."
}
```

---

### 7. Page Speed Analyzer

**POST** `/api/v1/seo/page-speed`

Measures server response time, page size, compression, caching and redirect chain. Returns a 0-100 score with actionable insights.

```json
// Request
{ "url": "https://example.com" }

// Response data
{
  "response_time_ms": 318.7,
  "ttfb_ms": 95.6,
  "page_size_bytes": 65432,
  "page_size_kb": 63.9,
  "compression_enabled": true,
  "cache_control": "max-age=3600",
  "http_version": "HTTP/2",
  "redirects_count": 1,
  "score": 82,
  "issues": [],
  "recommendations": ["Reduce redirect chain to improve TTFB."]
}
```

---

### 8. SSL Checker

**POST** `/api/v1/seo/ssl-checker`

Inspects the TLS certificate: validity, issuer, expiry date, SAN domains and protocol version. Warns if expiry is within 30 days.

```json
// Request
{ "url": "https://example.com" }

// Response data
{
  "domain": "example.com",
  "has_ssl": true,
  "ssl_valid": true,
  "issuer": "C=US, O=DigiCert Inc, CN=DigiCert TLS RSA SHA256 2020 CA1",
  "valid_from": "2024-01-01T00:00:00+00:00",
  "valid_until": "2026-01-01T00:00:00+00:00",
  "days_until_expiry": 196,
  "is_expiring_soon": false,
  "is_expired": false,
  "san_domains": ["example.com", "www.example.com"],
  "protocol_version": "TLSv1.3",
  "issues": [],
  "recommendations": ["Certificate is valid for 196 more day(s)."]
}
```

---

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Expose error detail in 500 responses |
| `USER_AGENT` | `SEOToolsBot/1.0` | Bot user-agent sent to target sites |
| `HTTP_CONNECT_TIMEOUT` | `10.0` | Connection timeout in seconds |
| `HTTP_READ_TIMEOUT` | `20.0` | Read timeout in seconds |
| `MAX_TEXT_CHARS` | `100000` | Max chars for word counter |
| `MAX_LINKS_TO_CHECK` | `50` | Max links for broken link checker |
| `MAX_SITEMAP_URLS` | `500` | Max URLs reported from sitemap |
| `BROKEN_LINK_CONCURRENCY` | `10` | Concurrent HEAD requests |
| `ALLOWED_ORIGINS` | `["*"]` | CORS allowed origins |

---

## Production deployment

```bash
# Gunicorn + Uvicorn workers
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Or with Docker
docker build -t seo-tools-api .
docker run -p 8000:8000 --env-file .env seo-tools-api
```

**Recommended extras for production:**
- Put behind Nginx/Caddy for TLS termination
- Add Redis-based rate limiting (e.g. `slowapi`)
- Monitor with Sentry or similar
- Lock `ALLOWED_ORIGINS` to your frontend domain
