// =============================================================================
// CyberNews Mailer — Google Apps Script
// =============================================================================
// Modos de disparo disponibles:
//
//   A) Menú en Google Sheets  →  abre el Sheet y usa el menú "🔒 CyberNews"
//   B) Web App HTTP (doPost)  →  el pipeline Python llama al endpoint tras
//                                subir los archivos a Drive
//   C) Trigger mensual        →  ejecuta setupMonthlyTrigger() una sola vez
//
// IMPORTANTE: este script debe estar VINCULADO al Google Sheet de destinatarios
// (Extensiones → Apps Script desde dentro del Sheet).
//
// Setup (una sola vez):
//   1. Edita el bloque CONFIG con tus IDs reales.
//   2. Ejecuta setupWebhookToken() para generar y guardar el token de seguridad
//      en Script Properties (no queda expuesto en el código fuente).
//   3. Despliega como Web App:
//        Implementar → Nueva implementación → Tipo: Aplicación web
//        Ejecutar como: Yo  |  Quién tiene acceso: Cualquier persona
//      Copia la URL → pégala en GOOGLE_APPSCRIPT_WEBHOOK_URL del .env de Python
//   4. El token del paso 2 → pégalo en GOOGLE_APPSCRIPT_TOKEN del .env de Python
//
// Estructura del Google Sheet (hoja "Destinatarios"):
//   Col A                    │ Col B  │ Col C (opcional)
//   ─────────────────────────┼────────┼─────────────────
//   usuario@bbva.com         │ si     │ AppSec Lead
//   grupo-cyber@bbva.com     │ si     │ Grupo Google
//   externo@partner.com      │ no     │ (desactivado)
// =============================================================================

// ─────────────────────────────────────────────────────────────────────────────
// CONFIGURACIÓN — edita solo este bloque
// ─────────────────────────────────────────────────────────────────────────────

var CONFIG = {
  // ID del Google Sheet de destinatarios.
  // URL: https://docs.google.com/spreadsheets/d/<ESTE_ID>/edit
  SHEET_ID: "REEMPLAZAR_CON_ID_DEL_SHEET",

  // Nombre exacto de la hoja dentro del Spreadsheet
  SHEET_NAME: "Destinatarios",

  // ID de la carpeta Google Drive donde Python sube los archivos.
  // URL: https://drive.google.com/drive/folders/<ESTE_ID>
  DRIVE_FOLDER_ID: "REEMPLAZAR_CON_ID_DE_CARPETA_DRIVE",

  // Nombres de archivo tal como los sube Python
  HTML_FILENAME:      "top4_email.html",
  JSON_FILENAME:      "top4_monthly.json",
  REMAINING_FILENAME: "remaining_news.html",

  // Alias Gmail configurado en: Mi Cuenta Google → Configuración → Cuentas e importación → "Enviar como"
  SENDER_ALIAS: "ciberseguridad@bbva.com",
  SENDER_NAME:  "BBVA Ciberseguridad",

  // Nombre de la Script Property donde se guarda el token del Web App endpoint.
  // El valor real lo genera setupWebhookToken() — nunca va en el código fuente.
  TOKEN_PROPERTY: "WEBHOOK_TOKEN"
};

// =============================================================================
// A) MENÚ EN GOOGLE SHEETS
// =============================================================================

/**
 * Se ejecuta automáticamente al abrir el Sheet.
 * Agrega el menú "🔒 CyberNews" en la barra de menús del Sheet.
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🔒 CyberNews")
    .addItem("📧 Enviar correo del mes",            "sendCyberNewsMail")
    .addItem("🧪 Enviar prueba (1er destinatario)", "testSendFirst")
    .addSeparator()
    .addItem("📋 Ver destinatarios activos",         "showRecipients")
    .addToUi();
}

// =============================================================================
// B) WEB APP — endpoint HTTP para trigger desde Python
// =============================================================================

/**
 * Endpoint POST. Python llama a este URL tras subir los archivos a Drive.
 *
 * Cuerpo esperado (JSON):
 *   { "token": "<valor de GOOGLE_APPSCRIPT_TOKEN en .env>" }
 *
 * Respuestas posibles:
 *   { "status": 200, "message": "OK: correo enviado a N destinatario(s)" }
 *   { "status": 400, "message": "Cuerpo inválido" }
 *   { "status": 403, "message": "Unauthorized" }
 *   { "status": 500, "message": "Error: ..." }
 */
/**
 * Endpoint GET. Responde con un estado de salud básico.
 * Necesario para que el despliegue del Web App no falle al verificar la URL.
 * No expone información sensible ni ejecuta ninguna acción.
 */
