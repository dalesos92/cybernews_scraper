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

    # ── Google Drive / Apps Script integration ───────────────────────
    # Ruta LOCAL al JSON de la Service Account (NUNCA commitear este archivo)
    google_sa_key_path: Optional[str] = None
    # ID de la carpeta Drive donde se suben HTML + JSON
    google_drive_folder_id: Optional[str] = None
    # ID del Google Sheet con destinatarios (usado solo como referencia/doc)
    google_sheets_recipients_id: Optional[str] = None
    # Template a usar para el email Drive: a | b | c  (default: a)
    google_email_template: str = "a"
    # URL del Web App de Apps Script (endpoint doPost)
    google_appscript_webhook_url: Optional[str] = None
    # Token de autenticacion para el Web App (debe coincidir con Script Properties)
    google_appscript_token: Optional[str] = None

    # ── Fuentes habilitadas ──────────────────────────────────────────
    # Fuentes en español
    enable_welivesecurity: bool = False   # deshabilitado: RSS con contenido mixto
    enable_cybersecnews_es: bool = True
    enable_hispasec: bool = True
    enable_revista_ciberseguridad: bool = True
    enable_incibe: bool = False           # deshabilitado: RSS devuelve solo índice
    enable_seguinfo: bool = True
    enable_kaspersky_latam: bool = True
    # Fuentes en inglés (deshabilitadas)
    enable_hackernews: bool = False
    enable_securityweek: bool = False
    enable_kaspersky: bool = False
    enable_cybersecnews: bool = False


settings = Settings()
