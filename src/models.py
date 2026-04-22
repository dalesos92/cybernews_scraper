"""Modelos de datos del sistema."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class StructuredInsight(BaseModel):
    """Desglose estructurado de una noticia de ciberseguridad."""

    afectados: str = ""    # Empresas, sistemas, usuarios afectados
    cifras: str = ""       # Números, CVEs, estadísticas relevantes
    que_paso: str = ""     # Qué ocurrió exactamente (1-2 líneas)
    mitigacion: str = ""   # Acciones recomendadas para mitigar
    insight_dev: str = ""  # Takeaway clave para equipos de desarrollo


class ExecutiveInsight(BaseModel):
    """Análisis ejecutivo no técnico de una noticia de ciberseguridad.

    Pensado para alta dirección: lenguaje de negocio, sin jerga técnica.
    """

    nivel_riesgo: str = "MEDIO"
    # CRÍTICO / ALTO / MEDIO / BAJO

    porcentaje_afectacion: int = 0
    # Estimación del impacto operativo (0-100 %)

    segmento: str = ""
    # Área de negocio más expuesta: Continuidad Operativa, Protección de Datos,
    # Fraude Financiero, Infraestructura TI, Reputación Digital, Cumplimiento

    impacto_negocio: str = ""
    # Descripción ejecutiva del impacto en continuidad del negocio (sin jerga)

    riesgo_reputacional: str = ""
    # Consecuencias para la imagen institucional y la confianza de clientes

    perdida_potencial: str = ""
    # Estimación cualitativa/cuantitativa de la pérdida económica

    accion_directiva: str = ""
    # Acción recomendada a nivel directivo (no técnica)


class NewsItem(BaseModel):
    """Representa una noticia de ciberseguridad recopilada de una fuente."""

    title: str
    url: str
    source_name: str
    published_at: datetime
    summary: str = ""
    score: float = 0.0
    keywords_found: list[str] = Field(default_factory=list)
    # Resumen en español: generado por plantilla o LLM
    summary_es: str = ""
    # Desglose estructurado generado por el enriquecedor (técnico)
    insight: Optional[StructuredInsight] = None
    # Análisis ejecutivo generado por el enriquecedor (no técnico)
    executive_insight: Optional[ExecutiveInsight] = None

    @field_validator("published_at", mode="before")
    @classmethod
    def ensure_tz_aware(cls, v: object) -> object:
        """Garantiza que todas las fechas tengan zona horaria."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @property
    def url_hash(self) -> str:
        """Hash corto de la URL normalizada (sin query/fragment)."""
        normalized = re.sub(r"[?#].*$", "", self.url.lower().rstrip("/"))
        return hashlib.sha256(normalized.encode()).hexdigest()[:20]

    @property
    def title_hash(self) -> str:
        """Hash corto del título normalizado."""
        normalized = " ".join(self.title.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:20]

    def age_days(self) -> float:
        """Antigüedad de la noticia en días."""
        now = datetime.now(timezone.utc)
        return max(0.0, (now - self.published_at).total_seconds() / 86400)


class RankedNewsItem(BaseModel):
    """Noticia con su posición en el ranking mensual."""

    rank: int
    item: NewsItem
    score: float
