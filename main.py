#!/usr/bin/env python3
"""
CyberNews Scraper — Punto de entrada principal.

Uso básico:
    python main.py                   # ejecutar completo (recopila, rankea, envía)
    python main.py --dry-run         # sólo genera archivos, no guarda ni envía
    python main.py --skip-send       # genera y guarda, pero omite notificaciones
    python main.py --output-dir out  # sobreescribe el directorio de salida
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from src.config import settings
from src.dedup import deduplicate, filter_already_sent
from src.enricher import enrich_ranked
from src.enricher import _clean_summary
from src.models import NewsItem, RankedNewsItem
from src.ranking import rank_items
from src.renderers import Renderer, get_subject
from src.sender import EmailSender, SlackWebhookSender, TeamsWebhookSender
from src.sources.html import (
    KasperskyLatamSource,
)
from src.sources.rss import RSSSource
from src.storage import Storage


# ── Logging ───────────────────────────────────────────────────────────


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ── Construcción de fuentes ───────────────────────────────────────────


def build_sources() -> list[RSSSource]:
    """Construye la lista de fuentes activas según la configuración."""
    sources: list[RSSSource] = []

    if settings.enable_welivesecurity:
        sources.append(
            RSSSource(
                name="WeLiveSecurity ES",
                rss_url="https://www.welivesecurity.com/es/rss/feed/",
                site_url="https://www.welivesecurity.com/es/",
            )
        )

    if settings.enable_cybersecnews_es:
        sources.append(
            RSSSource(
                name="CyberSecurity News ES",
                rss_url="https://cybersecuritynews.es/feed/",
                site_url="https://cybersecuritynews.es/",
            )
        )

    if settings.enable_hispasec:
        sources.append(
            RSSSource(
                name="Hispasec Una-al-Día",
                rss_url="https://unaaldia.hispasec.com/feed/",
                site_url="https://unaaldia.hispasec.com/",
            )
        )

    if settings.enable_revista_ciberseguridad:
        sources.append(
            RSSSource(
                name="Revista Ciberseguridad",
                rss_url="https://www.revistaciberseguridad.com/feed/",
                site_url="https://www.revistaciberseguridad.com/",
            )
        )

    if settings.enable_incibe:
        sources.append(
            RSSSource(
                name="INCIBE-CERT",
                rss_url="https://www.incibe.es/rss.xml",
                site_url="https://www.incibe.es/",
            )
        )

    if settings.enable_seguinfo:
        sources.append(
            RSSSource(
                name="Segu-Info",
                rss_url="http://feeds.feedburner.com/NoticiasSeguridadInformatica",
                site_url="https://blog.segu-info.com.ar/",
            )
        )

    if settings.enable_kaspersky_latam:
        sources.append(KasperskyLatamSource())

    return sources


# ── Pipeline principal ────────────────────────────────────────────────


def run(
    dry_run: bool = False,
    skip_send: bool = False,
    output_dir: str | None = None,
) -> list[RankedNewsItem]:
    """Ejecuta el pipeline completo de recopilación y distribución."""
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    batch_id = datetime.now(timezone.utc).strftime("%Y-%m")
    logger.info("=" * 60)
    logger.info("CyberNews Scraper — batch %s", batch_id)
    logger.info("=" * 60)

    # 1. Recopilar desde todas las fuentes (error isolation por fuente)
    sources = build_sources()
    all_items: list[NewsItem] = []
    for source in sources:
        items = source.fetch()
        logger.info("  %-28s → %d ítems", f"[{source.name}]", len(items))
        all_items.extend(items)

    logger.info("Total recopilado: %d ítems", len(all_items))

    if not all_items:
        logger.error("No se obtuvieron noticias de ninguna fuente. Abortando.")
        return []

    # 2. Deduplicación en memoria
    unique = deduplicate(all_items)
    logger.info("Tras deduplicación: %d ítems únicos", len(unique))

    # 3. Filtrar ya-enviados (lookup en SQLite)
    storage = Storage(settings.db_path)
    sent_hashes = storage.get_sent_hashes(since_days=90)
    fresh = filter_already_sent(unique, sent_hashes)
    logger.info("Noticias nuevas (no enviadas en 90 días): %d", len(fresh))

    # 4. Fallback: si no hay suficientes noticias frescas, reusar únicas
    if len(fresh) < settings.top_n:
        logger.warning(
            "Sólo %d noticias frescas (objetivo: %d). "
            "Completando con noticias ya vistas.",
            len(fresh),
            settings.top_n,
        )
        seen_hashes = {i.url_hash for i in fresh}
        extras = [i for i in unique if i.url_hash not in seen_hashes]
        fresh = fresh + extras[: settings.top_n - len(fresh)]

    # 5. Scoring y selección top-N con diversidad de fuentes
    ranked = rank_items(fresh)
    logger.info("Top %d seleccionadas:", len(ranked))
    for r in ranked:
        logger.info(
            "  #%d [%.1f pts] %s (%s)",
            r.rank,
            r.score,
            r.item.title[:65],
            r.item.source_name,
        )

    # Calcular noticias que no entraron en el top-N (ya tienen score asignado)
    top_hashes = {r.item.url_hash for r in ranked}
    remaining = sorted(
        [i for i in fresh if i.url_hash not in top_hashes],
        key=lambda i: i.score,
        reverse=True,
    )

    # 6. Generar resúmenes en español
    _generate_summaries_es(ranked)

    # 7. Enriquecer con análisis estructurado (afectados, cifras, qué pasó, mitigación)
    logger.info("Enriqueciendo top-%d con análisis estructurado...", len(ranked))
    enrich_ranked(ranked)

    # 8. Renderizar salidas
    renderer = Renderer(output_dir=output_dir or settings.output_dir)
    renderer.render_json(ranked)
    renderer.render_markdown(ranked)
    renderer.render_remaining_md(remaining)
    renderer.render_remaining_html(remaining)
    html_path = renderer.render_html_email(ranked)

    if dry_run:
        logger.info("[DRY-RUN] Archivos generados. Sin guardar ni enviar.")
        return ranked

    # 9. Persistir en BD
    storage.save_sent_items([r.item for r in ranked], batch_id=batch_id)

    # 10. Enviar notificaciones
    if not skip_send:
        subject = get_subject()
        EmailSender().send(html_path)
        TeamsWebhookSender().send(ranked, subject)
        SlackWebhookSender().send(ranked, subject)

    logger.info("=" * 60)
    logger.info("Pipeline completado correctamente.")
    return ranked


# ── Generación de resúmenes en español ───────────────────────────────


def _generate_summaries_es(ranked: list[RankedNewsItem]) -> None:
    """Genera resúmenes en español.

    Si OPENAI_API_KEY está configurada, usa GPT-4o-mini.
    En caso contrario, construye un resumen estructurado por plantilla.
    """
    logger = logging.getLogger(__name__)

    if settings.openai_api_key:
        try:
            _openai_summaries(ranked)
            return
        except Exception as exc:
            logger.warning(
                "OpenAI no disponible (%s). Usando resumen por plantilla.", exc
            )

    for r in ranked:
        r.item.summary_es = _template_summary(r.item)


def _template_summary(item: NewsItem) -> str:
    date_str = item.published_at.strftime("%d/%m/%Y")
    kw = ", ".join(item.keywords_found[:3]) if item.keywords_found else "ciberseguridad"
    raw = _clean_summary(item.summary).strip()
    tail = "." if raw and not raw.endswith((".", "!", "?")) else ""
    return (
        f"**{item.source_name}** ({date_str}): {item.title}. "
        f"Áreas de impacto detectadas: {kw}. "
        + (f"{raw}{tail}" if raw else "")
    )


def _openai_summaries(ranked: list[RankedNewsItem]) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    for r in ranked:
        item = r.item
        prompt = (
            "Resume en 2-4 líneas en español técnico la siguiente noticia de "
            f"ciberseguridad para un equipo de desarrollo de software.\n"
            f"Título: {item.title}\n"
            f"Resumen original: {item.summary[:400]}\n"
            f"Fuente: {item.source_name}"
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=220,
            temperature=0.3,
        )
        item.summary_es = resp.choices[0].message.content.strip()


# ── CLI ───────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CyberNews Scraper — recopila y distribuye el top-4 mensual.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Genera archivos sin guardar en BD ni enviar notificaciones.",
    )
    parser.add_argument(
        "--skip-send",
        action="store_true",
        help="Guarda en BD pero omite el envío de email/webhooks.",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Directorio de salida (sobreescribe OUTPUT_DIR del .env).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    ranked = run(
        dry_run=args.dry_run,
        skip_send=args.skip_send,
        output_dir=args.output_dir,
    )
    if not ranked:
        sys.exit(1)

    print(f"\n{'-'*60}")
    print(f"  Top {len(ranked)} noticias del mes:")
    print(f"{'-'*60}")
    for r in ranked:
        print(f"  #{r.rank}  [{r.score:5.1f} pts]  {r.item.title[:68]}")
    print(f"{'-'*60}\n")


if __name__ == "__main__":
    main()
