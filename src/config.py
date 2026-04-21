"""Configuración centralizada vía variables de entorno (.env)."""
from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    app_name: str = "CyberNews Scraper"
    log_level: str = "INFO"
    output_dir: str = "output"

    # ── Base de datos ────────────────────────────────────────────────
    db_path: str = "data/cybernews.db"

    # ── HTTP ─────────────────────────────────────────────────────────
    http_timeout: int = 30
    http_max_retries: int = 3
    http_user_agent: str = (
        "Mozilla/5.0 (compatible; CyberNewsBot/1.0)"
    )

    # ── Selección de contenido ───────────────────────────────────────
    top_n: int = 4
    lookback_days: int = 35

    # ── SMTP ─────────────────────────────────────────────────────────
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    email_recipients: str = ""

    # ── Webhooks ─────────────────────────────────────────────────────
    teams_webhook_url: Optional[str] = None
    slack_webhook_url: Optional[str] = None

    # ── IA opcional ──────────────────────────────────────────────────
    openai_api_key: Optional[str] = None

    # ── Fuentes habilitadas ──────────────────────────────────────────
    enable_hackernews: bool = True
    enable_securityweek: bool = True
    enable_kaspersky: bool = True
    enable_welivesecurity: bool = True
    enable_cybersecnews: bool = False
    enable_kaspersky_latam: bool = True


settings = Settings()
