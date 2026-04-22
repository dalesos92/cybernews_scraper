"""Sube artefactos generados a Google Drive.

Autenticación (en orden de prioridad):
1. `credentials` explícitas pasadas al llamar la función (ej. desde Colab tras authenticate_user).
2. Si GOOGLE_SA_KEY_PATH está definido en .env → usa esa clave explícita.
3. Si no → usa Application Default Credentials (ADC): gcloud auth / Cloud Run / GCE.
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    from googleapiclient.discovery import build as _gapi_build
    from googleapiclient.http import MediaFileUpload
except ImportError:  # se eleva con mensaje claro en upload_artifacts
    _gapi_build = None  # type: ignore[assignment]
    MediaFileUpload = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# MIME types por extensión de archivo
_MIME = {
    ".html": "text/html",
    ".json": "application/json",
    ".md": "text/markdown",
}


def upload_artifacts(
    paths: list[Path],
    folder_id: str,
    sa_key_path: str | None = None,
    credentials=None,
) -> dict[str, str]:
    """Sube una lista de archivos a la carpeta Drive indicada.

    Hace upsert: si ya existe un archivo con el mismo nombre en la carpeta,
    lo sobreescribe en lugar de crear un duplicado.

    Args:
        paths:       Lista de Path locales a subir.
        folder_id:   ID de la carpeta Google Drive destino.
        sa_key_path: (Opcional) Ruta al JSON de una Service Account explícita.
        credentials: (Opcional) Objeto de credenciales ya construido.
                     Tiene prioridad sobre sa_key_path y ADC.
                     Usar en Colab tras `google.colab.auth.authenticate_user()`.

    Returns:
        Dict {nombre_archivo: drive_file_id} con los IDs resultantes.

    Raises:
        ImportError:  Si google-api-python-client no está instalado.
        Exception:    Cualquier error de la API de Drive o de autenticación.
    """
    if _gapi_build is None:
        raise ImportError(
            "Dependencias de Google no instaladas. "
            "Ejecuta: pip install google-api-python-client google-auth"
        )

    creds = credentials or _get_credentials(sa_key_path)
    service = _gapi_build("drive", "v3", credentials=creds, cache_discovery=False)

    result: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            logger.warning("Archivo no encontrado, se omite: %s", path)
            continue
        mime = _MIME.get(path.suffix, "application/octet-stream")
        file_id = _upsert_file(service, path, mime, folder_id)
        result[path.name] = file_id
        logger.info("Drive upload OK: %s → file_id=%s", path.name, file_id)

    return result


def _get_credentials(sa_key_path: str | None):
    """Resuelve credenciales Google en orden de prioridad:
    1. SA key explícita (sa_key_path apunta a un JSON válido).
    2. Application Default Credentials (gcloud auth / entorno Google).
    """
    _SCOPES = ["https://www.googleapis.com/auth/drive"]

    if sa_key_path:
        from google.oauth2 import service_account
        sa_path = Path(sa_key_path)
        if not sa_path.exists():
            raise FileNotFoundError(
                f"Clave SA no encontrada: {sa_key_path}. "
                "Revisa GOOGLE_SA_KEY_PATH en .env."
            )
        return service_account.Credentials.from_service_account_file(
            str(sa_path), scopes=_SCOPES
        )

    # ADC: hereda gcloud auth application-default login o entorno Google
    import google.auth
    creds, _ = google.auth.default(scopes=_SCOPES)
    return creds


def _upsert_file(service, path: Path, mime: str, folder_id: str) -> str:
    """Actualiza un archivo existente en la carpeta o crea uno nuevo."""
    # Escapar comillas simples en el nombre para la query
    safe_name = path.name.replace("'", "\\'")
    query = (
        f"name='{safe_name}' "
        f"and '{folder_id}' in parents "
        f"and trashed=false"
    )
    res = (
        service.files()
        .list(
            q=query,
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="allDrives",
        )
        .execute()
    )
    existing = res.get("files", [])
    media = MediaFileUpload(str(path), mimetype=mime, resumable=False)

    if existing:
        file_id: str = existing[0]["id"]
        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()
    else:
        meta = {"name": path.name, "parents": [folder_id]}
        uploaded = (
            service.files()
            .create(body=meta, media_body=media, fields="id", supportsAllDrives=True)
            .execute()
        )
        file_id = uploaded["id"]

    return file_id
