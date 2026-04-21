"""Scrapers HTML como fallback cuando el RSS no está disponible.

Los selectores CSS están desacoplados en dataclasses de configuración
para que puedan actualizarse sin tocar la lógica de extracción.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.models import NewsItem
from src.sources.base import BaseSource

logger = logging.getLogger(__name__)


# ── Configuración desacoplada por fuente ──────────────────────────────


@dataclass
class HTMLSourceConfig:
    """Define los selectores CSS y metadatos de una fuente HTML."""

    name: str
    url: str
    article_selector: str
    title_selector: str
    link_selector: str
    date_selector: str = ""
    summary_selector: str = ""
    link_attr: str = "href"
    date_attr: str = "datetime"
    max_items: int = 25


# Selectores validados para cada fuente principal
_HACKER_NEWS_CFG = HTMLSourceConfig(
    name="The Hacker News",
    url="https://thehackernews.com/",
    article_selector="div.body-post",
    title_selector="h2.home-title",
    link_selector="a.story-link",
    date_selector="span.h-datetime",
    summary_selector="div.home-desc",
)

_SECURITY_WEEK_CFG = HTMLSourceConfig(
    name="SecurityWeek",
    url="https://www.securityweek.com/",
    article_selector="article",
    title_selector="h3, h2",
    link_selector="a",
    date_selector="time",
    summary_selector="p",
    date_attr="datetime",
)

_KASPERSKY_CFG = HTMLSourceConfig(
    name="Kaspersky Securelist",
    url="https://securelist.com/",
    article_selector="article",
    title_selector="h2, h3",
    link_selector="a",
    date_selector="time",
    summary_selector="p",
    date_attr="datetime",
)


# ── Motor genérico de scraping HTML ──────────────────────────────────


class GenericHTMLSource(BaseSource):
    """Extractor HTML dirigido por configuración de selectores CSS.

    No contiene lógica específica de ningún sitio: adapta el comportamiento
    según el `HTMLSourceConfig` recibido.
    """

    def __init__(self, config: HTMLSourceConfig) -> None:
        self.config = config
        self.name = config.name
        self.site_url = config.url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _get_html(self) -> str:
        with httpx.Client(
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            resp = client.get(self.config.url)
            resp.raise_for_status()
            return resp.text

    def _fetch(self) -> list[NewsItem]:
        logger.info("[%s] Scraping HTML: %s", self.name, self.config.url)
        html = self._get_html()
        soup = BeautifulSoup(html, "lxml")
        articles = soup.select(self.config.article_selector)

        items: list[NewsItem] = []
        cfg = self.config

        for article in articles[: cfg.max_items]:
            item = self._parse_article(article, cfg)
            if item:
                items.append(item)

        logger.info(
            "[%s] %d ítems extraídos via HTML.", self.name, len(items)
        )
        return items

    def _parse_article(
        self, article: BeautifulSoup, cfg: HTMLSourceConfig
    ) -> Optional[NewsItem]:
        try:
            title_el = article.select_one(cfg.title_selector)
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            # URL del artículo
            link_el = article.select_one(cfg.link_selector)
            if not link_el:
                # Intentar buscar enlace en elemento padre o en el título
                link_el = title_el.find_parent("a") or title_el.find("a")
            if not link_el:
                return None

            href = link_el.get(cfg.link_attr, "")
            if not href:
                return None
            url = href if href.startswith("http") else urljoin(cfg.url, href)

            # Fecha de publicación
            published_at = self._parse_date_from_article(article, cfg)

            # Resumen
            summary = ""
            if cfg.summary_selector:
                summary_el = article.select_one(cfg.summary_selector)
                if summary_el:
                    summary = summary_el.get_text(" ", strip=True)[:400]

            return NewsItem(
                title=title,
                url=url,
                source_name=self.name,
                published_at=published_at,
                summary=summary,
            )
        except Exception as exc:
            logger.warning(
                "[%s] Error parseando artículo: %s", self.name, exc
            )
            return None

    @staticmethod
    def _parse_date_from_article(
        article: BeautifulSoup, cfg: HTMLSourceConfig
    ) -> datetime:
        if cfg.date_selector:
            date_el = article.select_one(cfg.date_selector)
            if date_el:
                date_str = date_el.get(cfg.date_attr, "") or date_el.get_text(
                    strip=True
                )
                if date_str:
                    try:
                        dt = dateutil_parser.parse(date_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt
                    except Exception:
                        pass
        return datetime.now(timezone.utc)


# ── Funciones de fábrica para cada fuente conocida ───────────────────


def HackerNewsHTMLSource() -> GenericHTMLSource:
    return GenericHTMLSource(_HACKER_NEWS_CFG)


def SecurityWeekHTMLSource() -> GenericHTMLSource:
    return GenericHTMLSource(_SECURITY_WEEK_CFG)


def KasperskyHTMLSource() -> GenericHTMLSource:
    return GenericHTMLSource(_KASPERSKY_CFG)


# ── Kaspersky LATAM Press Releases (scraper especializado) ────────────

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_fecha_es(text: str) -> datetime:
    """Parsea fechas en español como '20 de abril de 2026'."""
    import re
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", text.lower())
    if m:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = _MESES_ES.get(month_str)
        if month:
            return datetime(year, month, day, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


class KasperskyLatamSource(BaseSource):
    """Scraper para latam.kaspersky.com/about/press-releases."""

    name = "Kaspersky LATAM"
    site_url = "https://latam.kaspersky.com/about/press-releases"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _get_html(self) -> str:
        with httpx.Client(
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            resp = client.get(self.site_url)
            resp.raise_for_status()
            return resp.text

    def _fetch(self) -> list[NewsItem]:
        logger.info("[%s] Scraping HTML: %s", self.name, self.site_url)
        html = self._get_html()
        soup = BeautifulSoup(html, "lxml")

        items: list[NewsItem] = []
        # Cada comunicado está en un <article> o bloque con <h3> + enlace
        for block in soup.select("h3 a[href*='/about/press-releases/']")[:25]:
            try:
                title = block.get_text(strip=True)
                if not title:
                    continue
                href = block.get("href", "")
                url = href if href.startswith("http") else urljoin(self.site_url, href)

                # Fecha: texto anterior al enlace dentro del contenedor padre
                parent = block.find_parent()
                raw_text = parent.get_text(" ", strip=True) if parent else ""
                published_at = _parse_fecha_es(raw_text)

                # Resumen: texto del contenedor sin el título
                summary = raw_text.replace(title, "").replace("MÁS INFORMACIÓN", "").strip()
                summary = " ".join(summary.split())[:500]

                items.append(NewsItem(
                    title=title,
                    url=url,
                    source_name=self.name,
                    published_at=published_at,
                    summary=summary,
                ))
            except Exception as exc:
                logger.warning("[%s] Error parseando bloque: %s", self.name, exc)

        logger.info("[%s] %d ítems extraídos.", self.name, len(items))
        return items
