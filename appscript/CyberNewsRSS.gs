// =============================================================================
// CyberNews RSS Fetcher — Google Apps Script
// =============================================================================
// Descarga feeds RSS de ciberseguridad en español, rankea las noticias,
// genera un Google Doc con el JSON listo para pegar en el Gem de Gemini
// y notifica al operador por email.
//
// Setup (ejecutar una sola vez desde el editor de Apps Script):
//   1. Edita RSS_CONFIG con tus valores reales.
//   2. Ejecuta setupMonthlyRSSTrigger() para el trigger automático.
//   3. Para prueba manual: ejecuta runMonthlyCyberNewsReport().
// =============================================================================

var RSS_CONFIG = {

  // ── Fuentes RSS ─────────────────────────────────────────────────────────────
  SOURCES: [
    { name: "CyberSecurity News ES",  url: "https://cybersecuritynews.es/feed/",                   enabled: true  },
    { name: "Hispasec Una-al-Día",    url: "https://unaaldia.hispasec.com/feed/",                   enabled: true  },
    { name: "Revista Ciberseguridad", url: "https://www.revistaciberseguridad.com/feed/",            enabled: true  },
    { name: "Segu-Info",              url: "https://www.segu-info.com.ar/rss/seguinfo.rss",          enabled: true  },
    { name: "Kaspersky LATAM Blog",   url: "https://latam.kaspersky.com/blog/feed/",                 enabled: true  },
    { name: "WeLiveSecurity ES",      url: "https://www.welivesecurity.com/es/rss/feed/",            enabled: false },
    { name: "INCIBE CERT",            url: "https://www.incibe.es/rss.xml",                          enabled: false }
  ],

  // ── Parámetros de selección ──────────────────────────────────────────────────
  TOP_N:                4,   // noticias que van al informe ejecutivo
  LOOKBACK_DAYS:        30,  // antigüedad máxima en días
  MAX_PER_SOURCE:       20,  // máximo de ítems a leer por fuente
  MAX_DIVERSITY_SOURCE: 2,   // máximo de noticias del mismo origen en el top

  // ── Operador ─────────────────────────────────────────────────────────────────
  // Email que recibe el aviso con el link al Doc para Gemini
  OPERATOR_EMAIL: "REEMPLAZAR_CON_TU_EMAIL",

  // ── Drive ────────────────────────────────────────────────────────────────────
  // ID de carpeta Drive donde guardar los Docs generados (dejar "" para My Drive)
  DOC_FOLDER_ID: "",

  // ── URLs de integración ──────────────────────────────────────────────────────
  // URL del Gem de Gemini (gemini.google.com > Gems > tu gem > Compartir)
  GEM_URL:    "https://gemini.google.com/gem/REEMPLAZAR_CON_ID_GEM",

  // URL del Web App de Apps Script (de CyberNewsMailer, ya desplegado)
  WEBAPP_URL: "REEMPLAZAR_CON_URL_WEBAPP"
};

// ── Pesos de keywords para ranking (replicado de Python) ─────────────────────
var _KW = {
  "remote code execution": 6.0, "rce": 6.0,
  "zero-day": 5.5, "zero day": 5.5, "0-day": 5.5,
  "supply chain attack": 6.0, "supply chain": 5.0, "supply-chain": 5.0,
  "malicious package": 5.5, "dependency confusion": 5.5, "typosquatting": 4.5,
  "ransomware": 4.5, "critical vulnerability": 4.5, "critical": 3.5,
  "backdoor": 4.5, "privilege escalation": 4.5, "authentication bypass": 4.5,
  "unauthenticated": 4.0, "exploit": 4.0,
  "data breach": 4.0, "breach": 3.5, "apt": 3.5, "cve-": 3.5,
  "vulnerability": 3.0, "malware": 3.0, "injection": 3.0,
  "sql injection": 3.5, "command injection": 4.0, "bypass": 3.0,
  "phishing": 2.5, "leak": 2.5, "exposed": 2.5,
  "api key": 3.5, "credential": 3.0, "hardcoded": 3.5,
  "github actions": 4.5, "ci/cd": 4.0, "container": 3.0,
  "kubernetes": 3.5, "docker": 3.0,
  "aws": 2.5, "azure": 2.5, "gcp": 2.5, "cloud": 2.0,
  "patch": 2.0, "advisory": 2.0, "update": 1.5,
  // Español
  "vulnerabilidad": 3.0, "crítica": 3.5, "critica": 3.5, "crítico": 3.5,
  "ataque": 2.5, "brecha": 3.5, "filtración": 3.5, "robo de datos": 4.0,
  "código malicioso": 4.0, "amenaza": 2.0, "ciberataque": 3.5
};
var _MAX_KW_SCORE  = 20.0;
var _RECENCY_MAX   = 10.0;
var _PROMO_WORDS   = ["[webinar]","[sponsored]","[free event]","[partner]","register now"];

