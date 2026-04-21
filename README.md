# CyberNews Scraper

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/dalesos92/cybernews_scraper/blob/main/CyberNews_Scraper.ipynb)

Sistema de producción en Python para recopilar, puntuar y distribuir mensualmente las **4 noticias más relevantes de ciberseguridad** a equipos de desarrollo, AppSec y DevOps.

---

## Arquitectura

```
Fuentes RSS ──┐
              ├──► Recopilador ──► Dedup ──► Ranking ──► Renderers ──► Salidas
Fallback HTML ┘                               ▲                ▼
                                          Storage         SMTP / Teams / Slack
```

| Módulo | Responsabilidad |
|---|---|
| `src/config.py` | Configuración vía `.env` con pydantic-settings |
| `src/models.py` | Modelos Pydantic: `NewsItem`, `RankedNewsItem` |
| `src/sources/rss.py` | Ingestión RSS/Atom con reintentos (tenacity) |
| `src/sources/html.py` | Scraping HTML config-driven como fallback |
| `src/ranking.py` | Scoring por keywords + recencia + diversidad |
| `src/dedup.py` | Dedup por URL normalizada y similitud de título |
| `src/storage.py` | Historial en SQLite (stdlib) |
| `src/renderers.py` | JSON, Markdown y HTML email (Jinja2) |
| `src/sender.py` | SMTP, Teams webhook, Slack webhook |
| `main.py` | Pipeline completo + CLI |

---

## Árbol de archivos

```
scraper/
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── rss.py
│   │   └── html.py
│   ├── ranking.py
│   ├── dedup.py
│   ├── storage.py
│   ├── renderers.py
│   └── sender.py
├── templates/
│   └── email.html.j2
├── tests/
│   ├── __init__.py
│   ├── test_ranking.py
│   └── test_dedup.py
├── output/           ← artefactos generados (JSON, MD, HTML)
├── data/             ← SQLite (cybernews.db)
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## Instalación

```bash
# 1. Clonar o copiar el proyecto
cd scraper

# 2. Crear entorno virtual
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales (SMTP, webhooks, etc.)
```

---

## Ejecución

```bash
# Ejecución completa (recopila, rankea, guarda y envía)
python main.py

# Solo genera archivos, sin guardar ni enviar (modo prueba)
python main.py --dry-run

# Genera y guarda en BD, pero omite notificaciones
python main.py --skip-send

# Especificar directorio de salida
python main.py --dry-run --output-dir /tmp/cybernews
```

### Salidas generadas

| Archivo | Descripción |
|---|---|
| `output/top4_monthly.json` | Estructura completa con scores y metadatos |
| `output/top4_monthly.md` | Informe en Markdown listo para Confluence/Wiki |
| `output/top4_email.html` | Email HTML responsive para envío directo |

---

## Tests

```bash
# Ejecutar todos los tests
pytest tests/ -v

# Con cobertura (requiere pytest-cov)
pip install pytest-cov
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## Cron (Linux / macOS)

Añade esta línea con `crontab -e` para ejecutar el primer día de cada mes a las 08:00:

```cron
0 8 1 * * cd /opt/cybernews-scraper && .venv/bin/python main.py >> logs/cybernews.log 2>&1
```

## Windows Task Scheduler

```powershell
# Crear tarea programada (PowerShell como administrador)
$action = New-ScheduledTaskAction `
    -Execute "C:\opt\scraper\.venv\Scripts\python.exe" `
    -Argument "C:\opt\scraper\main.py" `
    -WorkingDirectory "C:\opt\scraper"

$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At "08:00"

Register-ScheduledTask `
    -TaskName "CyberNewsScraper" `
    -Action $action `
    -Trigger $trigger `
    -RunLevel Highest
```

---

## Configuración de canales de envío

### Email SMTP

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=tu@gmail.com
SMTP_PASSWORD=app_password_aqui
EMAIL_RECIPIENTS=dev@empresa.com,appsec@empresa.com
```

> Para Gmail, genera una [contraseña de aplicación](https://myaccount.google.com/apppasswords) con 2FA activado.

### Microsoft Teams

1. En el canal de Teams → **Conectores** → **Incoming Webhook** → Configurar.
2. Copia la URL generada y pégala en `.env`:

```env
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
```

### Slack

1. Crea una app en <https://api.slack.com/apps> → **Incoming Webhooks**.
2. Añade la URL al `.env`:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
```

---

## Resúmenes en español con IA (opcional)

Si configuras una clave de OpenAI, el sistema generará resúmenes técnicos en español usando `gpt-4o-mini`:

```env
OPENAI_API_KEY=sk-...
```

Instala la dependencia opcional:

```bash
pip install openai
```

---

## Añadir nuevas fuentes

1. Si la fuente tiene RSS, añade una entrada en `build_sources()` en `main.py`:

```python
sources.append(
    RSSSource(
        name="Nueva Fuente",
        rss_url="https://nueva-fuente.com/feed/",
        site_url="https://nueva-fuente.com/",
    )
)
```

2. Si sólo tiene HTML, crea un `HTMLSourceConfig` en `src/sources/html.py` y una función de fábrica.

3. Añade un toggle en `src/config.py` y `.env.example` para habilitarla.

---

## Fuentes configuradas por defecto

| Fuente | Tipo | URL Feed |
|---|---|---|
| The Hacker News | RSS (feedburner) | `feeds.feedburner.com/TheHackersNews` |
| SecurityWeek | RSS (feedburner) | `feeds.feedburner.com/Securityweek` |
| Kaspersky Securelist | RSS nativo | `securelist.com/feed/` |
| WeLiveSecurity ES | RSS nativo | `welivesecurity.com/es/feed/` |
| CyberSecurity News | RSS nativo *(desactivado)* | `cybersecuritynews.com/news/feed/` |

---

## Posibles mejoras futuras

- **FastAPI + scheduler**: exponer endpoint `/run` y usar APScheduler para ejecución interna.
- **Traducción automática sin LLM**: integrar DeepL API o `deep-translator` para resúmenes sin coste de OpenAI.
- **Filtro por idioma**: `langdetect` para separar fuentes en inglés/español.
- **Score por audiencia configurable**: perfiles DevOps, Cloud, Mobile para ajustar pesos.
- **Dashboard web**: Flask/FastAPI + Chart.js para visualizar histórico de keywords por mes.
- **Alertas urgentes**: modo bypass mensual para CVE críticos (CVSS ≥ 9.0) con envío inmediato.
- **Integración CI/CD**: GitHub Actions para ejecutar el scraper en una fechas programadas con `schedule`.
- **Persistencia mejorada**: migrar a PostgreSQL con SQLAlchemy 2.0 para entornos multi-instancia.
