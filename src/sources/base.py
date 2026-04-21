"""Clase base abstracta para todas las fuentes de noticias."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.models import NewsItem

logger = logging.getLogger(__name__)


class BaseSource(ABC):
    """Contrato común para fuentes RSS y scrapers HTML.

    Cada fuente concreta implementa `_fetch`. El método público
    `fetch` envuelve la llamada con aislamiento de errores: si una
    fuente falla, devuelve lista vacía en lugar de propagar la
    excepción y abortar el pipeline completo.
    """

    name: str = "BaseSource"
    rss_url: str | None = None
    site_url: str | None = None

    def fetch(self) -> list[NewsItem]:
        """Ejecuta la recolección con aislamiento de errores por fuente."""
        try:
            return self._fetch()
        except Exception as exc:
            logger.error(
                "[%s] Fallo en fetch: %s", self.name, exc, exc_info=True
            )
            return []

    @abstractmethod
    def _fetch(self) -> list[NewsItem]: ...
