"""Help centre content (E30 FR-30-5): markdown articles and "What's new" entries kept in the
repository (``success/help``), reviewed like code, with a small in-process search index.

Each file starts with a front-matter block::

    ---
    title: Schedule your first lesson
    summary: Add a lesson to the calendar and invite the student.
    routes: /calendar, /jobs          (pages where the article is suggested)
    tags: lessons, calendar
    tour: calendar                    (optional: the product tour that goes with it)
    ---

Articles live in ``help/<locale>/<slug>.md`` (en-GB is the fallback); changelog entries
in ``help/changelog/<YYYY-MM-DD>-<slug>.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "help"
FALLBACK_LOCALE = "en-GB"
WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    summary: str
    body: str
    routes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    tour: str = ""
    words: frozenset[str] = field(default=frozenset(), compare=False, repr=False)


@dataclass(frozen=True)
class ChangelogEntry:
    slug: str
    title: str
    summary: str
    body: str
    published_on: date


def _parse(text: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        for line in head.splitlines():
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip()] = value.strip()
        return meta, body.strip()
    return meta, text.strip()


def _list(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(",") if v.strip())


def _words(*texts: str) -> frozenset[str]:
    return frozenset(WORD.findall(" ".join(texts).lower()))


@cache
def articles(locale: str = FALLBACK_LOCALE) -> dict[str, Article]:
    folder = ROOT / locale
    if not folder.is_dir():
        folder = ROOT / FALLBACK_LOCALE
    out: dict[str, Article] = {}
    for path in sorted(folder.glob("*.md")):
        meta, body = _parse(path.read_text(encoding="utf-8"))
        title = meta.get("title", path.stem)
        summary = meta.get("summary", "")
        tags = _list(meta.get("tags", ""))
        out[path.stem] = Article(
            slug=path.stem,
            title=title,
            summary=summary,
            body=body,
            routes=_list(meta.get("routes", "")),
            tags=tags,
            tour=meta.get("tour", ""),
            words=_words(title, summary, " ".join(tags), body),
        )
    return out


@cache
def changelog() -> list[ChangelogEntry]:
    entries = []
    for path in sorted((ROOT / "changelog").glob("*.md"), reverse=True):
        meta, body = _parse(path.read_text(encoding="utf-8"))
        published = date.fromisoformat(meta.get("date") or path.stem[:10])
        entries.append(
            ChangelogEntry(
                slug=path.stem,
                title=meta.get("title", path.stem),
                summary=meta.get("summary", ""),
                body=body,
                published_on=published,
            )
        )
    return entries


def _route_matches(article: Article, route: str) -> bool:
    route = route.rstrip("/") or "/"
    for prefix in article.routes:
        prefix = prefix.rstrip("/") or "/"
        if route == prefix or (prefix != "/" and route.startswith(prefix + "/")):
            return True
    return False


def _score(article: Article, terms: list[str]) -> int:
    title = _words(article.title)
    tags = _words(" ".join(article.tags))
    summary = _words(article.summary)
    score = 0
    for term in terms:
        if term in title:
            score += 5
        elif any(w.startswith(term) for w in title):
            score += 3
        if term in tags:
            score += 3
        if term in summary:
            score += 2
        if term in article.words:
            score += 1
        elif not any(w.startswith(term) for w in article.words):
            return 0  # every term must appear somewhere (prefixes count)
    return score


def search(query: str = "", route: str = "", locale: str = FALLBACK_LOCALE) -> list[Article]:
    """Articles for the help panel: with a query, the matches ranked by where the terms
    appear (title, tags, summary, body), the current page's articles first among equals;
    without one, the articles suggested for the current page."""
    terms = WORD.findall(query.lower())[:8]
    found: list[tuple[int, int, str, Article]] = []
    for article in articles(locale).values():
        on_page = 1 if route and _route_matches(article, route) else 0
        if terms:
            score = _score(article, terms)
            if score:
                found.append((-score, -on_page, article.title, article))
        elif on_page:
            found.append((0, 0, article.title, article))
    return [row[3] for row in sorted(found, key=lambda r: r[:3])]


def article(slug: str, locale: str = FALLBACK_LOCALE) -> Article | None:
    return articles(locale).get(slug) or articles(FALLBACK_LOCALE).get(slug)
