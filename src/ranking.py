"""Motor de scoring y ranking de noticias.

Estrategia de puntuación:
  - Keyword score   → peso por keyword encontrada en título+resumen (cap 20 pts)
  - Recency score   → decaimiento lineal hasta LOOKBACK_DAYS (máx 10 pts)
  - Diversity penalty → penaliza repetir fuente en el top N seleccionado

La selección top-N usa un algoritmo greedy que aplica la penalidad
de diversidad en tiempo real, garantizando variedad de fuentes.
"""
from __future__ import annotations

import logging

from src.config import settings
from src.models import NewsItem, RankedNewsItem

logger = logging.getLogger(__name__)

# ── Tabla de keywords con sus pesos ──────────────────────────────────
# Prioriza amenazas críticas para equipos de desarrollo / AppSec / DevOps

KEYWORD_WEIGHTS: dict[str, float] = {
    # Crítico — explotación directa
    "remote code execution": 6.0,
    "rce": 6.0,
    "zero-day": 5.5,
    "zero day": 5.5,
    "0-day": 5.5,
    "supply chain attack": 6.0,
    "supply chain": 5.0,
    "supply-chain": 5.0,
    "malicious package": 5.5,
    "dependency confusion": 5.5,
    "typosquatting": 4.5,
    # Alto — compromisos graves
    "ransomware": 4.5,
    "critical vulnerability": 4.5,
    "critical": 3.5,
    "backdoor": 4.5,
    "privilege escalation": 4.5,
    "authentication bypass": 4.5,
    "unauthenticated": 4.0,
    "exploit": 4.0,
    # Medio-alto — impacto confirmado
    "data breach": 4.0,
    "breach": 3.5,
    "apt": 3.5,
    "cve-": 3.5,
    "vulnerability": 3.0,
    "malware": 3.0,
    "injection": 3.0,
    "sql injection": 3.5,
    "code injection": 3.5,
    "command injection": 4.0,
    "bypass": 3.0,
    "phishing": 2.5,
    "leak": 2.5,
    "exposed": 2.5,
    # Dev-specific — ecosistema software
    "npm": 4.0,
    "pypi": 4.0,
    "pip": 3.0,
    "cargo": 3.0,
    "rubygems": 3.0,
    "maven": 3.0,
    "dependency": 3.0,
    "package": 2.5,
    "open source": 2.5,
    "github": 2.5,
    "github actions": 4.5,
    "ci/cd": 4.0,
    "pipeline": 3.0,
    "dockerfile": 3.0,
    "container": 3.0,
    "docker": 3.0,
    "kubernetes": 3.5,
    "k8s": 3.5,
    "helm": 2.5,
    # Cloud & infra
    "aws": 2.5,
    "azure": 2.5,
    "gcp": 2.5,
    "cloud": 2.0,
    "s3 bucket": 4.0,
    "serverless": 2.5,
    # Identidad, secretos y tokens
    "api key": 3.5,
    "secret": 3.0,
    "credential": 3.0,
    "hardcoded": 3.5,
    "oauth": 3.0,
    "jwt": 3.0,
    "token": 2.0,
    "ldap": 2.5,
    "saml": 2.5,
    "ssrf": 4.0,
    "idor": 3.5,
    "xss": 3.0,
    # Parches y actualizaciones
    "patch": 2.0,
    "update": 1.5,
    "advisory": 2.0,
}

# Prefijos / patrones que indican contenido promocional o no editorial
_PROMO_PREFIXES: tuple[str, ...] = (
    "[webinar]",
    "[sponsored]",
    "[free event]",
    "[partner]",
    "[advertisement]",
    "register now",
    "[live event]",
    "[free webinar]",
)

_MAX_KEYWORD_SCORE: float = 20.0
_RECENCY_MAX_SCORE: float = 10.0
# Penalidad alta por fuente repetida: evita que una sola fuente monopolice el top-N
_SOURCE_DIVERSITY_PENALTY: float = 8.0


# ── Funciones públicas ────────────────────────────────────────────────


def score_item(item: NewsItem) -> tuple[float, list[str]]:
    """Calcula puntuación y keywords encontradas para un NewsItem.

    Returns:
        (total_score, lista de keywords detectadas)
    """
    text = f"{item.title} {item.summary}".lower()

    keyword_score = 0.0
    found: list[str] = []

    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword in text:
            keyword_score += weight
            found.append(keyword)

    keyword_score = min(keyword_score, _MAX_KEYWORD_SCORE)

    # Recency: decaimiento lineal desde publicación hasta LOOKBACK_DAYS
    age = item.age_days()
    recency_score = max(
        0.0,
        _RECENCY_MAX_SCORE * (1.0 - age / settings.lookback_days),
    )

    return keyword_score + recency_score, found


def _is_promotional(item: NewsItem) -> bool:
    """Detecta contenido no editorial (webinars, patrocinados, etc.)."""
    title_lower = item.title.lower().strip()
    return any(title_lower.startswith(p) for p in _PROMO_PREFIXES)


def rank_items(items: list[NewsItem]) -> list[RankedNewsItem]:
    """Puntúa, aplica diversidad de fuentes y devuelve el top-N.

    Algoritmo greedy: en cada iteración selecciona el ítem con mayor
    puntuación ajustada (base − penalidad acumulada por fuente),
    garantizando variedad en el resultado final.
    """
    if not items:
        return []

    # Filtrar contenido promocional antes de puntuar
    filtered = [i for i in items if not _is_promotional(i)]
    if len(filtered) < len(items):
        logger.info(
            "Filtrados %d ítems promocionales/webinar.",
            len(items) - len(filtered),
        )
    items = filtered
    if not items:
        return []

    # 1. Puntuar todos los ítems
    for item in items:
        s, kw = score_item(item)
        item.score = s
        item.keywords_found = kw

    # 2. Selección greedy con penalidad por fuente repetida
    candidates = list(items)
    result: list[RankedNewsItem] = []
    source_counts: dict[str, int] = {}

    while len(result) < settings.top_n and candidates:
        best_item: NewsItem | None = None
        best_adjusted = float("-inf")

        for item in candidates:
            count = source_counts.get(item.source_name, 0)
            adjusted = item.score - count * _SOURCE_DIVERSITY_PENALTY
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_item = item

        if best_item is None:
            break

        candidates.remove(best_item)
        source_counts[best_item.source_name] = (
            source_counts.get(best_item.source_name, 0) + 1
        )
        result.append(
            RankedNewsItem(
                rank=len(result) + 1,
                item=best_item,
                score=round(best_adjusted, 3),
            )
        )

    logger.debug(
        "Ranking: %d ítems candidatos → %d seleccionados",
        len(items),
        len(result),
    )
    return result
