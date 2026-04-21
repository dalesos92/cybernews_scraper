"""Fuente genérica RSS/Atom con reintentos y fallback HTML."""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser
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


class RSSSource(BaseSource):
    """Lee cualquier feed RSS/Atom y convierte entradas en NewsItem.

    Si el feed no devuelve entradas (caído, vacío o bloqueado),
    delega en la fuente de fallback HTML si está configurada.
    """

    def __init__(
        self,
        name: str,
        rss_url: str,
        site_url: str = "",
        fallback: Optional[BaseSource] = None,
    ) -> None:
        self.name = name
        self.rss_url = rss_url
        self.site_url = site_url
        self._fallback = fallback

    def _fetch(self) -> list[NewsItem]:
        logger.info("[%s] Leyendo RSS: %s", self.name, self.rss_url)
        feed = self._parse_feed()

        if not feed.entries:
            logger.warning("[%s] Feed sin entradas.", self.name)
            if self._fallback:
                logger.info("[%s] Usando fallback HTML.", self.name)
                return self._fallback.fetch()
            return []

        items: list[NewsItem] = []
        for entry in feed.entries:
            item = self._entry_to_item(entry)
            if item:
                items.append(item)

        logger.info("[%s] %d ítems obtenidos via RSS.", self.name, len(items))
        return items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _parse_feed(self) -> feedparser.FeedParserDict:
        return feedparser.parse(
            self.rss_url,
            agent=settings.http_user_agent,
            request_headers={
                "User-Agent": settings.http_user_agent,
                "Accept": (
                    "application/rss+xml, application/atom+xml,"
                    " application/xml, text/xml"
                ),
            },
        )

    def _entry_to_item(
        self, entry: feedparser.FeedParserDict
    ) -> Optional[NewsItem]:
        try:
            title = (entry.get("title") or "").strip()
            url = (entry.get("link") or "").strip()
            if not title or not url:
                return None

            summary = self._extract_summary(entry)
            published_at = self._parse_date(entry)

            return NewsItem(
                title=title,
                url=url,
                source_name=self.name,
                published_at=published_at,
                summary=summary,
            )
        except Exception as exc:
            logger.warning("[%s] Error parseando entrada: %s", self.name, exc)
            return None

    @staticmethod
    def _extract_summary(entry: feedparser.FeedParserDict) -> str:
        """Extrae y limpia el resumen de texto de una entrada RSS."""
        raw = ""
        if detail := entry.get("summary_detail"):
            raw = detail.get("value", "")
        elif summary := entry.get("summary"):
            raw = summary
        elif content := entry.get("content"):
            raw = content[0].get("value", "") if content else ""

        if not raw:
            return ""

        # Eliminar etiquetas HTML
        from bs4 import BeautifulSoup

        text = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
        return text[:500]

    @staticmethod
    def _parse_date(entry: feedparser.FeedParserDict) -> datetime:
        """Convierte campos de fecha de feedparser a datetime UTC."""
        # feedparser ofrece *_parsed como struct_time UTC
        for field in ("published_parsed", "updated_parsed", "created_parsed"):
            t = entry.get(field)
            if t:
                # calendar.timegm trata el struct_time como UTC
                return datetime.fromtimestamp(
                    calendar.timegm(t), tz=timezone.utc
                )

        # Fallback: campos de cadena
        for field in ("published", "updated", "created"):
            s = entry.get(field)
            if s:
                try:
                    dt = dateutil_parser.parse(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    pass

        return datetime.now(timezone.utc)