// =============================================================================
// PUNTO DE ENTRADA PRINCIPAL
// =============================================================================

function runMonthlyCyberNewsReport() {
  Logger.log("=== CyberNews RSS Report iniciado ===");

  var allItems = _fetchAllSources();
  Logger.log("Total recopiladas: " + allItems.length);

  if (allItems.length === 0) {
    Logger.log("Sin noticias. Verifica las fuentes RSS.");
    return;
  }

  var deduped  = _deduplicateItems(allItems);
  Logger.log("Tras deduplicación: " + deduped.length);

  var scored   = _scoreAndFilterItems(deduped);
  Logger.log("Dentro del periodo (" + RSS_CONFIG.LOOKBACK_DAYS + " días): " + scored.length);

  if (scored.length === 0) {
    Logger.log("Sin noticias en el período. Verifica LOOKBACK_DAYS.");
    return;
  }

  var topItems = _selectTopN(scored, RSS_CONFIG.TOP_N);
  Logger.log("Top-" + RSS_CONFIG.TOP_N + " seleccionados");

  var docUrl = _buildPromptDoc(topItems, scored);
  Logger.log("Doc generado: " + docUrl);

  _notifyOperator(docUrl, topItems, scored.length);
  Logger.log("=== Completado ===");
}

// =============================================================================
// DESCARGA DE FEEDS RSS
// =============================================================================

function _fetchAllSources() {
  var all     = [];
  var sources = RSS_CONFIG.SOURCES.filter(function(s) { return s.enabled; });

  sources.forEach(function(src) {
    try {
      var items = _fetchRSSSource(src);
      Logger.log(src.name + ": " + items.length + " ítems");
      all = all.concat(items);
    } catch (e) {
      Logger.log("ERROR en " + src.name + ": " + e.message);
    }
  });
  return all;
}

function _fetchRSSSource(src) {
  var resp = UrlFetchApp.fetch(src.url, {
    method:             "get",
    muteHttpExceptions: true,
    headers:            { "User-Agent": "Mozilla/5.0 (compatible; CyberNewsBot/2.0; +https://bbva.com)" },
    followRedirects:    true
  });

  if (resp.getResponseCode() !== 200) {
    throw new Error("HTTP " + resp.getResponseCode() + " en " + src.url);
  }

  var text = resp.getContentText("utf-8");
  return _parseRSSXml(text, src.name);
}

function _parseRSSXml(xml, srcName) {
  var items = [];
  try {
    var doc  = XmlService.parse(xml);
    var root = doc.getRootElement();

    // ── RSS 2.0 ──────────────────────────────────────────────────────────────
    if (root.getName() === "rss") {
      var channel = root.getChild("channel");
      if (!channel) return items;

      var contentNS = XmlService.getNamespace("content",
                        "http://purl.org/rss/1.0/modules/content/");

      channel.getChildren("item").slice(0, RSS_CONFIG.MAX_PER_SOURCE).forEach(function(el) {
        var title   = _childVal(el, "title",       "");
        var link    = _childVal(el, "link",        "");
        var descRaw = _childVal(el, "description", "");
        var pubDate = _childVal(el, "pubDate",     "");

        // Preferir content:encoded si existe
        try {
          var enc = el.getChild("encoded", contentNS);
          if (enc && enc.getValue()) descRaw = enc.getValue();
        } catch(e2) {}

        var desc = _stripHtml(descRaw).substring(0, 600);
        if (title && link) {
          items.push({ title: title.trim(), url: link.trim(),
                       source_name: srcName, published_at: _parseDate(pubDate),
                       summary: desc.trim(), score: 0, keywords: [] });
        }
      });

    // ── Atom ─────────────────────────────────────────────────────────────────
    } else if (root.getName() === "feed") {
      var ns = root.getNamespace();

      root.getChildren("entry", ns).slice(0, RSS_CONFIG.MAX_PER_SOURCE).forEach(function(entry) {
        var title = ""; var link = ""; var summary = ""; var updated = "";

        var tEl = entry.getChild("title",   ns); if (tEl) title   = tEl.getValue();
        var lEl = entry.getChild("link",    ns); if (lEl) link    = lEl.getAttributeValue("href") || lEl.getValue();
        var sEl = entry.getChild("summary", ns); if (sEl) summary = _stripHtml(sEl.getValue()).substring(0, 600);
        var uEl = entry.getChild("updated", ns); if (uEl) updated = uEl.getValue();

        if (title && link) {
          items.push({ title: title.trim(), url: link.trim(),
                       source_name: srcName, published_at: _parseDate(updated),
                       summary: summary.trim(), score: 0, keywords: [] });
        }
      });
    }

  } catch (e) {
    Logger.log(srcName + " — fallo XmlService (" + e.message + "), usando regex fallback");
    items = _parseRSSFallback(xml, srcName);
  }
  return items;
}

