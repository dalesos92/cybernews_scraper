"""Tests del módulo de deduplicación."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.dedup import SIMILARITY_THRESHOLD, deduplicate, filter_already_sent
from src.models import NewsItem


# ── Helpers ────────────────────────────────────────────────────────────


def make_item(title: str, url: str, days_ago: int = 1) -> NewsItem:
    published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return NewsItem(
        title=title,
        url=url,
        source_name="TestSource",
        published_at=published,
    )


# ── Deduplicación ─────────────────────────────────────────────────────


def test_dedup_exact_url() -> None:
    items = [
        make_item("Article A", "https://example.com/article-a"),
        make_item("Article A – copy", "https://example.com/article-a"),  # misma URL
    ]
    result = deduplicate(items)
    assert len(result) == 1
    assert result[0].title == "Article A"


def test_dedup_url_with_query_params() -> None:
    """URLs que difieren sólo en query string deben considerarse la misma."""
    items = [
        make_item("Article B", "https://example.com/article-b?utm_source=rss"),
        make_item("Article B alt", "https://example.com/article-b?ref=newsletter"),
    ]
    result = deduplicate(items)
    assert len(result) == 1


def test_dedup_similar_title() -> None:
    items = [
        make_item(
            "Critical zero-day found in OpenSSL library",
            "https://source1.com/a",
        ),
        make_item(
            "Critical zero-day found in OpenSSL",  # ~96 % similitud
            "https://source2.com/b",
        ),
    ]
    result = deduplicate(items)
    assert len(result) == 1


def test_no_false_dedup_different_topics() -> None:
    items = [
        make_item("Ransomware attacks major hospital chain", "https://s1.com/a"),
        make_item("New zero-day vulnerability in Chrome browser", "https://s2.com/b"),
    ]
    result = deduplicate(items)
    assert len(result) == 2


def test_preserves_first_occurrence() -> None:
    """El primer ítem de cada grupo debe mantenerse."""
    items = [
        make_item("Supply chain attack hits npm ecosystem", "https://a.com/1"),
        make_item("Supply chain attack hits npm ecosystem again", "https://b.com/2"),
    ]
    result = deduplicate(items)
    assert len(result) == 1
    assert result[0].url == "https://a.com/1"


def test_dedup_empty_input() -> None:
    assert deduplicate([]) == []


def test_dedup_single_item() -> None:
    items = [make_item("Lone article", "https://example.com/lone")]
    assert deduplicate(items) == items


def test_case_insensitive_title_dedup() -> None:
    items = [
        make_item("CRITICAL RCE IN APACHE TOMCAT", "https://src1.com/x"),
        make_item("critical rce in apache tomcat", "https://src2.com/y"),
    ]
    result = deduplicate(items)
    assert len(result) == 1


# ── filter_already_sent ───────────────────────────────────────────────


def test_filter_removes_sent_items() -> None:
    new_item = make_item("New article", "https://example.com/new")
    old_item = make_item("Old article", "https://example.com/old")
    sent_hashes = {old_item.url_hash}
    result = filter_already_sent([new_item, old_item], sent_hashes)
    assert len(result) == 1
    assert result[0].title == "New article"


def test_filter_empty_sent_set() -> None:
    items = [
        make_item("Article X", "https://example.com/x"),
        make_item("Article Y", "https://example.com/y"),
    ]
    result = filter_already_sent(items, set())
    assert len(result) == 2


def test_filter_all_already_sent() -> None:
    items = [
        make_item("Article A", "https://example.com/a"),
        make_item("Article B", "https://example.com/b"),
    ]
    sent = {item.url_hash for item in items}
    result = filter_already_sent(items, sent)
    assert result == []
