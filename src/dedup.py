"""Deduplicación de noticias por URL normalizada y similitud de título.

Dos noticias se consideran duplicadas si:
  1. Sus URLs normalizadas (sin query/fragment) son idénticas, o
  2. Sus títulos normalizados tienen similitud ≥ SIMILARITY_THRESHOLD
     según SequenceMatcher (difflib, stdlib).
"""
from __future__ import annotations

import difflib
import logging

from src.models import NewsItem

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD: float = 0.78  # 78 % de similitud de título = duplicado


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Elimina duplicados por URL y por similitud de título.

    Preserva el primer ítem encontrado (el de mayor score si ya vienen
    ordenados) y descarta los posteriores reconocidos como duplicados.
    """
    seen_url_hashes: set[str] = set()
    seen_titles: list[str] = []
    result: list[NewsItem] = []

    for item in items:
        # --- Dedup por URL ---
        if item.url_hash in seen_url_hashes:
            logger.debug("Dedup URL: %.60s", item.title)
            continue

        # --- Dedup por similitud de título ---
        norm_title = " ".join(item.title.lower().split())
        is_dup = _is_similar_to_any(norm_title, seen_titles)
        if is_dup:
            continue

        seen_url_hashes.add(item.url_hash)
        seen_titles.append(norm_title)
        result.append(item)

    logger.debug(
        "Dedup: %d entradas → %d únicas", len(items), len(result)
    )
    return result


def filter_already_sent(
    items: list[NewsItem], sent_hashes: set[str]
) -> list[NewsItem]:
    """Excluye ítems cuyo url_hash ya está en el historial de envíos."""
    return [item for item in items if item.url_hash not in sent_hashes]


def _is_similar_to_any(title: str, seen: list[str]) -> bool:
    for existing in seen:
        ratio = difflib.SequenceMatcher(None, title, existing).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            logger.debug(
                "Dedup título (sim=%.2f): %.60s", ratio, title
            )
            return True
    return False
