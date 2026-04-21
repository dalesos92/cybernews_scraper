"""Persistencia en SQLite para historial de noticias enviadas.

Usa sqlite3 nativo (stdlib) con queries parametrizadas para evitar
inyección SQL. La BD se crea automáticamente en el primer uso.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import NewsItem

logger = logging.getLogger(__name__)


class Storage:
    """Gestiona el historial de noticias ya enviadas para evitar duplicados."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Conexión ──────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Activar WAL para mejor concurrencia de lectura
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Inicialización ────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_items (
                    url_hash    TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    url         TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    score       REAL DEFAULT 0.0,
                    sent_at     TEXT NOT NULL,
                    batch_id    TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sent_at  ON sent_items(sent_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_id ON sent_items(batch_id)"
            )
            conn.commit()

    # ── API pública ───────────────────────────────────────────────────

    def get_sent_hashes(self, since_days: int = 90) -> set[str]:
        """Devuelve los url_hash de ítems enviados en los últimos N días."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=since_days)
        ).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT url_hash FROM sent_items WHERE sent_at >= ?",
                (cutoff,),
            ).fetchall()
        return {row["url_hash"] for row in rows}

    def save_sent_items(
        self, items: list[NewsItem], batch_id: str
    ) -> None:
        """Registra los ítems como enviados para este batch mensual."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sent_items
                        (url_hash, title, url, source_name,
                         published_at, score, sent_at, batch_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.url_hash,
                        item.title,
                        item.url,
                        item.source_name,
                        item.published_at.isoformat(),
                        item.score,
                        now,
                        batch_id,
                    ),
                )
            conn.commit()
        logger.info(
            "Storage: %d ítems guardados (batch=%s).", len(items), batch_id
        )

    def get_batch_history(self, limit: int = 12) -> list[dict]:
        """Devuelve el historial de batches recientes."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT batch_id,
                       COUNT(*)    AS item_count,
                       MIN(sent_at) AS sent_at
                FROM sent_items
                GROUP BY batch_id
                ORDER BY sent_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
