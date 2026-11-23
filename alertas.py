import calendar
import json
import logging
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
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


def enviar(correo, asunto, texto):
    mensaje = EmailMessage()
    mensaje["From"] = os.environ["SMTP_FROM"]
    mensaje["To"] = correo
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
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
           f"Para recibir el resumen {frecuencia}, pega este código en Buscador y Alertas dentro de 24 horas:\n\n{codigo}")


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
                resultados = db.execute(f"SELECT titulo,ocid,cierre FROM convocatorias WHERE {where} ORDER BY fecha DESC LIMIT 50", params)
                lineas = [f"{r['titulo']} · {r['ocid']} · Cierre: {r['cierre'] or 'sin fecha'}" for r in resultados]
                resumen = "\n".join(lineas) or "Sin coincidencias para los filtros seleccionados."
                enviar(fila["correo"], "LicitIA · Resumen " + fila["frecuencia"],
                       resumen + "\n\nPara cancelar, pega este código en la opción Cancelar alerta de LicitIA:\n" + fila["token"])
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