function _parseRSSFallback(text, srcName) {
  var items = [];
  var re    = /<item[^>]*>([\s\S]*?)<\/item>/gi;
  var m; var count = 0;
  while ((m = re.exec(text)) !== null && count < RSS_CONFIG.MAX_PER_SOURCE) {
    var block   = m[1];
    var title   = _extractTag(block, "title");
    var link    = _extractTag(block, "link")  || _extractTag(block, "guid");
    var desc    = _stripHtml(_extractTag(block, "description")).substring(0, 600);
    var pubDate = _extractTag(block, "pubDate");
    if (title && link) {
      items.push({ title: title, url: link, source_name: srcName,
                   published_at: _parseDate(pubDate), summary: desc,
                   score: 0, keywords: [] });
      count++;
    }
  }
  return items;
}

// =============================================================================
// SCORING Y SELECCIÓN
// =============================================================================

function _scoreAndFilterItems(items) {
  var cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - RSS_CONFIG.LOOKBACK_DAYS);

  return items
    .filter(function(it) { return it.published_at > cutoff && it.published_at.getTime() > 0; })
    .map(function(it) {
      var r     = _scoreItem(it.title, it.summary);
      it.score  = r.score;
      it.keywords = r.keywords;
      return it;
    })
    .sort(function(a, b) { return b.score - a.score; });
}

function _scoreItem(title, summary) {
  var text  = (title + " " + summary).toLowerCase();
  var total = 0;
  var found = [];

  for (var kw in _KW) {
    if (_KW.hasOwnProperty(kw) && text.indexOf(kw) !== -1) {
      total += _KW[kw];
      found.push(kw);
    }
  }

  // Recency bonus: items dentro del lookback_days reciben hasta 10 pts adicionales
  // (aquí no se puede calcular porque no tenemos la fecha de referencia,
  //  pero el filtro previo ya garantiza que todos están en el período)
  return { score: Math.min(total, _MAX_KW_SCORE), keywords: found };
}

function _deduplicateItems(items) {
  var seen  = {};
  var clean = [];
  items.forEach(function(it) {
    var key = _normalizeUrl(it.url);
    if (!seen[key]) { seen[key] = true; clean.push(it); }
  });
  return clean;
}

function _selectTopN(scored, n) {
  // Filtrar contenido promocional
  var pool = scored.filter(function(it) {
    var tl = it.title.toLowerCase();
    return !_PROMO_WORDS.some(function(p) { return tl.indexOf(p) !== -1; });
  });

  var selected     = [];
  var sourceCounts = {};

  while (selected.length < n && pool.length > 0) {
    var bestIdx = -1; var bestAdj = -Infinity;

    pool.forEach(function(it, idx) {
      var penalty = (sourceCounts[it.source_name] || 0) >= RSS_CONFIG.MAX_DIVERSITY_SOURCE ? 8.0 : 0;
      var adj     = it.score - penalty;
      if (adj > bestAdj) { bestAdj = adj; bestIdx = idx; }
    });

    if (bestIdx === -1) break;

    var chosen  = pool.splice(bestIdx, 1)[0];
    chosen.rank = selected.length + 1;
    selected.push(chosen);
    sourceCounts[chosen.source_name] = (sourceCounts[chosen.source_name] || 0) + 1;
  }

  return selected;
}

