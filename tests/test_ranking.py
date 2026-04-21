"""Tests del motor de scoring y ranking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models import NewsItem
from src.ranking import KEYWORD_WEIGHTS, rank_items, score_item


# ── Helpers ────────────────────────────────────────────────────────────


def make_item(
    title: str,
    summary: str = "",
    source: str = "TestSource",
    days_ago: int = 1,
    url_suffix: str = "",
) -> NewsItem:
    published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    slug = url_suffix or title[:20].replace(" ", "-").lower()
    return NewsItem(
        title=title,
        url=f"https://example.com/{slug}",
        source_name=source,
        published_at=published,
        summary=summary,
    )


# ── Score ──────────────────────────────────────────────────────────────


def test_critical_keywords_score_high() -> None:
    item = make_item("Critical zero-day RCE exploit found in npm package")
    score, keywords = score_item(item)
    assert score > 15.0, f"Se esperaba score alto, obtenido: {score}"
    detected = set(keywords)
    assert "zero-day" in detected or "zero day" in detected
    assert "rce" in detected or "remote code execution" in detected


def test_irrelevant_news_scores_low() -> None:
    item = make_item("Company announces new quarterly earnings results")
    score, keywords = score_item(item)
    # Sin keywords de seguridad sólo recency (≤10) y nada más
    assert score < 12.0, f"Score inesperadamente alto: {score}"
    assert keywords == []


def test_recency_decay() -> None:
    """Noticia reciente debe puntuar más que la misma con más días."""
    fresh = make_item("ransomware attack campaign", days_ago=1)
    stale = make_item("ransomware attack campaign", days_ago=32, url_suffix="old")
    fresh_score, _ = score_item(fresh)
    stale_score, _ = score_item(stale)
    assert fresh_score > stale_score, (
        f"Fresh ({fresh_score}) debería > Stale ({stale_score})"
    )


def test_keyword_score_capped() -> None:
    """El score de keywords no debe superar MAX_KEYWORD_SCORE (20)."""
    # Ponemos todos los keywords de alto peso en el título
    mega_title = " ".join(list(KEYWORD_WEIGHTS.keys())[:30])
    item = make_item(mega_title)
    score, _ = score_item(item)
    # keyword cap = 20, recency max = 10 → techo ≤ 30
    assert score <= 30.1


def test_supply_chain_weight() -> None:
    """supply chain attack debe tener alto peso."""
    item = make_item("New supply chain attack targets PyPI packages")
    score, keywords = score_item(item)
    assert "supply chain" in keywords or "supply chain attack" in keywords
    assert score > 10.0


# ── Rank ───────────────────────────────────────────────────────────────


def test_rank_items_returns_top_n(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.ranking.settings.top_n", 4)
    items = [make_item(f"News item {i}", url_suffix=str(i)) for i in range(20)]
    ranked = rank_items(items)
    assert len(ranked) == 4, f"Se esperaban 4, obtenidos: {len(ranked)}"


def test_rank_returns_less_than_n_when_few_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.ranking.settings.top_n", 4)
    items = [make_item("Only one item", url_suffix="x")]
    ranked = rank_items(ranked_items := items)
    ranked = rank_items(items)
    assert len(ranked) == 1


def test_rank_order_descending() -> None:
    """El ítem con mayor score debe aparecer en rank=1."""
    items = [make_item(f"Normal news {i}", url_suffix=str(i)) for i in range(10)]
    # Inyectar un ítem claramente superior
    items.append(
        make_item(
            "Critical zero-day RCE in npm supply chain backdoor",
            url_suffix="best",
        )
    )
    ranked = rank_items(items)
    assert ranked[0].rank == 1
    assert ranked[0].item.url == "https://example.com/best"


def test_source_diversity_in_top4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con diversidad activada, una fuente única no debe monopolizar el top-4."""
    monkeypatch.setattr("src.ranking.settings.top_n", 4)
    # 8 ítems de "SourceA" con keywords potentes + 2 de "SourceB" medios
    source_a = [
        make_item(
            f"ransomware zero-day exploit {i}",
            source="SourceA",
            url_suffix=f"a{i}",
        )
        for i in range(8)
    ]
    source_b = [
        make_item(f"critical vulnerability {i}", source="SourceB", url_suffix=f"b{i}")
        for i in range(2)
    ]
    ranked = rank_items(source_a + source_b)
    sources = [r.item.source_name for r in ranked]
    # SourceB debería aparecer al menos una vez gracias a la penalidad de diversidad
    assert "SourceB" in sources, f"SourceB ausente en top4: {sources}"


def test_rank_empty_input() -> None:
    assert rank_items([]) == []
