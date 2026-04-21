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
  HTML_FILENAME: "top4_email.html",
  JSON_FILENAME: "top4_monthly.json",

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