function doGet(e) {
  var page = (e && e.parameter && e.parameter.page) ? e.parameter.page : "";

  // ── Página de noticias adicionales ──────────────────────────────────────
  // Lee remaining_items del JSON generado por Python y renderiza HTML.
  if (page === "remaining") {
    // ── Buscar el JSON en Drive ──────────────────────────────────────────
    // Intento 1: búsqueda dentro de la carpeta configurada.
    var files;
    try {
      var folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
      files = folder.getFilesByName(CONFIG.JSON_FILENAME);
    } catch(err) {
      files = { hasNext: function() { return false; } };
    }

    // Intento 2: si la carpeta es una Shared Drive o el resultado está vacío,
    // buscar globalmente en todos los archivos accesibles.
    if (!files.hasNext()) {
      files = DriveApp.getFilesByName(CONFIG.JSON_FILENAME);
    }

    if (!files.hasNext()) {
      var folderId = CONFIG.DRIVE_FOLDER_ID;
      var folderUrl = 'https://drive.google.com/drive/folders/' + folderId;
      return HtmlService.createHtmlOutput(
        '<html><body style="font-family:Arial,sans-serif;padding:40px;color:#1a1a2e;">' +
        '<h2 style="color:#001490;">CyberNews BBVA</h2>' +
        '<p style="margin-bottom:8px;">El archivo <strong>' + CONFIG.JSON_FILENAME + '</strong> ' +
        'no se encontró en la carpeta Drive configurada.</p>' +
        '<p style="margin-bottom:16px;font-size:13px;color:#555;">' +
        'Carpeta buscada: <a href="' + folderUrl + '" target="_blank" ' +
        'style="color:#001490;">' + folderId + '</a></p>' +
        '<p style="font-size:13px;color:#555;">Posibles causas:</p>' +
        '<ul style="font-size:13px;color:#555;line-height:1.8;">' +
        '<li>El <strong>Paso 7</strong> del notebook no se ejecutó (los archivos no se subieron a Drive).</li>' +
        '<li>El <strong>DRIVE_FOLDER_ID</strong> en Apps Script no coincide con el de Colab Secrets. ' +
        'Verifica que ambos apuntan a la misma carpeta.</li>' +
        '</ul>' +
        '</body></html>'
      ).setTitle("CyberNews – Noticias adicionales");
    }

    var json         = JSON.parse(files.next().getBlob().getDataAsString("utf-8"));
    var items        = json.remaining_items || [];
    var topN         = (json.items || []).length || 0;
    var emailSubject = topN > 0
      ? json.subject.replace(/^Top \d+/, "Top " + topN)
      : (json.subject || "Noticias de ciberseguridad");
    var pageSubject  = items.length + " noticias adicionales al " + emailSubject;
    var genAt        = json.generated_at ? json.generated_at.substring(0, 10) : "";

    // ── Tarjetas unificadas (una por noticia, compacta) ─────────────────
    var cards = "";
    var maxScore = 0;
    for (var s = 0; s < items.length; s++) { if ((items[s].score || 0) > maxScore) maxScore = items[s].score || 0; }
    if (maxScore === 0) maxScore = 30;

    if (items.length === 0) {
      cards = '<p style="color:#6B8BA4;text-align:center;padding:40px 0;">No hay noticias adicionales en este período.</p>';
    } else {
      for (var i = 0; i < items.length; i++) {
        var it   = items[i];
        var kws  = (it.keywords_found || []).slice(0, 4).map(function(k) {
          return '<span style="background:#EBF3FF;color:#2A7EC8;border:1px solid #B8D8F8;' +
                 'padding:1px 6px;border-radius:2px;font-size:10.5px;margin-right:2px;">' + k + '</span>';
        }).join("");
        var date  = it.published_at ? it.published_at.substring(0, 10) : "";
        var barW  = Math.min(Math.round((it.score || 0) / maxScore * 100), 100);
        var rowBg = (i % 2 === 0) ? "#F8FAFD" : "#ffffff";

        cards +=
          '<div style="background:' + rowBg + ';border:1px solid #D8E4F0;border-radius:6px;' +
          'padding:12px 16px;margin-bottom:8px;">' +

          // Fila principal: número + título + score
          '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' +
            '<td style="width:26px;vertical-align:top;padding-top:2px;">' +
              '<span style="display:inline-block;background:#001490;color:#fff;border-radius:50%;' +
              'width:20px;height:20px;font-size:10px;font-weight:bold;text-align:center;' +
              'line-height:20px;">' + (i + 1) + '</span>' +
            '</td>' +
            '<td style="vertical-align:top;padding:0 10px;">' +
              '<a href="' + it.url + '" target="_blank" ' +
              'style="color:#001490;text-decoration:none;font-size:13px;font-weight:bold;line-height:1.4;">' +
              it.title + '</a>' +
              // Score bar bajo el título
              '<div style="margin-top:5px;background:#E0E8F2;border-radius:2px;height:3px;width:100%;max-width:180px;">' +
                '<div style="background:#84C8FC;height:3px;border-radius:2px;width:' + barW + '%;"></div>' +
              '</div>' +
            '</td>' +
            '<td style="vertical-align:top;text-align:right;white-space:nowrap;padding-left:8px;">' +
              '<span style="color:#001490;font-weight:bold;font-size:12px;">' + (it.score || 0).toFixed(1) + ' pts</span>' +
            '</td>' +
          '</tr></table>' +

          // Fila meta: fuente · fecha · keywords
          '<div style="margin-top:6px;padding-left:30px;font-size:11.5px;color:#6B8BA4;">' +
            '<strong style="background:#E8F0FF;color:#001490;padding:1px 6px;border-radius:3px;font-size:11px;">' + (it.source || "") + '</strong>' +
            (date ? ' &nbsp;·&nbsp; ' + date : '') +
            (kws ? ' &nbsp;·&nbsp; ' + kws : '') +
          '</div>' +

          '</div>';
      }
    }

    // ── HTML completo estilo Template C ─────────────────────────────────
    var html =
      '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>CyberNews – Noticias adicionales</title></head>' +
      '<body style="margin:0;padding:0;background:#EEF3F9;font-family:Arial,Helvetica,sans-serif;">' +

      '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF3F9;padding:28px 0;">' +
      '<tr><td align="center">' +
      '<table role="presentation" width="700" cellpadding="0" cellspacing="0" ' +
      'style="max-width:700px;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #D0DCE8;">' +

      // Banda tricolor superior
      '<tr><td style="padding:0;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' +
          '<tr><td style="height:6px;background:#001490;width:60%;"></td>' +
               '<td style="height:6px;background:#84C8FC;width:40%;"></td></tr>' +
        '</table>' +
      '</td></tr>' +

      // Header
      '<tr><td style="padding:22px 36px 18px;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' +
          '<td style="vertical-align:middle;">' +
            '<span style="color:#6B8BA4;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;">Ciberseguridad</span><br>' +
            '<h1 style="color:#1A1A2E;margin:10px 0 4px;font-size:20px;font-weight:bold;line-height:1.3;">' +
              'Más noticias recopiladas</h1>' +
            '<p style="color:#6B8BA4;font-size:12px;margin:0 0 12px;border-bottom:2px solid #EEF3F9;padding-bottom:14px;">' +
              pageSubject + (genAt ? ' &nbsp;·&nbsp; ' + genAt : '') + '</p>' +
          '</td>' +
        '</tr></table>' +
      '</td></tr>' +

      // Listado unificado
      '<tr><td style="padding:0 36px 24px;">' + cards + '</td></tr>' +

      // Banda tricolor inferior + footer
      '<tr><td style="padding:0;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' +
          '<tr><td style="height:4px;background:#84C8FC;width:40%;"></td>' +
               '<td style="height:4px;background:#001490;width:60%;"></td></tr>' +
        '</table>' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F8FAFD;">' +
          '<tr><td style="padding:14px 36px;">' +
            '<p style="color:#8A9BB0;font-size:11px;margin:0;text-align:center;line-height:1.7;">' +
              'BBVA Ciberseguridad &nbsp;·&nbsp; Informe generado automáticamente<br>' +
              'Fuentes verificadas en español &nbsp;·&nbsp; <span style="color:#84C8FC;">CyberNews Scraper</span>' +
            '</p>' +
          '</td></tr>' +
        '</table>' +
      '</td></tr>' +

      '</table></td></tr></table>' +
      '</body></html>';

    return HtmlService.createHtmlOutput(html)
      .setTitle("CyberNews – " + items.length + " noticias adicionales al " + emailSubject)
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  // ── Página de envío del informe ejecutivo de Gemini ───────────────────────
  if (page === "submit") {
    return _renderSubmitPage();
  }

  // ── Health check (GET sin parámetros) ───────────────────────────────────
  return _jsonResponse(200, "CyberNews Mailer — Web App activo. Usa POST para disparar el envio.");
}

function doPost(e) {

  // ── Modo A: formulario web con JSON de Gemini (source=gemini_form) ────────
  // El formulario de ?page=submit envía application/x-www-form-urlencoded
  if (e.parameter && e.parameter.source === "gemini_form") {
    return _handleGeminiFormPost(e);
  }

  // ── Modo B: webhook JSON de Python (legacy) ───────────────────────────────
  // 1. Parsear cuerpo JSON
  var receivedToken = "";
  try {
    var body = JSON.parse(e.postData.contents);
    receivedToken = body.token || "";
  } catch (err) {
    return _jsonResponse(400, "Cuerpo de la peticion invalido (se esperaba JSON).");
  }

  // 2. Verificar token contra Script Properties (no contra el código)
  var expectedToken = PropertiesService.getScriptProperties()
                        .getProperty(CONFIG.TOKEN_PROPERTY);

  if (!expectedToken) {
    return _jsonResponse(500,
      "Token no configurado. Ejecuta setupWebhookToken() primero.");
  }
  if (receivedToken !== expectedToken) {
    return _jsonResponse(403, "Unauthorized");
  }

  // 3. Ejecutar envío
  try {
    var count = sendCyberNewsMail();
    return _jsonResponse(200, "OK: correo enviado a " + count + " destinatario(s).");
  } catch (err) {
    Logger.log("doPost ERROR: " + err.message);
    return _jsonResponse(500, "Error: " + err.message);
  }
}

// =============================================================================
// FUNCIÓN PRINCIPAL DE ENVÍO
// =============================================================================

/**
 * Lee destinatarios del Sheet, obtiene el HTML de Drive y envía el correo.
 * Retorna el número de destinatarios a los que se envió.
 */
function sendCyberNewsMail() {
  Logger.log("=== CyberNews Mailer iniciado ===");

  var recipients = _getRecipients();
  if (recipients.length === 0) {
    Logger.log("No hay destinatarios activos en el Sheet.");
    _showAlert("No hay destinatarios activos en la hoja \"" + CONFIG.SHEET_NAME + "\".");
    return 0;
  }
  Logger.log("Destinatarios (" + recipients.length + "): " + recipients.join(", "));

  var htmlBody = _readHtmlFromDrive();
  var subject  = _getSubjectFromJson();
  Logger.log("Asunto: " + subject);

  recipients.forEach(function (to) {
    GmailApp.sendEmail(to, subject, "", {
      from:     CONFIG.SENDER_ALIAS,
      name:     CONFIG.SENDER_NAME,
      htmlBody: htmlBody,
      charset:  "UTF-8",
      noReply:  false
    });
    Logger.log("Enviado a: " + to);
  });

  Logger.log("=== Envio completado: " + recipients.length + " destinatario(s) ===");
  return recipients.length;
}

// =============================================================================
// HELPERS INTERNOS
// =============================================================================

/**
 * Lee destinatarios activos del Sheet.
 * Columna A = email/grupo | Columna B = "si"/"si"/"true"/"1"/"yes"
 * Fila 1 = encabezado (se ignora).
 */
function _getRecipients() {
  var ss    = SpreadsheetApp.openById(CONFIG.SHEET_ID);
  var sheet = ss.getSheetByName(CONFIG.SHEET_NAME);

  if (!sheet) {
    throw new Error(
      "No se encontro la hoja \"" + CONFIG.SHEET_NAME + "\" en el Spreadsheet."
    );
  }

  var data       = sheet.getDataRange().getValues();
  var recipients = [];
  var activeVals = ["si", "si", "true", "1", "yes"];

  for (var i = 1; i < data.length; i++) {
    var email = String(data[i][0]).trim();
    var flag  = String(data[i][1]).trim().toLowerCase();
    if (email && activeVals.indexOf(flag) !== -1) {
      recipients.push(email);
    }
  }
  return recipients;
}

/**
 * Lee el HTML del email desde la carpeta Drive.
 */
function _readHtmlFromDrive() {
  var folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
  var files  = folder.getFilesByName(CONFIG.HTML_FILENAME);

  if (!files.hasNext()) {
    throw new Error(
      "\"" + CONFIG.HTML_FILENAME + "\" no encontrado en Drive. " +
      "Verifica que el pipeline Python se ejecuto correctamente."
    );
  }
  return files.next().getBlob().getDataAsString("utf-8");
}

/**
 * Lee el asunto desde el JSON generado por Python.
 * Usa un asunto de fallback si el JSON no está disponible.
 */
function _getSubjectFromJson() {
  var folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
  var files  = folder.getFilesByName(CONFIG.JSON_FILENAME);

  if (!files.hasNext()) {
    var now    = new Date();
    var months = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                  "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
    return "Top noticias de ciberseguridad - " +
           months[now.getMonth()] + " " + now.getFullYear();
  }
  var json  = JSON.parse(files.next().getBlob().getDataAsString("utf-8"));
  var topN   = (json.items || []).length || 0;
  var subject = json.subject || "Top noticias de ciberseguridad";
  return topN > 0 ? subject.replace(/^Top \d+/, "Top " + topN) : subject;
}

/**
 * Devuelve una respuesta JSON para el Web App endpoint.
 */
function _jsonResponse(status, message) {
  var payload = JSON.stringify({ status: status, message: message });
  return ContentService.createTextOutput(payload)
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Muestra un alert en el Sheet (solo cuando se llama desde la UI).
 * No lanza error si no hay UI disponible (trigger/webhook).
 */
function _showAlert(msg) {
  try {
    SpreadsheetApp.getUi().alert(msg);
  } catch (e) { /* sin UI — trigger o llamada HTTP */ }
}

// =============================================================================
// UTILIDADES Y SETUP (ejecutar manualmente desde el editor de Apps Script)
// =============================================================================

/**
 * Genera un token UUID aleatorio y lo guarda en Script Properties.
 * Muestra el token UNA SOLA VEZ en pantalla para copiarlo al .env de Python.
 *
 * Ejecutar ANTES de desplegar el Web App.
 */
function setupWebhookToken() {
  var token = Utilities.getUuid() + "-" + Utilities.getUuid();
  PropertiesService.getScriptProperties()
    .setProperty(CONFIG.TOKEN_PROPERTY, token);

  var msg = "Token generado y guardado en Script Properties.\n\n" +
            "Aniadelo a tu archivo .env de Python:\n\n" +
            "GOOGLE_APPSCRIPT_TOKEN=" + token + "\n\n" +
            "Esta ventana no volvera a mostrarlo.";
  SpreadsheetApp.getUi().alert("Webhook Token", msg, SpreadsheetApp.getUi().ButtonSet.OK);
  Logger.log("Token guardado en Script Properties.");
}

/**
 * Configura trigger mensual: dia 1 de cada mes a las 09:00.
 * Ejecutar UNA SOLA VEZ manualmente.
 */
function setupMonthlyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === "sendCyberNewsMail"; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });

  ScriptApp.newTrigger("sendCyberNewsMail")
    .timeBased()
    .onMonthDay(1)
    .atHour(9)
    .create();

  Logger.log("Trigger mensual configurado: dia 1 a las 09:00.");
  _showAlert("Trigger mensual configurado: dia 1 de cada mes a las 09:00.");
}

