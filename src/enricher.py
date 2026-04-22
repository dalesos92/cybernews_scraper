"""Enriquecedor de noticias: extrae datos estructurados de cada ítem.

Para cada noticia del top-N realiza:
  1. Fetch ligero del artículo original (primeros 3.000 chars de texto visible).
  2. Extracción con regex de: CVEs, cifras numéricas, nombres de organizaciones.
  3. Inferencia por keywords de: afectados, mitigación, insight para devs.
  4. Si OPENAI_API_KEY está configurado, delega todo en GPT-4o-mini.

El proceso es tolerante a fallos: si el fetch del artículo falla, trabaja
sólo con el título + resumen RSS que ya tenemos.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
import unicodedata
from bs4 import BeautifulSoup

from src.config import settings
from src.models import ExecutiveInsight, NewsItem, RankedNewsItem, StructuredInsight

logger = logging.getLogger(__name__)

# ── Regex helpers ─────────────────────────────────────────────────────

_RE_CVE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
_RE_NUMBERS = re.compile(
    r"""
    (?:\$[\d,.]+(?:\s?(?:million|billion|M|B))?   # cantidades monetarias
    |\d+(?:[,.]\d+)?%                               # porcentajes
    |\d[\d,.]*\s?(?:million|billion|thousand|M|B)? # magnitudes
    \s?(?:users?|records?|devices?|systems?|accounts?|victims?|endpoints?)
    |\d+\+?\s?(?:organizations?|companies|countries?|hospitals?|agencies?)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_RE_ORG = re.compile(
    r"""
    (?:
        (?:[A-Z][a-zA-Z0-9&'\-]+(?:\s[A-Z][a-zA-Z0-9&'\-]+){0,3})  # Multi-word org
        (?:\s(?:Inc|Corp|Ltd|LLC|AG|GmbH|SE|PLC|Group|Labs|Security|Networks?)\.?)? 
    )
    """,
    re.VERBOSE,
)

# Palabras que indican recomendación/mitigación en el texto
_MITIGATION_SIGNALS: list[str] = [
    "patch", "update", "upgrade", "fix", "mitigate", "disable", "block",
    "restrict", "revoke", "rotate", "monitor", "apply", "install", "enable",
    "workaround", "advisory", "recommend", "should", "must", "immediately",
    "parchar", "actualizar", "deshabilitar", "revocar", "aplicar",
]

# Mapa keyword → texto de mitigación genérico (si el artículo no aporta uno)
_MITIGATION_BY_KEYWORD: dict[str, str] = {
    "supply chain": (
        "Auditar dependencias de terceros con herramientas como "
        "Dependabot, Snyk o OWASP Dependency-Check. "
        "Fijar versiones exactas en manifiestos de dependencias."
    ),
    "npm": (
        "Revisar `npm audit` y bloquear versiones comprometidas. "
        "Usar lockfiles comprometidos y verificar integridad con checksums."
    ),
    "pypi": (
        "Ejecutar `pip-audit` sobre el entorno. "
        "Considerar un espejo privado (Artifactory, Nexus) con políticas de aprobación."
    ),
    "zero-day": (
        "Aplicar el parche del fabricante en cuanto esté disponible. "
        "Mientras tanto, activar WAF/IDS y monitorear indicadores de compromiso (IOCs)."
    ),
    "zero day": (
        "Aplicar el parche del fabricante en cuanto esté disponible. "
        "Mientras tanto, activar WAF/IDS y monitorear indicadores de compromiso (IOCs)."
    ),
    "ransomware": (
        "Verificar backups offsite actualizados y testar su restauración. "
        "Segmentar la red y aplicar principio de mínimo privilegio."
    ),
    "rce": (
        "Parchear inmediatamente o aislar el sistema afectado. "
        "Revisar logs de acceso en busca de explotación previa."
    ),
    "remote code execution": (
        "Parchear inmediatamente o aislar el sistema afectado. "
        "Revisar logs de acceso en busca de explotación previa."
    ),
    "phishing": (
        "Reforzar MFA en todas las cuentas. "
        "Actualizar simulacros de phishing para el equipo."
    ),
    "api key": (
        "Rotar todas las API keys expuestas inmediatamente. "
        "Implementar gestión de secretos (HashiCorp Vault, AWS Secrets Manager)."
    ),
    "credential": (
        "Rotar credenciales afectadas. Implementar un gestor de secretos centralizado. "
        "Habilitar alerta de uso inusual de credenciales."
    ),
    "github actions": (
        "Auditar workflows de CI/CD. Usar inputs con pin de SHA en actions externas. "
        "Revisar permisos de GITHUB_TOKEN."
    ),
    "ci/cd": (
        "Auditar el pipeline en busca de inyecciones. "
        "Aislar runners y usar artefactos firmados."
    ),
    "container": (
        "Escanear imágenes con Trivy o Grype antes del despliegue. "
        "Aplicar políticas de admisión (OPA/Kyverno)."
    ),
    "kubernetes": (
        "Revisar RBAC, network policies y configuración de secretos. "
        "Usar herramientas como kube-bench para auditar el clúster."
    ),
    "authentication bypass": (
        "Aplicar parche del fabricante. "
        "Forzar re-autenticación de todas las sesiones activas y revisar accesos."
    ),
}

# Mapa keyword → insight para desarrolladores
_INSIGHT_BY_KEYWORD: dict[str, str] = {
    "supply chain": (
        "Los ataques a la cadena de suministro de software son el vector "
        "de mayor crecimiento. Introduce revisión de seguridad en el proceso "
        "de aprobación de nuevas dependencias."
    ),
    "rce": (
        "Una RCE explotable puede comprometer todo el entorno de producción. "
        "Prioriza este tipo de vulnerabilidades en el backlog de seguridad."
    ),
    "remote code execution": (
        "Una RCE explotable puede comprometer todo el entorno de producción. "
        "Prioriza este tipo de vulnerabilidades en el backlog de seguridad."
    ),
    "zero-day": (
        "Las vulnerabilidades zero-day no tienen parche disponible aún. "
        "La detección temprana y el monitoreo de comportamiento son la primera línea."
    ),
    "zero day": (
        "Las vulnerabilidades zero-day no tienen parche disponible aún. "
        "La detección temprana y el monitoreo de comportamiento son la primera línea."
    ),
    "github actions": (
        "Los pipelines de CI/CD son un objetivo de alto valor. "
        "Tratar los workflows de Actions con el mismo rigor que el código de producción."
    ),
    "npm": (
        "El ecosistema npm sigue siendo objetivo frecuente de typosquatting "
        "y paquetes maliciosos. Automatiza el escaneo en cada PR."
    ),
    "api key": (
        "Las API keys nunca deben estar en el código. "
        "Usar variables de entorno y un gestor de secretos desde el día 1."
    ),
    "ransomware": (
        "El ransomware afecta cada vez más a infraestructura cloud y backups. "
        "Validar que los backups son inmutables y están aislados de la red principal."
    ),
    "authentication bypass": (
        "Los bypasses de autenticación suelen deberse a validación incorrecta "
        "del lado servidor. Auditar toda la lógica de autorización en la API."
    ),
    "container": (
        "Imágenes base desactualizadas son una fuente habitual de vulnerabilidades. "
        "Fija versiones de imagen y automatiza su escaneo en el registry."
    ),
}

_DEFAULT_INSIGHT = (
    "Mantenerse actualizado sobre este tipo de amenazas y revisar "
    "si los sistemas o dependencias propias están afectados."
)
_DEFAULT_MITIGATION = (
    "Revisar los boletines oficiales del proveedor y aplicar "
    "actualizaciones de seguridad disponibles. Monitorear IOCs publicados."
)


# ── Limpieza de resúmenes RSS ─────────────────────────────────────────

_RE_HTML_TAGS = re.compile(r"<[^>]+>")
_RE_WORDPRESS_FOOTER = re.compile(
    r"La entrada .+? se public[oó] primero en .+?\.",
    re.IGNORECASE | re.DOTALL,
)
_RE_TRUNCATED_END = re.compile(r"\s*\[[\u2026\.]{1,3}\]\s*$")


def _clean_summary(text: str) -> str:
    """Limpia un resumen RSS: elimina HTML, pie de WordPress y texto truncado."""
    t = _RE_HTML_TAGS.sub("", text)
    t = _RE_WORDPRESS_FOOTER.sub("", t)
    t = _RE_TRUNCATED_END.sub("", t)
    # Eliminar última oración incompleta (sin punto final)
    sentences = re.split(r"(?<=[.!?])\s+", t.strip())
    if len(sentences) > 1 and not sentences[-1].rstrip().endswith((".", "!", "?")):
        sentences = sentences[:-1]
    return " ".join(sentences).strip()


# ── Fetch ligero del artículo ─────────────────────────────────────────


def _fetch_article_text(url: str, max_chars: int = 5000) -> str:
    """Descarga el artículo y extrae el texto visible (primeros N chars)."""
    try:
        with httpx.Client(
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Eliminar scripts, estilos, navegación y elementos cromáticos
        for tag in soup(["script", "style", "nav", "header", "footer",
                          "aside", "noscript", "form", "button", "iframe"]):
            tag.decompose()
        # Eliminar por atributos: menús, migas de pan, sidebars, skip-links
        _JUNK_PATTERNS = (
            "nav", "menu", "breadcrumb", "sidebar", "skip",
            "related", "share", "social", "cookie", "banner",
            "advertisement", "promo", "tags", "comments",
        )
        for attr in ("class", "id", "role"):
            for elem in soup.find_all(attrs={attr: True}):
                val = " ".join(elem.get(attr, [])) if isinstance(elem.get(attr), list) else str(elem.get(attr, ""))
                if any(p in val.lower() for p in _JUNK_PATTERNS):
                    elem.decompose()
        text = soup.get_text(" ", strip=True)
        # Colapsar espacios múltiples
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text[:max_chars]
    except Exception as exc:
        logger.debug("Fetch artículo fallido (%s): %s", url, exc)
        return ""


# ── Extracción de campos estructurados ───────────────────────────────


def _extract_cves(text: str) -> list[str]:
    return list(dict.fromkeys(_RE_CVE.findall(text)))  # únicos, orden preservado


def _extract_figures(text: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in _RE_NUMBERS.findall(text)))


def _extract_orgs(text: str) -> list[str]:
    """Heurística ligera: palabras en CamelCase que no son keywords comunes."""
    _STOP = {
        "The", "This", "That", "These", "Those", "When", "Where", "How",
        "What", "Which", "With", "From", "Into", "Over", "Under", "After",
        "Before", "During", "While", "Through", "Between", "Without",
        "However", "Although", "Because", "Since", "Until", "Unless",
        "According", "Researchers", "Attackers", "Threat", "Security",
        "Vulnerability", "Attack", "Exploit", "Critical", "New", "Old",
        "Recent", "Latest", "First", "Last", "Multiple", "Several",
    }
    tokens = re.findall(r"\b[A-Z][a-zA-Z0-9]+(?:\s[A-Z][a-zA-Z0-9]+)*\b", text)
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        first_word = t.split()[0]
        if first_word not in _STOP and t not in seen and len(t) > 2:
            seen.add(t)
            result.append(t)
    return result[:8]


def _first_mitigation_sentence(text: str) -> str:
    """Busca la primera oración del artículo que contiene señales de mitigación."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for s in sentences:
        slow = s.lower()
        hits = sum(1 for sig in _MITIGATION_SIGNALS if sig in slow)
        if hits >= 2:
            clean = s.strip()
            if len(clean) > 30:
                return clean[:280]
    return ""


def _build_afectados(title: str, full_text: str, orgs: list[str]) -> str:
    title_low = title.lower()
    parts: list[str] = []

    # Inferir tipo de víctima desde el título/keywords
    if any(w in title_low for w in ["user", "customer", "account"]):
        parts.append("usuarios / clientes")
    if any(w in title_low for w in ["enterprise", "organization", "company", "government"]):
        parts.append("organizaciones empresariales")
    if any(w in title_low for w in ["developer", "npm", "pypi", "package", "repo", "github"]):
        parts.append("desarrolladores / ecosistema open source")
    if any(w in title_low for w in ["hospital", "healthcare", "medical"]):
        parts.append("sector sanitario")
    if any(w in title_low for w in ["bank", "financial", "payment"]):
        parts.append("sector financiero")
    if any(w in title_low for w in ["router", "dvr", "iot", "device", "firmware"]):
        parts.append("dispositivos IoT / red")
    if any(w in title_low for w in ["nginx", "apache", "server", "cloud", "kubernetes"]):
        parts.append("infraestructura de servidores / cloud")

    # Añadir orgs detectadas en el texto (máx 4)
    named = [o for o in orgs if len(o) > 3][:4]
    if named:
        parts.append("mencionados: " + ", ".join(named))

    return "; ".join(parts) if parts else "Organizaciones y usuarios no especificados"


def _pick_mitigation(item: NewsItem, article_text: str) -> str:
    # 1. Intentar extraer del artículo
    extracted = _first_mitigation_sentence(article_text)
    if extracted:
        return extracted

    # 2. Fallback por keyword match
    for kw in item.keywords_found:
        if kw in _MITIGATION_BY_KEYWORD:
            return _MITIGATION_BY_KEYWORD[kw]

    return _DEFAULT_MITIGATION


def _pick_insight(item: NewsItem) -> str:
    for kw in item.keywords_found:
        if kw in _INSIGHT_BY_KEYWORD:
            return _INSIGHT_BY_KEYWORD[kw]
    return _DEFAULT_INSIGHT


# ── Enriquecedor principal ────────────────────────────────────────────


def enrich_item(item: NewsItem) -> StructuredInsight:
    """Genera el desglose estructurado para un NewsItem."""
    logger.info("[Enricher] Procesando: %.60s", item.title)

    full_text = _fetch_article_text(item.url)
    combined = f"{item.title}. {item.summary}. {full_text}"

    cves = _extract_cves(combined)
    figures = _extract_figures(combined)
    orgs = _extract_orgs(combined)

    # ── Cifras ────────────────────────────────────────────────────────
    cifras_parts: list[str] = []
    if cves:
        cifras_parts.append(", ".join(cves))
    if figures:
        cifras_parts.extend(figures[:4])
    cifras = "; ".join(cifras_parts) if cifras_parts else "Sin cifras específicas detectadas"

    # ── Qué pasó ──────────────────────────────────────────────────────
    # Tomar hasta 4 oraciones informativas del artículo, descartando
    # fragmentos de navegación, breadcrumbs y frases muy cortas.
    _NAV_FRAGMENTS = (
        "saltar al", "usted está aquí", "inicio /", "ir al contenido",
        "skip to", "you are here", "compartir", "ver más", "leer más",
        "suscrib", "newsletter", "registr", "inicio",
        # Pie de WordPress / syndication
        "se publicó primero en", "was first published", "read more at",
        "continue reading", "leer artículo completo",
        # Índices / tablas de contenido (INCIBE-CERT, boletines)
        "índice", "table of contents", "ir a sección",
    )

    def _looks_like_index(sentence: str) -> bool:
        """Detecta frases que son solo una lista de títulos concatenados
        (ej. índice de boletín con muchos nombres de producto/vuln)."""
        words = sentence.split()
        if len(words) < 12:
            return False
        # Alta proporción de palabras capitalizadas → lista de títulos
        cap = sum(1 for w in words if w and w[0].isupper() and len(w) > 1)
        return (cap / len(words)) > 0.50

    source_text = full_text or item.summary
    raw_sentences = re.split(r"(?<=[.!?])\s+", source_text.strip())
    good: list[str] = []
    for s in raw_sentences:
        s_clean = s.strip()
        # Normalizar a NFC para que acentos compuestos (NFD del RSS) coincidan
        # con los literales del código fuente (NFC). P. ej. Índice en RSS es NFD.
        s_low = unicodedata.normalize("NFC", s_clean.lower())
        # Saltar si es muy corto, es navegación o tiene demasiadas barras
        if len(s_clean) < 40:
            continue
        if any(frag in s_low for frag in _NAV_FRAGMENTS):
            continue
        if s_clean.count("/") > 3:
            continue
        # Descartar frases truncadas (terminan con […] o similar)
        if re.search(r"\[[\u2026\.]{1,3}\]$", s_clean):
            continue
        # Descartar listas de títulos concatenados (índices de boletín)
        if _looks_like_index(s_clean):
            continue
        good.append(s_clean)
        if len(good) == 4:
            break
    que_paso = " ".join(good).strip()
    # Si termina a mitad de oración (por corte de 3000 chars), truncar en el
    # último signo de puntuación completo antes del límite de 800 chars.
    que_paso = que_paso[:800]
    if que_paso and que_paso[-1] not in ".!?":
        last_punct = max(que_paso.rfind("."), que_paso.rfind("!"), que_paso.rfind("?"))
        if last_punct > 0:
            que_paso = que_paso[: last_punct + 1]
    if not que_paso:
        # No se encontraron oraciones informativas (p. ej. RSS es solo un índice).
        # Construir descripción sintética a partir de los metadatos disponibles.
        synth: list[str] = [item.title]
        if cves:
            synth.append("CVEs identificados: " + ", ".join(cves[:4]))
        if item.keywords_found:
            synth.append("Tipos de vulnerabilidad: " + ", ".join(item.keywords_found[:3]))
        synth.append(
            f"Publicado por {item.source_name} "
            f"el {item.published_at.strftime('%d/%m/%Y')}."
        )
        que_paso = ". ".join(synth)

    # ── Afectados ─────────────────────────────────────────────────────
    afectados = _build_afectados(item.title, combined, orgs)

    # ── Mitigación ────────────────────────────────────────────────────
    mitigacion = _pick_mitigation(item, full_text)

    # ── Insight para devs ─────────────────────────────────────────────
    insight_dev = _pick_insight(item)

    return StructuredInsight(
        afectados=afectados,
        cifras=cifras,
        que_paso=que_paso,
        mitigacion=mitigacion,
        insight_dev=insight_dev,
    )


def enrich_ranked(ranked: list[RankedNewsItem]) -> None:
    """Enriquece in-place todos los ítems del ranking.

    Si OPENAI_API_KEY está configurado, usa GPT-4o-mini para mayor calidad.
    """
    if settings.openai_api_key:
        try:
            _openai_enrich(ranked)
            return
        except Exception as exc:
            logger.warning(
                "OpenAI no disponible (%s). Usando extractor heurístico.", exc
            )

    for r in ranked:
        try:
            r.item.insight = enrich_item(r.item)
        except Exception as exc:
            logger.error(
                "[Enricher] Error en '%s': %s", r.item.title[:50], exc
            )
            r.item.insight = StructuredInsight(
                que_paso=r.item.summary[:200],
                mitigacion=_DEFAULT_MITIGATION,
                insight_dev=_DEFAULT_INSIGHT,
            )


# ── Ruta OpenAI (opcional) ────────────────────────────────────────────


def _openai_enrich(ranked: list[RankedNewsItem]) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)

    for r in ranked:
        item = r.item
        article_text = _fetch_article_text(item.url)

        prompt = f"""Eres un analista de ciberseguridad senior. Analiza esta noticia y devuelve EXACTAMENTE este JSON (sin texto adicional):

{{
  "afectados": "Empresas, sistemas, usuarios o sectores afectados (1-2 líneas)",
  "cifras": "CVEs, números, estadísticas relevantes del incidente",
  "que_paso": "Qué ocurrió exactamente, en 2-3 líneas en español técnico",
  "mitigacion": "Acciones concretas que deben tomar los equipos técnicos para mitigar o protegerse",
  "insight_dev": "Lección o takeaway clave para equipos de desarrollo, AppSec o DevOps (1-2 líneas)"
}}

Título: {item.title}
Fuente: {item.source_name}
Fecha: {item.published_at.strftime('%d/%m/%Y')}
Resumen: {item.summary[:400]}
Texto del artículo: {article_text[:2000]}"""

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=450,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        import json
        data = json.loads(resp.choices[0].message.content)
        item.insight = StructuredInsight(**data)
        logger.info("[OpenAI Enricher] ✓ %s", item.title[:50])


# ── Enriquecimiento ejecutivo (alta dirección) ────────────────────────

# Orden de prioridad: el primer match gana el nivel de riesgo
_EXECUTIVE_RISK_LEVELS: list[tuple[str, str, int]] = [
    # (keyword, nivel_riesgo, porcentaje_afectacion)
    ("ransomware",              "CRÍTICO", 90),
    ("remote code execution",   "CRÍTICO", 88),
    ("rce",                     "CRÍTICO", 88),
    ("supply chain attack",     "CRÍTICO", 85),
    ("zero-day",                "CRÍTICO", 83),
    ("zero day",                "CRÍTICO", 83),
    ("0-day",                   "CRÍTICO", 83),
    ("malicious package",       "CRÍTICO", 80),
    ("dependency confusion",    "CRÍTICO", 80),
    ("backdoor",                "ALTO",    72),
    ("data breach",             "ALTO",    70),
    ("authentication bypass",   "ALTO",    68),
    ("privilege escalation",    "ALTO",    67),
    ("critical vulnerability",  "ALTO",    65),
    ("supply chain",            "ALTO",    65),
    ("unauthenticated",         "ALTO",    63),
    ("apt",                     "ALTO",    62),
    ("breach",                  "ALTO",    60),
    ("exploit",                 "ALTO",    58),
    ("injection",               "MEDIO",   48),
    ("phishing",                "MEDIO",   45),
    ("malware",                 "MEDIO",   43),
    ("vulnerability",           "MEDIO",   40),
    ("api key",                 "MEDIO",   38),
    ("credential",              "MEDIO",   38),
    ("leak",                    "MEDIO",   35),
    ("exposed",                 "MEDIO",   33),
    ("patch",                   "BAJO",    20),
    ("update",                  "BAJO",    15),
    ("advisory",                "BAJO",    12),
]

# keyword → segmento de negocio (primer match gana)
_EXECUTIVE_SEGMENT: list[tuple[str, str]] = [
    ("ransomware",            "Continuidad Operativa"),
    ("remote code execution", "Continuidad Operativa"),
    ("rce",                   "Continuidad Operativa"),
    ("supply chain attack",   "Infraestructura TI"),
    ("supply chain",          "Infraestructura TI"),
    ("zero-day",              "Infraestructura TI"),
    ("zero day",              "Infraestructura TI"),
    ("0-day",                 "Infraestructura TI"),
    ("malicious package",     "Infraestructura TI"),
    ("dependency confusion",  "Infraestructura TI"),
    ("backdoor",              "Infraestructura TI"),
    ("data breach",           "Protección de Datos"),
    ("breach",                "Protección de Datos"),
    ("leak",                  "Protección de Datos"),
    ("exposed",               "Protección de Datos"),
    ("credential",            "Protección de Datos"),
    ("api key",               "Protección de Datos"),
    ("phishing",              "Fraude Financiero"),
    ("authentication bypass", "Gestión de Accesos"),
    ("privilege escalation",  "Gestión de Accesos"),
    ("vulnerability",         "Infraestructura TI"),
    ("malware",               "Infraestructura TI"),
    ("inject",                "Infraestructura TI"),
    ("apt",                   "Ciberespionaje"),
    ("patch",                 "Infraestructura TI"),
]

# nivel_riesgo → texto de impacto de negocio (plantilla base)
_IMPACTO_NEGOCIO: dict[str, str] = {
    "CRÍTICO": (
        "Amenaza de primer orden con capacidad de paralizar operaciones. "
        "Puede comprometer la disponibilidad de servicios críticos, "
        "bloquear el acceso a sistemas internos y exigir recursos de respuesta inmediata. "
        "Requiere activación del plan de continuidad de negocio."
    ),
    "ALTO": (
        "Riesgo significativo para la integridad de la información o la disponibilidad "
        "de servicios. Puede derivar en pérdida de datos sensibles, interrupción "
        "temporal de operaciones o exposición no autorizada de información confidencial."
    ),
    "MEDIO": (
        "Incidente de relevancia moderada que, si no se gestiona adecuadamente, "
        "puede escalar. No compromete operaciones de forma inmediata, pero representa "
        "una ventana de oportunidad para actores maliciosos si no se cierra a tiempo."
    ),
    "BAJO": (
        "Evento informativo o de bajo riesgo directo. "
        "No requiere acción urgente, pero es recomendable hacer seguimiento "
        "para anticipar posibles amenazas futuras relacionadas."
    ),
}

# nivel_riesgo → riesgo reputacional
_RIESGO_REPUTACIONAL: dict[str, str] = {
    "CRÍTICO": (
        "Exposición pública elevada. Riesgo severo de daño a la imagen institucional, "
        "pérdida de confianza de clientes y cobertura mediática negativa."
    ),
    "ALTO": (
        "Posible cobertura en medios especializados. Puede generar desconfianza "
        "entre clientes y socios si se conoce externamente."
    ),
    "MEDIO": (
        "Impacto reputacional contenido si la situación se gestiona y comunica "
        "de forma proactiva y transparente."
    ),
    "BAJO": (
        "Riesgo reputacional bajo. Seguimiento preventivo recomendado."
    ),
}

# nivel_riesgo → pérdida potencial estimada
_PERDIDA_POTENCIAL: dict[str, str] = {
    "CRÍTICO": (
        "Pérdida potencial: millones de euros "
        "(paralización operativa, posibles rescates, sanciones regulatorias, "
        "litigios y costes de respuesta a incidente)."
    ),
    "ALTO": (
        "Pérdida potencial: cientos de miles de euros "
        "(respuesta al incidente, compensaciones a clientes, "
        "pérdida de negocio y posibles multas regulatorias)."
    ),
    "MEDIO": (
        "Pérdida potencial: decenas de miles de euros "
        "(remediación, tiempo de equipos especializados, "
        "posibles sanciones menores)."
    ),
    "BAJO": (
        "Impacto económico directo bajo si se atiende en los plazos habituales."
    ),
}

# nivel_riesgo → acción directiva recomendada
_ACCION_DIRECTIVA: dict[str, str] = {
    "CRÍTICO": (
        "Convocar al Comité de Crisis de Ciberseguridad. Activar el Plan de "
        "Continuidad de Negocio. Designar responsable ejecutivo del incidente. "
        "Evaluar notificación regulatoria y a clientes en menos de 24 horas."
    ),
    "ALTO": (
        "Informar al Comité de Dirección y al CISO. Solicitar evaluación urgente "
        "del impacto sobre los activos propios. Definir plan de remediación "
        "con fechas comprometidas en los próximos 3-5 días."
    ),
    "MEDIO": (
        "Trasladar al equipo de Seguridad para análisis de afectación. "
        "Incluir en el próximo ciclo de revisión de riesgos. "
        "Asegurar que los controles preventivos están activos."
    ),
    "BAJO": (
        "Registrar en el inventario de amenazas. Revisar en el informe mensual "
        "de ciberseguridad. No requiere acción inmediata."
    ),
}


def build_executive_insight(item: NewsItem) -> ExecutiveInsight:
    """Genera el análisis ejecutivo no técnico para un NewsItem.

    La lógica es puramente heurística (sin LLM): mapea las keywords
    ya detectadas a niveles de riesgo, segmentos de negocio y textos
    ejecutivos predefinidos.
    """
    kws = set(item.keywords_found)
    text_low = f"{item.title} {item.summary}".lower()

    # ── Nivel de riesgo y % de afectación ─────────────────────────────
    nivel_riesgo = "BAJO"
    porcentaje = 12
    for kw, nivel, pct in _EXECUTIVE_RISK_LEVELS:
        if kw in kws or kw in text_low:
            nivel_riesgo = nivel
            porcentaje = pct
            break

    # ── Segmento de negocio ───────────────────────────────────────────
    segmento = "Infraestructura TI"
    for kw, seg in _EXECUTIVE_SEGMENT:
        if kw in kws or kw in text_low:
            segmento = seg
            break

    return ExecutiveInsight(
        nivel_riesgo=nivel_riesgo,
        porcentaje_afectacion=porcentaje,
        segmento=segmento,
        impacto_negocio=_IMPACTO_NEGOCIO[nivel_riesgo],
        riesgo_reputacional=_RIESGO_REPUTACIONAL[nivel_riesgo],
        perdida_potencial=_PERDIDA_POTENCIAL[nivel_riesgo],
        accion_directiva=_ACCION_DIRECTIVA[nivel_riesgo],
    )


def enrich_executive(ranked: list[RankedNewsItem]) -> None:
    """Genera el análisis ejecutivo in-place para todos los ítems del ranking."""
    for r in ranked:
        try:
            r.item.executive_insight = build_executive_insight(r.item)
        except Exception as exc:
            logger.error(
                "[Executive Enricher] Error en '%s': %s", r.item.title[:50], exc
            )
            r.item.executive_insight = ExecutiveInsight(
                nivel_riesgo="MEDIO",
                impacto_negocio=r.item.summary[:200],
            )
