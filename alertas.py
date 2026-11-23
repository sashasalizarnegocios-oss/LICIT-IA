import calendar
import html
import json
import logging
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from threading import Thread

from datos import conectar, normalizar


def condiciones_busqueda(origen, filtros):
    condiciones, parametros = ["origen = ?"], [origen]
    for palabra in normalizar(filtros["q"]).split():
        condiciones.append("instr(normalizar(titulo || ' ' || coalesce(entidad, '') || ' ' || ocid || ' ' || coalesce(descripcion, '')), ?) > 0")
        parametros.append(palabra)
    for campo in ("region", "objeto", "estado"):
        if filtros[campo]:
            condiciones.append(f"{campo} = ?")
            parametros.append(filtros[campo])
    if filtros["anio"]:
        condiciones.append("substr(fecha, 1, 4) = ?")
        parametros.append(filtros["anio"])
    return " AND ".join(condiciones), parametros


def siguiente(ahora, frecuencia):
    if frecuencia == "semanal":
        return ahora + timedelta(days=7)
    mes = ahora.month % 12 + 1
    anio = ahora.year + (mes == 1)
    return ahora.replace(year=anio, month=mes, day=min(ahora.day, calendar.monthrange(anio, mes)[1]))


def _escapar(valor):
    """Escapa texto externo antes de introducirlo en una plantilla HTML."""
    return html.escape(str("" if valor is None else valor), quote=True)


def _plantilla_correo(etiqueta, contenido):
    """Marco compartido sin recursos externos, con estilos inline para clientes de correo."""
    return f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f2f5fa;font-family:Arial,Helvetica,sans-serif;color:#172b44;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;background-color:#f2f5fa;">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="border-collapse:collapse;width:100%;max-width:600px;background-color:#ffffff;">
      <tr><td style="background-color:#0e1d35;padding:30px 32px;border-bottom:4px solid #2ac9ba;">
        <p style="margin:0;color:#ffffff;font-size:30px;font-weight:700;letter-spacing:-0.8px;line-height:36px;">Licit<span style="color:#4ae0ce;">IA</span></p>
        <p style="margin:5px 0 0;color:#d2deec;font-size:13px;line-height:20px;letter-spacing:0.4px;">Radar de contrataciones públicas</p>
      </td></tr>
      <tr><td style="padding:32px 32px 28px;">
        <p style="margin:0 0 18px;color:#197b83;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;">{_escapar(etiqueta)}</p>
        {contenido}
      </td></tr>
      <tr><td style="padding:22px 32px;background-color:#f6f8fc;border-top:1px solid #e3eaf2;">
        <p style="margin:0;color:#64748b;font-size:12px;line-height:19px;">Este es un correo automático de LicitIA. Por favor, no respondas a este mensaje.</p>
        <p style="margin:8px 0 0;color:#64748b;font-size:12px;line-height:19px;">Prototipo con fines académicos.</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _html_confirmacion(codigo, frecuencia):
    contenido = f"""
        <h1 style="margin:0 0 16px;color:#0e1d35;font-size:25px;line-height:32px;">Confirma tu alerta</h1>
        <p style="margin:0 0 12px;font-size:15px;line-height:24px;">Hola,</p>
        <p style="margin:0 0 22px;font-size:15px;line-height:24px;">
          Solicitaste recibir un resumen {_escapar(frecuencia)} de contrataciones públicas
          que coincidan con tus filtros de búsqueda en LicitIA.
          Para activar la alerta, copia este código y pégalo en
          <strong>Buscador y Alertas</strong>.
        </p>
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;background-color:#eef8f8;border:1px solid #b5e5e0;">
          <tr><td align="center" style="padding:23px 14px;">
            <p style="margin:0 0 9px;color:#40707a;font-size:11px;font-weight:700;letter-spacing:1.2px;">TU CÓDIGO DE CONFIRMACIÓN</p>
            <p style="margin:0;color:#0e1d35;font-family:'Courier New',Courier,monospace;font-size:23px;font-weight:700;line-height:32px;letter-spacing:1px;overflow-wrap:anywhere;word-break:break-all;">{_escapar(codigo)}</p>
          </td></tr>
        </table>
        <p style="margin:19px 0 0;color:#945915;font-size:14px;font-weight:700;line-height:22px;">El código vence en 24 horas.</p>
        <p style="margin:12px 0 0;color:#64748b;font-size:13px;line-height:21px;">Si no solicitaste esto, ignora este correo.</p>
    """
    return _plantilla_correo("Activación de alerta", contenido)


