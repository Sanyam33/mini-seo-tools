"""Word Counter – analyses plain text or HTML for SEO content metrics."""

import re
import html as html_lib
from collections import Counter
from typing import List, Dict, Any

from fastapi import APIRouter
from bs4 import BeautifulSoup

from core.config import settings
from core.exceptions import PayloadTooLargeException
from models.schemas import WordCounterRequest, WordCounterResponse
from utils.response import ok

router = APIRouter()

TOOL = "word_counter"

# Common English stop words to exclude from keyword density
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "was", "are",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "not", "no",
    "nor", "so", "yet", "both", "either", "neither", "as", "if", "then",
    "than", "when", "where", "who", "which", "what", "how", "all", "each",
    "more", "most", "other", "some", "such", "up", "out", "about", "into",
    "through", "after", "over", "between", "its", "their", "our", "your",
    "my", "his", "her", "we", "they", "you", "i", "me", "him", "us", "them",
    "any", "only", "also", "just", "very", "too", "s", "re", "ve", "ll",
    "d", "m", "t",
}


def strip_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    # Remove scripts and styles
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ")


def tokenise(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r"\b[a-zA-Z']{2,}\b", text)]


def count_sentences(text: str) -> int:
    return len(re.findall(r"[.!?]+", text)) or 1


def count_paragraphs(text: str) -> int:
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return max(len(paras), 1)


def build_seo_insights(
    word_count: int,
    title_missing: bool,
    top_kw: List[Dict],
) -> List[str]:
    insights: List[str] = []
    if word_count < 300:
        insights.append(
            "Content is thin (<300 words). Google prefers pages with at least 300 words."
        )
    elif word_count < 600:
        insights.append(
            "Content is moderate (300-600 words). Aim for 600+ for better rankings."
        )
    else:
        insights.append(f"Good content length ({word_count} words).")

    if top_kw:
        top = top_kw[0]
        density = top["density_percent"]
        if density > 3.0:
            insights.append(
                f"Keyword '{top['word']}' appears at {density:.1f}% density — may be over-optimised (ideal <3%)."
            )
        elif density < 0.5 and word_count > 300:
            insights.append(
                "No clearly dominant keyword detected — consider focusing on a primary topic."
            )
        else:
            insights.append(
                f"Primary keyword '{top['word']}' has a healthy density of {density:.1f}%."
            )
    return insights


@router.post(
    "/word-counter",
    summary="Analyse text for word count, readability & keyword density",
    response_description="Detailed word-count metrics and SEO insights",
)
async def word_counter(body: WordCounterRequest):
    text = body.text

    if len(text) > settings.MAX_TEXT_CHARS:
        raise PayloadTooLargeException(
            TOOL, f"Text must not exceed {settings.MAX_TEXT_CHARS:,} characters."
        )

    # Strip HTML if needed
    if body.strip_html:
        text = strip_html(text)
    text = html_lib.unescape(text)

    # Metrics
    words = tokenise(text)
    word_count = len(words)
    char_count = len(text)
    char_no_spaces = len(text.replace(" ", ""))
    sentence_count = count_sentences(text)
    paragraph_count = count_paragraphs(text)
    avg_word_len = (
        round(sum(len(w) for w in words) / word_count, 2) if word_count else 0.0
    )
    # ~200 words/min average reading speed
    reading_time = round(word_count / 200, 1)
    unique_words = len(set(words))

    # Keyword density (exclude stop words, min 3 chars)
    content_words = [w for w in words if w not in STOP_WORDS and len(w) >= 3]
    freq = Counter(content_words)
    total_content = len(content_words) or 1

    top_keywords = [
        {
            "word": word,
            "count": count,
            "density_percent": round((count / total_content) * 100, 2),
        }
        for word, count in freq.most_common(20)
    ]

    keyword_density = {
        item["word"]: item["density_percent"] for item in top_keywords
    }

    seo_insights = build_seo_insights(word_count, False, top_keywords)

    result = WordCounterResponse(
        word_count=word_count,
        character_count=char_count,
        character_count_no_spaces=char_no_spaces,
        sentence_count=sentence_count,
        paragraph_count=paragraph_count,
        average_word_length=avg_word_len,
        reading_time_minutes=reading_time,
        unique_words=unique_words,
        top_keywords=top_keywords,
        keyword_density=keyword_density,
        seo_insights=seo_insights,
    )

    return ok(TOOL, result.model_dump())