// =============================================================================
// GENERACIÓN DEL GOOGLE DOC CON EL PROMPT PARA GEMINI
// =============================================================================

function _buildPromptDoc(topItems, allScored) {
  var now    = new Date();
  var MONTHS = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
  var period  = MONTHS[now.getMonth()] + " " + now.getFullYear();
  var dateStr = Utilities.formatDate(now, Session.getScriptTimeZone(), "dd/MM/yyyy 'a las' HH:mm");

  // ── JSON de entrada para el Gem ──────────────────────────────────────────
  var enabledSources = RSS_CONFIG.SOURCES
    .filter(function(s) { return s.enabled; })
    .map(function(s) { return s.name; });

  var gemInput = {
    periodo:                    period,
    generado_en:                now.toISOString(),
    fuentes_consultadas:        enabledSources,
    total_noticias_recopiladas: allScored.length,
    noticias: topItems.map(function(it) {
      return {
        rank:               it.rank,
        titulo:             it.title,
        fuente:             it.source_name,
        fecha:              Utilities.formatDate(it.published_at, "UTC", "yyyy-MM-dd"),
        url:                it.url,
        resumen:            it.summary,
        keywords_detectados: it.keywords.slice(0, 12)
      };
    })
  };

  var gemInputJson = JSON.stringify(gemInput, null, 2);

  // ── Crear el Google Doc ──────────────────────────────────────────────────
  var docTitle = "CyberNews BBVA — Prompt Gemini — " + period;
  var doc      = DocumentApp.create(docTitle);
  var body     = doc.getBody();
  body.clear();

  // Título principal
  body.appendParagraph("CyberNews BBVA — Informe " + period)
      .setHeading(DocumentApp.ParagraphHeading.HEADING1);

  body.appendParagraph("Generado automáticamente el " + dateStr)
      .setHeading(DocumentApp.ParagraphHeading.NORMAL);

  body.appendHorizontalRule();

  // ── Instrucciones ────────────────────────────────────────────────────────
  body.appendParagraph("INSTRUCCIONES — Completa estos 4 pasos (≈ 3 minutos)")
      .setHeading(DocumentApp.ParagraphHeading.HEADING2);

  var instrLines = [
    "PASO 1 → Abre el Gem de Gemini en este link:",
    "         " + RSS_CONFIG.GEM_URL,
    "",
    "PASO 2 → Copia el bloque JSON de la sección «DATOS PARA GEMINI» (más abajo).",
    "         Pégalo en el chat del Gem y espera la respuesta.",
    "",
    "PASO 3 → Cuando Gemini responda, COPIA TODO el JSON de su respuesta.",
    "         (Empieza en { y termina en el último })",
    "",
    "PASO 4 → Abre la página de envío del comunicado:",
    "         " + RSS_CONFIG.WEBAPP_URL + "?page=submit",
    "         Pega el JSON de Gemini y haz clic en «Enviar comunicado».",
    "         El sistema enviará el informe ejecutivo automáticamente."
  ];
  body.appendParagraph(instrLines.join("\n"));

  body.appendHorizontalRule();

  // ── JSON para el Gem ─────────────────────────────────────────────────────
  body.appendParagraph("DATOS PARA GEMINI — Copiar TODO el bloque de texto a continuación:")
      .setHeading(DocumentApp.ParagraphHeading.HEADING2);

  body.appendParagraph("(Seleccionar desde el primer { hasta el último } y copiar)")
      .setItalic(true);

  // JSON como texto monoespaciado
  var jsonPara = body.appendParagraph(gemInputJson);
  jsonPara.setAttributes({
    [DocumentApp.Attribute.FONT_FAMILY]:      "Courier New",
    [DocumentApp.Attribute.FONT_SIZE]:        8,
    [DocumentApp.Attribute.BACKGROUND_COLOR]: "#f4f4f4",
    [DocumentApp.Attribute.FOREGROUND_COLOR]: "#1a1a1a"
  });

  body.appendHorizontalRule();

  // ── Resumen del período ──────────────────────────────────────────────────
  body.appendParagraph("RESUMEN DEL PERÍODO")
      .setHeading(DocumentApp.ParagraphHeading.HEADING2);

  var summaryLines = [
    "Período analizado  : " + period,
    "Fuentes activas    : " + enabledSources.join(", "),
    "Total procesadas   : " + allScored.length + " noticias (dentro de los últimos " + RSS_CONFIG.LOOKBACK_DAYS + " días)",
    "Noticias en Top-" + RSS_CONFIG.TOP_N + " : " + topItems.length,
    "",
    "Selección:"
  ];
  topItems.forEach(function(it) {
    summaryLines.push("  #" + it.rank + " [" + it.score.toFixed(1) + " pts] [" + it.source_name + "] " + it.title);
  });

  body.appendParagraph(summaryLines.join("\n"));

  doc.saveAndClose();

  // Mover a carpeta Drive si está configurada
  var docFile = DriveApp.getFileById(doc.getId());
  if (RSS_CONFIG.DOC_FOLDER_ID) {
    try {
      DriveApp.getFolderById(RSS_CONFIG.DOC_FOLDER_ID).addFile(docFile);
      DriveApp.getRootFolder().removeFile(docFile);
    } catch(e) {
      Logger.log("No se pudo mover el Doc: " + e.message);
    }
  }

  return doc.getUrl();
}