def _html_resumen(coincidencias, codigo_cancelacion, frecuencia):
    filas = []
    for numero, registro in enumerate(coincidencias, 1):
        titulo = _escapar(registro["titulo"])
        ocid = _escapar(registro["ocid"])
        cierre = _escapar(registro["cierre"] or "sin fecha")
        filas.append(f"""
          <tr><td style="padding:17px 16px;border-bottom:1px solid #e3eaf2;">
            <p style="margin:0 0 7px;color:#197b83;font-size:11px;font-weight:700;letter-spacing:0.6px;">COINCIDENCIA {numero}</p>
            <p style="margin:0 0 8px;color:#0e1d35;font-size:15px;font-weight:700;line-height:22px;overflow-wrap:anywhere;">{titulo}</p>
            <p style="margin:0;color:#52657a;font-size:12px;line-height:20px;overflow-wrap:anywhere;word-break:break-word;">OCID: {ocid}</p>
            <p style="margin:2px 0 0;color:#52657a;font-size:12px;line-height:20px;">Cierre: {cierre}</p>
          </td></tr>
        """)
    if filas:
        listado = f"""
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;border:1px solid #e3eaf2;">
          {''.join(filas)}
        </table>"""
    else:
        listado = '<p style="margin:0;padding:22px 16px;background-color:#f6f8fc;color:#52657a;font-size:14px;line-height:22px;">Sin coincidencias para los filtros seleccionados.</p>'
    contenido = f"""
        <h1 style="margin:0 0 13px;color:#0e1d35;font-size:25px;line-height:32px;">Tu radar de oportunidades</h1>
        <p style="margin:0 0 22px;font-size:15px;line-height:24px;">
          Este es tu resumen {_escapar(frecuencia)} de contrataciones públicas
          que coinciden con la búsqueda que configuraste en LicitIA.
        </p>
        {listado}
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:25px;border-collapse:collapse;background-color:#f6f8fc;border-left:4px solid #2ac9ba;">
          <tr><td style="padding:20px 16px;">
            <p style="margin:0 0 9px;color:#0e1d35;font-size:14px;font-weight:700;line-height:21px;">¿Quieres cancelar tu alerta?</p>
            <p style="margin:0 0 12px;color:#52657a;font-size:13px;line-height:20px;">Pega este código en la opción <strong>Cancelar alerta de LicitIA</strong>:</p>
            <p style="margin:0;color:#0e1d35;font-family:'Courier New',Courier,monospace;font-size:18px;font-weight:700;line-height:27px;overflow-wrap:anywhere;word-break:break-all;">{_escapar(codigo_cancelacion)}</p>
          </td></tr>
        </table>
    """
    return _plantilla_correo("Resumen de coincidencias", contenido)


def enviar(correo, asunto, texto, contenido_html=None):
    mensaje = EmailMessage()
    mensaje["From"] = formataddr(("LicitIA", os.environ["SMTP_FROM"]))
    mensaje["To"] = correo
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    if contenido_html is not None:
        mensaje.add_alternative(contenido_html, subtype="html")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(mensaje)

def solicitar(db, correo, frecuencia, origen, filtros):
    ahora = datetime.now(timezone.utc)
    criterios = json.dumps(filtros, sort_keys=True)
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT 1 FROM solicitudes WHERE correo=? AND creada>? LIMIT 1",
                  (correo, (ahora-timedelta(minutes=2)).isoformat())).fetchone():
        return
    db.execute("DELETE FROM solicitudes WHERE creada < ?", ((ahora-timedelta(days=1)).isoformat(),))
    codigo = secrets.token_urlsafe(18)
    db.execute("INSERT INTO solicitudes VALUES (?,?,?,?,?,?)",
               (codigo, correo, frecuencia, origen, criterios, ahora.isoformat()))
    enviar(correo, "Confirma tu alerta de LicitIA",
           f"Para recibir el resumen {frecuencia}, pega este código en Buscador y Alertas dentro de 24 horas:\n\n{codigo}",
           contenido_html=_html_confirmacion(codigo, frecuencia))


def confirmar(db, codigo):
    ahora = datetime.now(timezone.utc)
    db.execute("BEGIN IMMEDIATE")
    fila = db.execute("SELECT * FROM solicitudes WHERE codigo=? AND creada>=?",
                      (codigo, (ahora-timedelta(days=1)).isoformat())).fetchone()
    if not fila:
        return False
    db.execute("""INSERT INTO suscripciones VALUES (?,?,?,?,?,?)
        ON CONFLICT(correo,origen,filtros) DO UPDATE SET frecuencia=excluded.frecuencia, proxima=excluded.proxima""",
        (secrets.token_urlsafe(24), fila["correo"], fila["frecuencia"], fila["origen"], fila["filtros"],
         siguiente(ahora, fila["frecuencia"]).isoformat()))
    db.execute("DELETE FROM solicitudes WHERE correo=? AND origen=? AND filtros=?",
               (fila["correo"], fila["origen"], fila["filtros"]))
    return True


def despachar(ruta):
    ahora = datetime.now(timezone.utc)
    with conectar(ruta) as db:
        pendientes = db.execute("SELECT token FROM suscripciones WHERE proxima<=?", (ahora.isoformat(),)).fetchall()
    for entrada in pendientes:
        try:
            with conectar(ruta) as db:
                db.execute("BEGIN IMMEDIATE")
                fila = db.execute("SELECT * FROM suscripciones WHERE token=? AND proxima<=?",
                                  (entrada["token"], ahora.isoformat())).fetchone()
                if not fila:
                    continue
                where, params = condiciones_busqueda(fila["origen"], json.loads(fila["filtros"]))
                resultados = db.execute(f"SELECT titulo,ocid,cierre FROM convocatorias WHERE {where} ORDER BY fecha DESC LIMIT 50", params).fetchall()
                lineas = [f"{r['titulo']} · {r['ocid']} · Cierre: {r['cierre'] or 'sin fecha'}" for r in resultados]
                resumen = "\n".join(lineas) or "Sin coincidencias para los filtros seleccionados."
                enviar(fila["correo"], "LicitIA · Resumen " + fila["frecuencia"],
                       resumen + "\n\nPara cancelar, pega este código en la opción Cancelar alerta de LicitIA:\n" + fila["token"],
                       contenido_html=_html_resumen(resultados, fila["token"], fila["frecuencia"]))
                db.execute("UPDATE suscripciones SET proxima=? WHERE token=?",
                           (siguiente(ahora, fila["frecuencia"]).isoformat(), fila["token"]))
        except (OSError, ValueError, KeyError):
            logging.exception("No se pudo entregar un resumen de alertas")


def iniciar(ruta):
    def ciclo():
        while True:
            try:
                despachar(ruta)
            except Exception:
                logging.exception("Falló la revisión de alertas")
            time.sleep(300)
    Thread(target=ciclo, name="licitia-alertas", daemon=True).start()