/**
 * Elimina todos los triggers de envio.
 */
function removeTriggers() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === "sendCyberNewsMail"; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  Logger.log("Triggers eliminados.");
}

/**
 * Prueba: envia solo al primer destinatario activo del Sheet.
 * Uso recomendado para verificar la integracion antes del envio masivo.
 */
function testSendFirst() {
  var recipients = _getRecipients();
  if (recipients.length === 0) {
    _showAlert("No hay destinatarios activos en el Sheet.");
    return;
  }

  var htmlBody = _readHtmlFromDrive();
  var subject  = "[TEST] " + _getSubjectFromJson();
  var to       = recipients[0];

  GmailApp.sendEmail(to, subject, "", {
    from:     CONFIG.SENDER_ALIAS,
    name:     CONFIG.SENDER_NAME,
    htmlBody: htmlBody,
    charset:  "UTF-8",
    noReply:  false
  });

  var msg = "Email de prueba enviado a: " + to;
  Logger.log(msg);
  _showAlert(msg);
}

/**
 * Muestra en un alert la lista de destinatarios activos.
 */
function showRecipients() {
  var list = _getRecipients();
  if (list.length === 0) {
    _showAlert("No hay destinatarios activos.");
    return;
  }
  _showAlert("Destinatarios activos (" + list.length + "):\n\n" + list.join("\n"));
}