// =============================================================================
// NOTIFICACIÓN AL OPERADOR
// =============================================================================

function _notifyOperator(docUrl, topItems, totalCount) {
  if (!RSS_CONFIG.OPERATOR_EMAIL) return;

  var now    = new Date();
  var MONTHS = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
  var period = MONTHS[now.getMonth()] + " " + now.getFullYear();

  var topListHtml = topItems.map(function(it) {
    return '<li style="margin-bottom:6px;">' +
           '<strong>#' + it.rank + '</strong> &nbsp;[' + it.score.toFixed(1) + ' pts]&nbsp; ' +
           '<a href="' + it.url + '" style="color:#001490;text-decoration:none;">' + it.title + '</a>' +
           '<br><span style="color:#6B8BA4;font-size:11px;">' + it.source_name + '</span>' +
           '</li>';
  }).join("");

  var htmlBody =
    '<div style="font-family:Arial,Helvetica,sans-serif;max-width:620px;margin:0 auto;">' +
    // Header
    '<table width="100%" cellpadding="0" cellspacing="0">' +
      '<tr><td style="height:6px;background:#001490;width:60%;"></td>' +
           '<td style="height:6px;background:#84C8FC;width:40%;"></td></tr>' +
    '</table>' +
    '<div style="background:#001490;padding:22px 28px;">' +
      '<p style="color:#84C8FC;font-size:11px;margin:0 0 4px;text-transform:uppercase;letter-spacing:1px;">CyberNews BBVA</p>' +
      '<h2 style="color:#ffffff;margin:0;font-size:20px;font-weight:bold;">Datos listos para Gemini</h2>' +
      '<p style="color:#84C8FC;margin:6px 0 0;font-size:13px;">' + period + '</p>' +
    '</div>' +
    // Body
    '<div style="padding:28px;background:#F8FAFC;border:1px solid #D0DCE8;">' +
      '<p style="color:#1a1a2e;font-size:14px;margin:0 0 16px;">' +
        'Se recopilaron y rankearon las noticias del mes. ' +
        '<strong>' + topItems.length + ' noticias</strong> seleccionadas para el informe ejecutivo ' +
        '(de ' + totalCount + ' procesadas).' +
      '</p>' +
      // Pasos
      '<div style="background:#EEF3F9;border-radius:6px;padding:16px 20px;margin-bottom:20px;">' +
        '<p style="color:#001490;font-size:12px;font-weight:bold;text-transform:uppercase;margin:0 0 10px;">Qué hacer (≈ 3 min)</p>' +
        '<ol style="color:#1a1a2e;font-size:13px;margin:0;padding-left:20px;line-height:2;">' +
          '<li>Abre el Doc con el prompt de Gemini (botón azul)</li>' +
          '<li>Pega el JSON en el <a href="' + RSS_CONFIG.GEM_URL + '" style="color:#001490;">Gem de Gemini</a></li>' +
          '<li>Copia la respuesta de Gemini</li>' +
          '<li>Pega en la <a href="' + RSS_CONFIG.WEBAPP_URL + '?page=submit" style="color:#001490;">página de envío</a> y haz clic en Enviar</li>' +
        '</ol>' +
      '</div>' +
      // Selección
      '<p style="color:#6B8BA4;font-size:11px;font-weight:bold;text-transform:uppercase;margin:0 0 8px;">Top-' + RSS_CONFIG.TOP_N + ' seleccionado</p>' +
      '<ul style="padding-left:0;list-style:none;margin:0 0 24px;">' + topListHtml + '</ul>' +
      // Botones
      '<table cellpadding="0" cellspacing="0"><tr>' +
        '<td style="padding-right:12px;">' +
          '<a href="' + docUrl + '" style="display:inline-block;background:#001490;color:#ffffff;' +
          'padding:12px 22px;text-decoration:none;border-radius:4px;font-size:14px;font-weight:bold;">' +
          '📄 Abrir Doc con instrucciones</a>' +
        '</td>' +
        '<td>' +
          '<a href="' + RSS_CONFIG.WEBAPP_URL + '?page=submit" style="display:inline-block;background:#F0F5FC;color:#001490;' +
          'padding:12px 22px;text-decoration:none;border-radius:4px;font-size:14px;border:1px solid #D0DCE8;">' +
          '📤 Página de envío</a>' +
        '</td>' +
      '</tr></table>' +
    '</div>' +
    // Footer
    '<div style="padding:12px 28px;background:#F0F5FC;border:1px solid #D0DCE8;border-top:none;">' +
      '<p style="color:#6B8BA4;font-size:11px;margin:0;text-align:center;">' +
        'CyberNews BBVA · Generado automáticamente · ' + Utilities.formatDate(now, Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm") +
      '</p>' +
    '</div>' +
    '</div>';

  GmailApp.sendEmail(RSS_CONFIG.OPERATOR_EMAIL,
    "🔒 CyberNews BBVA — Datos listos para Gemini — " + period, "", {
      htmlBody: htmlBody,
      name:     "CyberNews BBVA Automation"
    });
  Logger.log("Notificación enviada a: " + RSS_CONFIG.OPERATOR_EMAIL);
}

// =============================================================================
// SETUP
// =============================================================================

/**
 * Configura el trigger automático: día 1 de cada mes a las 08:00.
 * Ejecutar manualmente UNA SOLA VEZ.
 */
function setupMonthlyRSSTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(function(t) { return t.getHandlerFunction() === "runMonthlyCyberNewsReport"; })
    .forEach(function(t) { ScriptApp.deleteTrigger(t); });

  ScriptApp.newTrigger("runMonthlyCyberNewsReport")
    .timeBased()
    .onMonthDay(1)
    .atHour(8)
    .create();

  Logger.log("Trigger configurado: día 1 de cada mes a las 08:00.");
  try {
    SpreadsheetApp.getUi()
      .alert("Trigger configurado", "Día 1 de cada mes a las 08:00.", SpreadsheetApp.getUi().ButtonSet.OK);
  } catch(e) {}
}

