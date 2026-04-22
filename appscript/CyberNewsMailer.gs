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

    var json    = JSON.parse(files.next().getBlob().getDataAsString("utf-8"));
    var items   = json.remaining_items || [];
    var subject = json.subject || "Noticias de ciberseguridad";
    var genAt   = json.generated_at ? json.generated_at.substring(0, 10) : "";

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
              subject + (genAt ? ' &nbsp;·&nbsp; ' + genAt : '') +
              ' &nbsp;·&nbsp; <strong style="color:#001490;">' + items.length + '</strong> artículos</p>' +
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
      .setTitle("CyberNews – " + items.length + " noticias adicionales")
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  // ── Health check (GET sin parámetros) ───────────────────────────────────
  return _jsonResponse(200, "CyberNews Mailer — Web App activo. Usa POST para disparar el envio.");
}

function doPost(e) {
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
  var json = JSON.parse(files.next().getBlob().getDataAsString("utf-8"));
  return json.subject || "Top noticias de ciberseguridad";
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
