"""Módulo de envío de notificaciones: SMTP, Teams y Slack.

Cada sender es independiente y gestiona su propio manejo de errores.
Si un canal de envío no está configurado, lo omite silenciosamente.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from src.config import settings
from src.renderers import get_subject

if TYPE_CHECKING:
    from src.models import RankedNewsItem

logger = logging.getLogger(__name__)


# ── SMTP ──────────────────────────────────────────────────────────────


class EmailSender:
    """Envía el HTML email generado por SMTP con STARTTLS."""

    def send(
        self,
        html_path: Path,
        recipients: list[str] | None = None,
    ) -> bool:
        if not settings.smtp_host:
            logger.info("SMTP no configurado. Se omite el envío por email.")
            return False

        recip = recipients or [
            r.strip()
            for r in settings.email_recipients.split(",")
            if r.strip()
        ]
        if not recip:
            logger.warning("No hay destinatarios de email configurados.")
            return False

        html_content = html_path.read_text(encoding="utf-8")
        subject = get_subject()
        from_addr = (
            settings.smtp_from or settings.smtp_user or "noreply@cybernews.local"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(recip)
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=30
            ) as server:
                if settings.smtp_use_tls:
                    server.starttls(context=context)
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(from_addr, recip, msg.as_string())
            logger.info("Email enviado a %d destinatario(s).", len(recip))
            return True
        except Exception as exc:
            logger.error("Fallo al enviar email: %s", exc, exc_info=True)
            return False


# ── Microsoft Teams ───────────────────────────────────────────────────


class TeamsWebhookSender:
    """Envía una tarjeta MessageCard al webhook de Microsoft Teams."""

    def send(self, ranked: list[RankedNewsItem], subject: str) -> bool:
        if not settings.teams_webhook_url:
            logger.info("Teams webhook no configurado. Se omite.")
            return False

        facts = [
            {
                "name": f"#{r.rank} [{r.score:.1f} pts]",
                "value": f"[{r.item.title}]({r.item.url}) — {r.item.source_name}",
            }
            for r in ranked
        ]

        payload: dict = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "003B73",
            "summary": subject,
            "sections": [
                {
                    "activityTitle": f"🔐 {subject}",
                    "activitySubtitle": (
                        f"Top {settings.top_n} noticias de ciberseguridad del mes"
                    ),
                    "facts": facts,
                    "markdown": True,
                }
            ],
        }

        return self._post(settings.teams_webhook_url, payload, "Teams")

    @staticmethod
    def _post(url: str, payload: dict, name: str) -> bool:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
            logger.info("%s webhook enviado correctamente.", name)
            return True
        except Exception as exc:
            logger.error(
                "%s webhook falló: %s", name, exc, exc_info=True
            )
            return False


# ── Slack ─────────────────────────────────────────────────────────────


class SlackWebhookSender:
    """Envía un mensaje Block Kit al webhook de Slack."""

    def send(self, ranked: list[RankedNewsItem], subject: str) -> bool:
        if not settings.slack_webhook_url:
            logger.info("Slack webhook no configurado. Se omite.")
            return False

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🔐 {subject}", "emoji": True},
            },
            {"type": "divider"},
        ]

        for r in ranked:
            item = r.item
            blurb = (item.summary_es or item.summary)[:160].strip()
            if blurb and not blurb.endswith((".", "!", "?")):
                blurb += "…"

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{r.rank}. <{item.url}|{item.title}>*\n"
                            f"_{item.source_name}_ | "
                            f"{item.published_at.strftime('%d/%m/%Y')} | "
                            f"Score: {r.score:.1f}\n"
                            f"{blurb}"
                        ),
                    },
                }
            )
            blocks.append({"type": "divider"})

        payload = {"blocks": blocks}
        return TeamsWebhookSender._post(
            settings.slack_webhook_url, payload, "Slack"
        )