// =============================================================================
// UTILIDADES INTERNAS
// =============================================================================

function _childVal(el, name, def) {
  try { var c = el.getChild(name); return c ? c.getValue() : def; } catch(e) { return def; }
}

function _extractTag(text, tag) {
  var re = new RegExp("<" + tag + "(?:[^>]*)>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?<\\/" + tag + ">", "i");
  var m  = re.exec(text);
  return m ? m[1].trim() : "";
}

function _stripHtml(html) {
  if (!html) return "";
  html = html.replace(/<!\[CDATA\[|\]\]>/g, "");
  html = html.replace(/<[^>]+>/g, " ");
  html = html
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&nbsp;/g, " ")
    .replace(/&aacute;/g, "á").replace(/&eacute;/g, "é").replace(/&iacute;/g, "í")
    .replace(/&oacute;/g, "ó").replace(/&uacute;/g, "ú").replace(/&ntilde;/g, "ñ")
    .replace(/&Ntilde;/g, "Ñ").replace(/&mdash;/g, "—").replace(/&ndash;/g, "–");
  return html.replace(/\s+/g, " ").trim();
}

function _normalizeUrl(url) {
  return url.toLowerCase().replace(/\?.*$/, "").replace(/#.*$/, "").replace(/\/+$/, "");
}

function _parseDate(str) {
  if (!str) return new Date(0);
  try {
    var d = new Date(str);
    return isNaN(d.getTime()) ? new Date(0) : d;
  } catch(e) { return new Date(0); }
}
