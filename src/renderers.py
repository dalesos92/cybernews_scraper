"""Renderizado de salidas: JSON, Markdown y HTML email.

Todos los artefactos se escriben en OUTPUT_DIR (configurable via .env).
El HTML email usa una plantilla Jinja2; si la plantilla no existe,
activa un fallback HTML inline para garantizar siempre una salida válida.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import settings
from src.models import RankedNewsItem

logger = logging.getLogger(__name__)

# Nombres de mes en español para el asunto del correo
_MONTH_ES: dict[int, str] = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# Directorio de plantillas relativo al paquete (robusto ante cwd distinto)
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def get_subject(dt: Optional[datetime] = None) -> str:
    """Genera el asunto sugerido para el correo mensual."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return (
        f"Top {settings.top_n} noticias de ciberseguridad"
        f" - {_MONTH_ES[dt.month]} {dt.year}"
    )


class Renderer:
    """Genera los tres formatos de salida requeridos."""

    def __init__(
        self,
        output_dir: str = "",
        templates_dir: Optional[str] = None,
    ) -> None:
        self.output_dir = Path(output_dir or settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        tpl_dir = Path(templates_dir) if templates_dir else _TEMPLATES_DIR
        if not tpl_dir.exists():
            tpl_dir = Path("templates")  # fallback relativo al cwd

        self._jinja_env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html"]),
        )
        # Filtro personalizado para formatear fechas dentro de plantillas
        self._jinja_env.filters["date_es"] = lambda dt: (
            dt.strftime("%d/%m/%Y") if dt else ""
        )

    # ── Salidas públicas ──────────────────────────────────────────────

    def render_json(self, ranked: list[RankedNewsItem]) -> Path:
        """Genera top4_monthly.json."""
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "subject": get_subject(),
            "items": [
                {
                    "rank": r.rank,
                    "title": r.item.title,
                    "url": r.item.url,
                    "source": r.item.source_name,
                    "published_at": r.item.published_at.isoformat(),
                    "score": round(r.score, 2),
                    "keywords_found": r.item.keywords_found,
                    "summary_es": r.item.summary_es or r.item.summary,
                    "analisis": (
                        {
                            "afectados": r.item.insight.afectados,
                            "cifras": r.item.insight.cifras,
                            "que_paso": r.item.insight.que_paso,
                            "mitigacion": r.item.insight.mitigacion,
                            "insight_dev": r.item.insight.insight_dev,
                        }
                        if r.item.insight
                        else None
                    ),
                }
                for r in ranked
            ],
        }
        path = self.output_dir / "top4_monthly.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("JSON generado: %s", path)
        return path

    def render_markdown(self, ranked: list[RankedNewsItem]) -> Path:
        """Genera top4_monthly.md."""
        now = datetime.now(timezone.utc)
        subject = get_subject(now)
        lines: list[str] = [
            f"# {subject}\n",
            f"_Generado el {now.strftime('%d/%m/%Y %H:%M')} UTC_\n",
        ]
        for r in ranked:
            item = r.item
            date_str = item.published_at.strftime("%d/%m/%Y")
            kw_str = (
                " · ".join(f"`{k}`" for k in item.keywords_found[:5])
                if item.keywords_found
                else "—"
            )
            lines += [
                f"\n## {r.rank}. {item.title}",
                "",
                f"| Campo | Valor |",
                f"|---|---|",
                f"| Fuente | {item.source_name} |",
                f"| Fecha | {date_str} |",
                f"| Score | {r.score:.1f} |",
                f"| Keywords | {kw_str} |",
                f"| URL | <{item.url}> |",
                "",
            ]
            if item.insight:
                ins = item.insight
                lines += [
                    "### Análisis",
                    "",
                    f"**🟠 Afectados:** {ins.afectados}",
                    "",
                    f"**🔢 Cifras / CVEs:** {ins.cifras}",
                    "",
                    f"**💥 Qué pasó:** {ins.que_paso}",
                    "",
                    f"**🛡️ Mitigación:** {ins.mitigacion}",
                    "",
                    f"**💡 Insight para devs:** {ins.insight_dev}",
                    "",
                ]
            lines.append("---")

        path = self.output_dir / "top4_monthly.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Markdown generado: %s", path)
        return path

    def render_remaining_md(self, remaining: list["NewsItem"]) -> Path:
        """Genera remaining_news.md con todas las noticias fuera del top-N."""
        from src.models import NewsItem  # import local para evitar ciclo

        now = datetime.now(timezone.utc)
        lines: list[str] = [
            "# Resto de noticias recopiladas\n",
            f"_Generado el {now.strftime('%d/%m/%Y %H:%M')} UTC — "
            f"{len(remaining)} noticias fuera del Top {settings.top_n}_\n",
        ]
        for i, item in enumerate(remaining, start=1):
            date_str = item.published_at.strftime("%d/%m/%Y")
            kw_str = (
                " · ".join(f"`{k}`" for k in item.keywords_found[:4])
                if item.keywords_found
                else "—"
            )
            lines += [
                f"\n### {i}. {item.title}",
                "",
                f"| Campo | Valor |",
                f"|---|---|",
                f"| Fuente | {item.source_name} |",
                f"| Fecha | {date_str} |",
                f"| Score | {item.score:.1f} |",
                f"| Keywords | {kw_str} |",
                f"| URL | <{item.url}> |",
                "",
                "---",
            ]

        path = self.output_dir / "remaining_news.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Remaining Markdown generado: %s", path)
        return path

    def render_remaining_html(self, remaining: list) -> Path:
        """Genera remaining_news.html con todas las noticias fuera del top-N."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d/%m/%Y %H:%M UTC")

        rows_html = ""
        for i, item in enumerate(remaining, start=1):
            pub = item.published_at.strftime("%d/%m/%Y")
            kw_badges = "".join(
                f'<span style="display:inline-block;background:#e8f0fe;color:#1a56db;'
                f'padding:2px 7px;border-radius:10px;font-size:11px;margin:0 3px 3px 0;">'
                f'{kw}</span>'
                for kw in item.keywords_found[:4]
            ) or '<span style="color:#aaa;">—</span>'
            rows_html += f"""
            <tr style="border-bottom:1px solid #eee;">
              <td style="padding:10px 8px;color:#888;font-size:13px;
                         text-align:center;vertical-align:top;">{i}</td>
              <td style="padding:10px 12px;vertical-align:top;">
                <a href="{item.url}" target="_blank"
                   style="color:#003B73;font-weight:bold;font-size:14px;
                          text-decoration:none;line-height:1.4;">{item.title}</a>
                <div style="margin-top:5px;">{kw_badges}</div>
              </td>
              <td style="padding:10px 8px;font-size:13px;color:#555;
                         vertical-align:top;white-space:nowrap;">{item.source_name}</td>
              <td style="padding:10px 8px;font-size:13px;color:#555;
                         vertical-align:top;white-space:nowrap;">{pub}</td>
              <td style="padding:10px 8px;font-size:13px;color:#777;
                         text-align:right;vertical-align:top;
                         white-space:nowrap;">{item.score:.1f}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resto de noticias — CyberNews Scraper</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;
             font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f4f4;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="860" cellpadding="0" cellspacing="0"
               style="max-width:860px;background:#fff;border-radius:8px;
                      border:1px solid #dde3ec;overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="background:#003B73;padding:24px 36px;">
              <h1 style="color:#fff;margin:0;font-size:19px;font-weight:bold;">
                📋 Resto de noticias recopiladas
              </h1>
              <p style="color:#9ec3e6;margin:6px 0 0;font-size:13px;">
                {date_str} &nbsp;·&nbsp; {len(remaining)} noticias fuera del
                Top&nbsp;{settings.top_n} &nbsp;·&nbsp;
                <a href="top4_email.html"
                   style="color:#9ec3e6;text-decoration:underline;">
                  ← Volver al Top {settings.top_n}
                </a>
              </p>
            </td>
          </tr>

          <!-- Tabla de noticias -->
          <tr>
            <td style="padding:24px 36px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;">
                <thead>
                  <tr style="background:#003B73;color:#fff;">
                    <th style="padding:9px 8px;font-size:12px;width:36px;">#</th>
                    <th style="padding:9px 12px;font-size:12px;text-align:left;">Noticia</th>
                    <th style="padding:9px 8px;font-size:12px;text-align:left;">Fuente</th>
                    <th style="padding:9px 8px;font-size:12px;text-align:left;">Fecha</th>
                    <th style="padding:9px 8px;font-size:12px;text-align:right;">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {rows_html}
                </tbody>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 36px;border-top:1px solid #e4e9f0;
                       background:#f9fafb;text-align:center;">
              <p style="color:#999;font-size:12px;margin:0;">
                Generado automáticamente por <strong>CyberNews Scraper</strong>.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        path = self.output_dir / "remaining_news.html"
        path.write_text(html, encoding="utf-8")
        logger.info("Remaining HTML generado: %s", path)
        return path

    def render_html_email(self, ranked: list[RankedNewsItem]) -> Path:
        """Genera top4_email.html usando plantilla Jinja2."""
        now = datetime.now(timezone.utc)
        try:
            template = self._jinja_env.get_template("email.html.j2")
            html = template.render(
                subject=get_subject(now),
                items=ranked,
                generated_at=now.strftime("%d/%m/%Y %H:%M UTC"),
                top_n=settings.top_n,
            )
        except Exception as exc:
            logger.warning(
                "Plantilla Jinja2 no disponible (%s). Usando fallback inline.",
                exc,
            )
            html = self._inline_html(ranked, now)

        path = self.output_dir / "top4_email.html"
        path.write_text(html, encoding="utf-8")
        logger.info("HTML email generado: %s", path)
        return path

    # ── Fallback HTML inline ──────────────────────────────────────────

    @staticmethod
    def _inline_html(ranked: list[RankedNewsItem], now: datetime) -> str:
        subject = get_subject(now)
        items_html = ""
        for r in ranked:
            item = r.item
            kw_badges = " ".join(
                f'<span style="background:#e8f0fe;color:#1a56db;'
                f'padding:2px 7px;border-radius:10px;font-size:12px;'
                f'margin-right:4px;">{k}</span>'
                for k in item.keywords_found[:5]
            )
            # Bloque de análisis estructurado
            if item.insight:
                ins = item.insight
                analysis_html = f"""
              <table style="width:100%;border-collapse:collapse;
                            margin:10px 0 12px;font-size:13px;">
                <tr style="background:#eef4fb;">
                  <td style="padding:6px 10px;font-weight:bold;
                             color:#003B73;width:130px;">🟠 Afectados</td>
                  <td style="padding:6px 10px;color:#333;">{ins.afectados}</td>
                </tr>
                <tr style="background:#fff;">
                  <td style="padding:6px 10px;font-weight:bold;color:#003B73;">
                    🔢 Cifras / CVEs</td>
                  <td style="padding:6px 10px;color:#333;font-family:monospace;">
                    {ins.cifras}</td>
                </tr>
                <tr style="background:#eef4fb;">
                  <td style="padding:6px 10px;font-weight:bold;color:#003B73;">
                    💥 Qué pasó</td>
                  <td style="padding:6px 10px;color:#333;line-height:1.5;">
                    {ins.que_paso}</td>
                </tr>
                <tr style="background:#fff;">
                  <td style="padding:6px 10px;font-weight:bold;color:#003B73;">
                    🛡️ Mitigación</td>
                  <td style="padding:6px 10px;color:#333;line-height:1.5;">
                    {ins.mitigacion}</td>
                </tr>
                <tr style="background:#fffbea;">
                  <td style="padding:6px 10px;font-weight:bold;color:#7c5f00;">
                    💡 Insight dev</td>
                  <td style="padding:6px 10px;color:#5a4000;line-height:1.5;">
                    {ins.insight_dev}</td>
                </tr>
              </table>"""
            else:
                summary = item.summary_es or item.summary
                analysis_html = (
                    f'<p style="margin:0 0 10px 0;color:#333;font-size:14px;'
                    f'line-height:1.6;">{summary}</p>'
                )

            items_html += f"""
            <div style="margin-bottom:20px;padding:16px;
                        border-left:4px solid #003B73;background:#f9fbfd;
                        border-radius:4px;">
              <h3 style="margin:0 0 6px 0;font-size:16px;color:#003B73;">
                <span style="background:#003B73;color:#fff;padding:2px 8px;
                             border-radius:10px;font-size:12px;
                             margin-right:6px;">#{r.rank}</span>
                <a href="{item.url}" style="color:#003B73;text-decoration:none;">
                  {item.title}
                </a>
              </h3>
              <p style="margin:0 0 6px 0;color:#666;font-size:13px;">
                📰 {item.source_name} &nbsp;|&nbsp;
                📅 {item.published_at.strftime("%d/%m/%Y")} &nbsp;|&nbsp;
                ⭐ {r.score:.1f} pts
              </p>
              {f'<p style="margin:0 0 8px 0;">{kw_badges}</p>' if kw_badges else ""}
              {analysis_html}
              <a href="{item.url}" style="color:#0066cc;font-size:13px;">
                Leer artículo completo →
              </a>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;
             font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f4f4;padding:20px 0;">
    <tr><td align="center">
      <table width="680" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;
                    border:1px solid #e0e0e0;overflow:hidden;">
        <tr>
          <td style="background:#003B73;padding:24px 32px;">
            <h1 style="color:#fff;margin:0;font-size:21px;">
              🔐 {subject}
            </h1>
            <p style="color:#a8c4e0;margin:6px 0 0;font-size:13px;">
              Generado el {now.strftime("%d/%m/%Y %H:%M")} UTC
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px 8px;">
            <p style="color:#333;font-size:15px;margin:0;">
              Selección de las <strong>{len(ranked)} noticias más relevantes</strong>
              del mes para equipos de desarrollo, AppSec y DevOps.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:8px 32px 24px;">
            {items_html}
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px;border-top:1px solid #e0e0e0;
                     background:#f9f9f9;">
            <p style="color:#999;font-size:12px;margin:0;text-align:center;">
              Informe generado automáticamente por CyberNews Scraper.<br>
              Para ajustar fuentes o destinatarios, edita el archivo .env.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