// =============================================================================
// INFORME EJECUTIVO VÍA GEMINI — Formulario + Renderer
// =============================================================================

/**
 * Renderiza la página de formulario (?page=submit).
 * El usuario pega aquí el JSON producido por el Gem de Gemini.
 */
function _renderSubmitPage() {
  var tokenHint = "El token es el mismo que usas para el webhook de Python (GOOGLE_APPSCRIPT_TOKEN).";
  var html =
    '<!DOCTYPE html><html lang="es"><head>' +
    '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>CyberNews BBVA — Enviar informe ejecutivo</title>' +
    '<style>' +
      'body{margin:0;padding:0;background:#EEF3F9;font-family:Arial,Helvetica,sans-serif;}' +
      '.wrap{max-width:680px;margin:32px auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #D0DCE8;}' +
      '.hdr{background:#001490;padding:22px 28px;}' +
      '.hdr h1{color:#fff;margin:0;font-size:18px;font-weight:bold;}' +
      '.hdr p{color:#84C8FC;margin:6px 0 0;font-size:12px;}' +
      '.body{padding:28px;}' +
      'label{display:block;color:#001490;font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;}' +
      'input[type=text],textarea{width:100%;box-sizing:border-box;border:1px solid #D0DCE8;border-radius:4px;padding:10px 12px;font-size:13px;font-family:Courier New,monospace;color:#1a1a2e;background:#F8FAFC;margin-bottom:20px;}' +
      'textarea{height:320px;resize:vertical;}' +
      'button{background:#001490;color:#fff;border:none;border-radius:4px;padding:13px 28px;font-size:15px;font-weight:bold;cursor:pointer;width:100%;}' +
      'button:hover{background:#0022B8;}' +
      '.note{background:#F0F5FC;border-radius:4px;padding:12px 16px;color:#6B8BA4;font-size:12px;margin-bottom:20px;line-height:1.6;}' +
      '.err{background:#FFF0F0;border:1px solid #D0021B;border-radius:4px;padding:12px 16px;color:#D0021B;font-size:13px;margin-bottom:16px;display:none;}' +
    '</style></head><body>' +
    '<div class="wrap">' +
      '<div class="hdr">' +
        '<h1>📤 Enviar informe ejecutivo de ciberseguridad</h1>' +
        '<p>Pega el JSON producido por el Gem de Gemini y envía el comunicado</p>' +
      '</div>' +
      '<div class="body">' +
        '<div class="note">' +
          '<strong>¿Cómo obtener el JSON?</strong><br>' +
          '1. Abre el Doc generado automáticamente el día 1 del mes.<br>' +
          '2. Copia el bloque JSON y pégalo en el Gem de Gemini.<br>' +
          '3. Copia TODA la respuesta de Gemini (desde <code>{</code> hasta el último <code>}</code>).<br>' +
          '4. Pégala en el campo de abajo y haz clic en Enviar.' +
        '</div>' +
        '<div id="errBox" class="err"></div>' +
        '<form method="POST" onsubmit="return validateForm()">' +
          '<input type="hidden" name="source" value="gemini_form">' +
          '<label for="tok">Token de autenticación</label>' +
          '<input type="text" id="tok" name="token" placeholder="Ej: a1b2c3d4-...-..." required>' +
          '<label for="gj">JSON de respuesta de Gemini</label>' +
          '<textarea id="gj" name="gemini_json" placeholder=\'{"informe":{...},"noticias":[...],"webhook_url":"..."}\' required></textarea>' +
          '<button type="submit">🚀 Enviar comunicado ejecutivo a destinatarios</button>' +
        '</form>' +
      '</div>' +
    '</div>' +
    '<script>' +
      'function validateForm(){' +
        'var j=document.getElementById("gj").value.trim();' +
        'try{JSON.parse(j);}catch(e){' +
          'var b=document.getElementById("errBox");' +
          'b.style.display="block";' +
          'b.textContent="El texto no es JSON válido: "+e.message;' +
          'return false;}' +
        'return true;}' +
    '</script>' +
    '</body></html>';

  return HtmlService.createHtmlOutput(html)
    .setTitle("CyberNews BBVA — Enviar informe ejecutivo")
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * Maneja el POST del formulario de envío de Gemini.
 * e.parameter.token       → token de autenticación
 * e.parameter.gemini_json → JSON completo de respuesta del Gem
 */
function _handleGeminiFormPost(e) {
  // 1. Autenticar
  var expectedToken = PropertiesService.getScriptProperties()
                        .getProperty(CONFIG.TOKEN_PROPERTY);
  if (!expectedToken) {
    return _renderResultPage(false, "Token no configurado. Ejecuta setupWebhookToken() primero.");
  }
  var token = (e.parameter && e.parameter.token) ? e.parameter.token.trim() : "";
  if (token !== expectedToken) {
    return _renderResultPage(false, "Token incorrecto. Verifica tu GOOGLE_APPSCRIPT_TOKEN.");
  }

  // 2. Parsear JSON de Gemini
  var jsonText = (e.parameter && e.parameter.gemini_json) ? e.parameter.gemini_json.trim() : "";
  if (!jsonText) {
    return _renderResultPage(false, "El campo de JSON está vacío.");
  }

  var report;
  try {
    report = JSON.parse(jsonText);
  } catch (err) {
    return _renderResultPage(false, "El JSON no es válido: " + err.message);
  }

  // 3. Validación básica de estructura
  if (!report.noticias || !Array.isArray(report.noticias) || report.noticias.length === 0) {
    return _renderResultPage(false,
      "El JSON no tiene el campo 'noticias' o está vacío. " +
      "Asegúrate de copiar toda la respuesta del Gem.");
  }
  if (!report.informe) {
    return _renderResultPage(false, "El JSON no tiene el campo 'informe'. Copia toda la respuesta del Gem.");
  }

  // 4. Obtener destinatarios
  var recipients;
  try {
    recipients = _getRecipients();
  } catch (err) {
    return _renderResultPage(false, "Error al leer destinatarios: " + err.message);
  }
  if (recipients.length === 0) {
    return _renderResultPage(false, "No hay destinatarios activos en el Sheet. Revisa la hoja \"Destinatarios\".");
  }

  // 5. Renderizar HTML ejecutivo
  var htmlBody, subject;
  try {
    htmlBody = _renderExecutiveHTML(report);
    var periodo = (report.informe && report.informe.periodo) ? report.informe.periodo : "";
    subject  = "Informe ejecutivo de ciberseguridad — " + periodo;
  } catch (err) {
    Logger.log("_renderExecutiveHTML error: " + err.message);
    return _renderResultPage(false, "Error al generar el HTML del email: " + err.message);
  }

  // 6. Guardar HTML en Drive (para historial)
  try {
    var folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
    var existing = folder.getFilesByName("top4_email_executive.html");
    while (existing.hasNext()) { existing.next().setTrashed(true); }
    folder.createFile("top4_email_executive.html", htmlBody, MimeType.HTML);
  } catch (err) {
    Logger.log("No se pudo guardar el HTML en Drive: " + err.message);
    // No fatal — continuamos con el envío
  }

  // 7. Enviar emails
  var sent = 0;
  var errors = [];
  recipients.forEach(function(to) {
    try {
      GmailApp.sendEmail(to, subject, "", {
        from:     CONFIG.SENDER_ALIAS,
        name:     CONFIG.SENDER_NAME,
        htmlBody: htmlBody,
        charset:  "UTF-8",
        noReply:  false
      });
      sent++;
      Logger.log("Enviado a: " + to);
    } catch (err) {
      errors.push(to + ": " + err.message);
      Logger.log("Error enviando a " + to + ": " + err.message);
    }
  });

  if (sent > 0) {
    var msg = "✅ Informe ejecutivo enviado a " + sent + " destinatario(s).";
    if (errors.length > 0) msg += " Fallaron: " + errors.join("; ");
    return _renderResultPage(true, msg, report);
  } else {
    return _renderResultPage(false, "No se pudo enviar a ningún destinatario: " + errors.join("; "));
  }
}

/**
 * Renderiza el HTML del email ejecutivo a partir del JSON de Gemini.
 * Produce un email completo en HTML inline-CSS compatible con clientes de correo.
 */
function _renderExecutiveHTML(report) {
  var informe  = report.informe  || {};
  var noticias = report.noticias || [];
  var stats    = informe.estadisticas || {};
  var porNivel = stats.por_nivel_riesgo || {};
  var porSeg   = stats.por_segmento     || {};
  var periodo  = informe.periodo        || "";
  var genAt    = informe.generado_en    ? informe.generado_en.substring(0, 10) : Utilities.formatDate(new Date(), "UTC", "yyyy-MM-dd");

  // ── Contadores de nivel ────────────────────────────────────────────────────
  var cCritico = porNivel["CRITICO"] || porNivel["CRÍTICO"] || 0;
  var cAlto    = porNivel["ALTO"]    || 0;
  var cMedio   = porNivel["MEDIO"]   || 0;
  var cBajo    = porNivel["BAJO"]    || 0;

  // ── Tabla de segmentos ─────────────────────────────────────────────────────
  var segRows = "";
  var segOrder = [
    "Ransomware y Malware",
    "Vulnerabilidades Críticas (RCE / Zero-Day)",
    "Filtración de Datos",
    "Cadena de Suministro de Software",
    "Fraude e Ingeniería Social",
    "Infraestructura y Cloud",
    "Gestión de Identidad y Acceso"
  ];
  segOrder.forEach(function(seg, i) {
    var count = porSeg[seg] || 0;
    if (count === 0) return;
    var bg = i % 2 === 0 ? "#F0F5FC" : "#ffffff";
    segRows +=
      '<tr style="background:' + bg + ';border-bottom:1px solid #E8ECF2;">' +
        '<td style="padding:7px 12px;font-size:12px;color:#1a1a2e;">' + seg + '</td>' +
        '<td style="padding:7px 12px;font-size:12px;color:#001490;font-weight:bold;text-align:center;width:50px;">' + count + '</td>' +
      '</tr>';
  });

  // ── Tarjetas de noticias ───────────────────────────────────────────────────
  var cards = "";
  noticias.forEach(function(n) {
    var nivel = (n.nivel_riesgo || "MEDIO").toUpperCase().replace("CRÍTICO","CRITICO");

    // Colores según nivel
    var badgeBg, badgeColor, borderColor, cardBg;
    if (nivel === "CRITICO") {
      badgeBg = "#D0021B"; badgeColor = "#fff"; borderColor = "#D0021B"; cardBg = "#FFF8F8";
    } else if (nivel === "ALTO") {
      badgeBg = "#F5A623"; badgeColor = "#fff"; borderColor = "#F5A623"; cardBg = "#FFFAF4";
    } else if (nivel === "MEDIO") {
      badgeBg = "#F8CC1B"; badgeColor = "#5C4A00"; borderColor = "#F8CC1B"; cardBg = "#FDFBF0";
    } else {
      badgeBg = "#84C8FC"; badgeColor = "#001490"; borderColor = "#84C8FC"; cardBg = "#F0F5FC";
    }

    var rango    = n.rango_afectacion_pct || "—";
    var cifras   = n.cifras_del_incidente || "Sin cifras reportadas en la fuente";
    var expEco   = n.exposicion_economica || "Sin datos en la fuente";
    var impCont  = n.impacto_continuidad_negocio || "No evaluable con la información disponible";
    var impRep   = n.impacto_reputacional        || "No evaluable con la información disponible";
    var accion   = n.accion_directiva            || "—";
    var area     = n.area_negocio_impactada       || "—";
    var segmento = n.segmento_vulnerabilidad      || "—";
    var descEjec = n.descripcion_ejecutiva        || "";

    cards +=
      '<tr><td style="padding:0 28px 20px;">' +
      '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"' +
        ' style="background:' + cardBg + ';border-radius:6px;border-left:4px solid ' + borderColor + ';border:1px solid #D0DCE8;border-left:4px solid ' + borderColor + ';overflow:hidden;">' +

        // ── Cabecera de tarjeta
        '<tr><td style="padding:14px 18px 10px;border-bottom:1px solid #E8ECF2;">' +
          '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' +
            '<td style="vertical-align:top;">' +
              // Badges
              '<span style="display:inline-block;background:' + badgeBg + ';color:' + badgeColor + ';font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:1px;padding:3px 9px;border-radius:3px;margin-right:6px;">' + nivel + '</span>' +
              '<span style="display:inline-block;background:#EEF3F9;color:#001490;font-size:10px;font-weight:bold;letter-spacing:.5px;padding:3px 9px;border-radius:3px;margin-right:6px;">' + _escHtml(segmento) + '</span>' +
              '<span style="display:inline-block;background:#F8F0FF;color:#5A00B8;font-size:10px;padding:3px 9px;border-radius:3px;">' + _escHtml(area) + '</span>' +
              // Título
              '<div style="margin-top:8px;">' +
                '<a href="' + (n.url || "#") + '" target="_blank"' +
                   ' style="color:#1A1A2E;font-size:14px;font-weight:bold;text-decoration:none;line-height:1.4;">' +
                  (n.rank ? ('#' + n.rank + '. ') : '') + _escHtml(n.titulo || "") +
                '</a>' +
              '</div>' +
              '<div style="margin-top:4px;color:#6B8BA4;font-size:11px;">' +
                _escHtml(n.fuente || "") + (n.fecha ? ' &nbsp;·&nbsp; ' + n.fecha : '') +
              '</div>' +
              // Descripción ejecutiva
              (descEjec ? '<p style="margin:8px 0 0;color:#1a1a2e;font-size:12.5px;line-height:1.5;">' + _escHtml(descEjec) + '</p>' : '') +
            '</td>' +
            // % impacto
            '<td style="width:88px;text-align:center;vertical-align:middle;padding-left:14px;">' +
              '<div style="font-size:13px;font-weight:bold;color:' + badgeBg + ';line-height:1.2;">' + _escHtml(rango.split(' ')[0]) + '</div>' +
              '<div style="font-size:9px;color:#6B8BA4;text-transform:uppercase;letter-spacing:.5px;margin-top:3px;">impacto est.</div>' +
              '<div style="margin-top:6px;background:#E0E8F2;border-radius:3px;height:4px;">' +
                '<div style="background:' + badgeBg + ';height:4px;border-radius:3px;width:70%;"></div>' +
              '</div>' +
            '</td>' +
          '</tr></table>' +
        '</td></tr>' +

        // ── Métricas ejecutivas
        '<tr><td style="padding:12px 18px;">' +
          '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:12px;">' +
            _metricRow("Impacto operativo",     impCont,  "#001490") +
            _dividerRow() +
            _metricRow("Riesgo reputacional",   impRep,   "#001490") +
            _dividerRow() +
            _metricRow("Cifras del incidente",  cifras,   "#001490") +
            _dividerRow() +
            _metricRow("Exposición económica",  expEco,   "#001490") +
            _dividerRow() +
            _metricRow("Acción recomendada",    accion,   "#D0021B", true) +
          '</table>' +
        '</td></tr>' +

      '</table>' +
      '</td></tr>';
  });

  // ── Resumen ejecutivo ──────────────────────────────────────────────────────
  var resumenHtml = "";
  if (informe.resumen_ejecutivo) {
    resumenHtml =
      '<tr><td style="padding:0 28px 20px;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"' +
               ' style="background:#F0F5FC;border-radius:6px;border:1px solid #D0DCE8;">' +
          '<tr><td style="padding:16px 18px;">' +
            '<p style="color:#001490;font-size:11px;font-weight:bold;text-transform:uppercase;letter-spacing:.8px;margin:0 0 8px;">Resumen ejecutivo del período</p>' +
            '<p style="color:#1a1a2e;font-size:12.5px;line-height:1.6;margin:0;">' + _escHtml(informe.resumen_ejecutivo) + '</p>' +
          '</td></tr>' +
        '</table>' +
      '</td></tr>';
  }

  // ── HTML completo ──────────────────────────────────────────────────────────
  return '<!DOCTYPE html><html lang="es"><head>' +
    '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Informe ejecutivo de ciberseguridad — ' + _escHtml(periodo) + '</title>' +
    '</head>' +
    '<body style="margin:0;padding:0;background:#EEF3F9;font-family:Arial,Helvetica,sans-serif;">' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF3F9;padding:24px 0;">' +
    '<tr><td align="center">' +
    '<table role="presentation" width="680" cellpadding="0" cellspacing="0"' +
           ' style="max-width:680px;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #D0DCE8;">' +

      // Banda tricolor
      '<tr>' +
        '<td style="height:6px;background:#001490;width:60%;"></td>' +
        '<td style="height:6px;background:#84C8FC;width:40%;"></td>' +
      '</tr>' +

      // Header
      '<tr><td colspan="2" style="padding:22px 28px 18px;border-bottom:1px solid #EEF3F9;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' +
          '<td>' +
            '<p style="color:#6B8BA4;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 4px;">BBVA · Ciberseguridad · Informe Directivo</p>' +
            '<h1 style="color:#1A1A2E;font-size:20px;font-weight:bold;margin:0 0 4px;">Informe ejecutivo de ciberseguridad</h1>' +
            '<p style="color:#6B8BA4;font-size:12px;margin:0;">' + _escHtml(periodo) + ' &nbsp;·&nbsp; Generado el ' + genAt + '</p>' +
          '</td>' +
        '</tr></table>' +
        '<p style="color:#6B8BA4;font-size:12px;margin:12px 0 0;border-top:1px solid #EEF3F9;padding-top:12px;">' +
          'Resumen de amenazas con impacto potencial en la continuidad del negocio, reputación e ingresos.' +
        '</p>' +
      '</td></tr>' +

      // KPI dashboard
      '<tr><td colspan="2" style="padding:20px 28px 8px;">' +
        '<p style="color:#6B8BA4;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin:0 0 12px;font-weight:bold;">Panel de riesgo</p>' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' +
          '<td style="width:25%;padding-right:8px;">' + _kpiCard(cCritico, "CRÍTICO", "#D0021B", "#FFF0F0") + '</td>' +
          '<td style="width:25%;padding:0 4px;">'     + _kpiCard(cAlto,    "ALTO",    "#F5A623", "#FFF4EC") + '</td>' +
          '<td style="width:25%;padding:0 4px;">'     + _kpiCard(cMedio,   "MEDIO",   "#B8960A", "#FFFBEC") + '</td>' +
          '<td style="width:25%;padding-left:8px;">'  + _kpiCard(cBajo,    "BAJO",    "#001490", "#F0F5FC") + '</td>' +
        '</tr></table>' +
      '</td></tr>' +

      // Segmentos (solo si hay datos)
      (segRows ?
        '<tr><td colspan="2" style="padding:16px 28px 8px;">' +
          '<p style="color:#6B8BA4;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin:0 0 10px;font-weight:bold;">Segmentación por tipo de vulnerabilidad</p>' +
          '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #D0DCE8;border-radius:4px;overflow:hidden;">' +
            '<thead><tr style="background:#001490;">' +
              '<th style="padding:8px 12px;color:#fff;text-align:left;font-size:11px;">Segmento</th>' +
              '<th style="padding:8px 12px;color:#84C8FC;text-align:center;font-size:11px;width:50px;">N</th>' +
            '</tr></thead>' +
            '<tbody>' + segRows + '</tbody>' +
          '</table>' +
        '</td></tr>' : '') +

      // Separador + título sección
      '<tr><td colspan="2" style="padding:16px 28px 8px;">' +
        '<div style="height:1px;background:#D0DCE8;"></div>' +
        '<p style="color:#6B8BA4;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin:12px 0 0;font-weight:bold;">Análisis por amenaza</p>' +
      '</td></tr>' +

      // Tarjetas
      cards +

      // Resumen ejecutivo
      resumenHtml +

      // Nota metodológica
      '<tr><td colspan="2" style="padding:0 28px 20px;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F0F5FC;border-radius:6px;border:1px solid #D0DCE8;">' +
          '<tr><td style="padding:12px 16px;">' +
            '<p style="color:#001490;font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:.8px;margin:0 0 4px;">Nota metodológica</p>' +
            '<p style="color:#6B8BA4;font-size:11px;margin:0;line-height:1.6;">' +
              'Los rangos de impacto son estimaciones orientativas basadas en el nivel de riesgo de cada incidente. ' +
              'Las cifras y datos económicos provienen exclusivamente de las fuentes originales; ' +
              'cuando no están disponibles se indica «Sin datos en la fuente». ' +
              'Este informe no constituye una evaluación de riesgo formal para BBVA.' +
            '</p>' +
          '</td></tr>' +
        '</table>' +
      '</td></tr>' +

      // Footer
      '<tr><td colspan="2" style="padding:0;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' +
          '<tr>' +
            '<td style="height:4px;background:#001490;width:60%;"></td>' +
            '<td style="height:4px;background:#84C8FC;width:40%;"></td>' +
          '</tr>' +
        '</table>' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F8FAFC;">' +
          '<tr><td style="padding:14px 28px;text-align:center;">' +
            '<p style="color:#6B8BA4;font-size:11px;margin:0;">' +
              'BBVA Ciberseguridad · Informe ejecutivo generado con asistencia de IA · ' + genAt +
            '</p>' +
          '</td></tr>' +
        '</table>' +
      '</td></tr>' +

    '</table>' +
    '</td></tr></table>' +
    '</body></html>';
}

// ── Helpers de renderizado ────────────────────────────────────────────────────

function _kpiCard(count, label, color, bg) {
  return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"' +
         ' style="background:' + bg + ';border-radius:6px;border-left:4px solid ' + color + ';">' +
    '<tr><td style="padding:12px 14px 10px;">' +
      '<div style="font-size:28px;font-weight:bold;color:' + color + ';line-height:1;">' + count + '</div>' +
      '<div style="font-size:10px;color:' + color + ';font-weight:bold;text-transform:uppercase;letter-spacing:.8px;margin-top:4px;">' + label + '</div>' +
    '</td></tr>' +
  '</table>';
}

function _metricRow(label, value, labelColor, bold) {
  return '<tr>' +
    '<td style="padding:6px 10px 6px 0;vertical-align:top;width:130px;color:' + (labelColor||'#001490') + ';font-weight:bold;font-size:10px;text-transform:uppercase;letter-spacing:.5px;">' + label + '</td>' +
    '<td style="padding:6px 0;vertical-align:top;color:#1a1a2e;line-height:1.5;' + (bold ? 'font-weight:bold;' : '') + '">' + _escHtml(value) + '</td>' +
  '</tr>';
}

function _dividerRow() {
  return '<tr><td colspan="2" style="height:1px;background:#E8ECF2;padding:0;"></td></tr>';
}

function _escHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/**
 * Renderiza una página de resultado (éxito o error) tras el submit del formulario.
 */
function _renderResultPage(ok, message, report) {
  var periodo = (report && report.informe && report.informe.periodo) ? report.informe.periodo : "";
  var color   = ok ? "#001490" : "#D0021B";
  var icon    = ok ? "✅" : "❌";
  var bg      = ok ? "#F0FFF4" : "#FFF0F0";
  var borderC = ok ? "#00A651" : "#D0021B";

  var statsHtml = "";
  if (ok && report && report.informe && report.informe.estadisticas) {
    var s = report.informe.estadisticas;
    var pn = s.por_nivel_riesgo || {};
    statsHtml =
      '<div style="margin-top:16px;background:#F0F5FC;border-radius:6px;padding:14px 18px;">' +
        '<p style="color:#001490;font-size:11px;font-weight:bold;margin:0 0 8px;">Resumen del informe enviado</p>' +
        '<p style="color:#1a1a2e;font-size:13px;margin:0;">Período: <strong>' + _escHtml(periodo) + '</strong><br>' +
        'Noticias: ' + (s.total_analizadas||0) + ' &nbsp;·&nbsp; ' +
        'Crítico: ' + (pn["CRITICO"]||pn["CRÍTICO"]||0) + ' &nbsp;·&nbsp; ' +
        'Alto: ' + (pn["ALTO"]||0) + ' &nbsp;·&nbsp; ' +
        'Medio: ' + (pn["MEDIO"]||0) + ' &nbsp;·&nbsp; ' +
        'Bajo: ' + (pn["BAJO"]||0) +
        '</p>' +
      '</div>';
  }

  var html =
    '<!DOCTYPE html><html lang="es"><head>' +
    '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>CyberNews BBVA — Resultado</title>' +
    '<style>body{margin:0;padding:0;background:#EEF3F9;font-family:Arial,sans-serif;}' +
    '.wrap{max-width:600px;margin:48px auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #D0DCE8;}' +
    '.hdr{background:#001490;padding:20px 28px;}' +
    '.hdr h1{color:#fff;margin:0;font-size:18px;} .hdr p{color:#84C8FC;margin:4px 0 0;font-size:12px;}' +
    '.body{padding:28px;}' +
    '.msg{background:' + bg + ';border:1px solid ' + borderC + ';border-radius:6px;padding:16px 18px;color:' + color + ';font-size:14px;font-weight:bold;}' +
    '.btn{display:inline-block;margin-top:20px;background:#001490;color:#fff;padding:12px 24px;border-radius:4px;text-decoration:none;font-size:14px;font-weight:bold;}' +
    '</style></head><body>' +
    '<div class="wrap">' +
      '<div class="hdr"><h1>CyberNews BBVA</h1><p>Informe ejecutivo de ciberseguridad</p></div>' +
      '<div class="body">' +
        '<div class="msg">' + icon + ' ' + _escHtml(message) + '</div>' +
        statsHtml +
        '<a class="btn" href="?page=submit">← Volver al formulario</a>' +
      '</div>' +
    '</div>' +
    '</body></html>';

  return HtmlService.createHtmlOutput(html)
    .setTitle("CyberNews BBVA — Resultado")
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
