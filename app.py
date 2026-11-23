import os
import re

from flask import Flask, abort, redirect, render_template, request, url_for

import alertas
from asistente import MODELO, consultar, conversar
from datos import ESTADOS, OBJETOS, OECE, ROOT, SEACE, conectar, importar_ocds, normalizar

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get("RADAR_DB", ROOT / "instance" / "radar.sqlite3")
app.config["MAX_CONTENT_LENGTH"] = 65536
PALABRAS_COMUNES = {"para", "servicio", "servicios", "contratacion", "adquisicion", "ejecucion"}


def inicializar(db):
    db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))


def cargar_archivo(ruta):
    with conectar(app.config["DATABASE"]) as db:
        inicializar(db)
        count, skipped = importar_ocds(db, ruta, "oece")
    print(f"Datos importados: {count} procesos cargados, {skipped} omitidos.")


@app.template_filter("monto")
def mostrar_monto(valor, moneda):
    if valor is None:
        return "Sin dato"
    prefijo = "S/" if moneda == "PEN" else (moneda or "Moneda sin informar")
    return f"{prefijo} {valor:,.2f}"


@app.context_processor
def etiquetas():
    return {"objetos": OBJETOS, "estados": ESTADOS, "oece": OECE, "seace": SEACE, "modelo": MODELO}


@app.get("/equipo")
def equipo():
    return render_template("equipo.html")


@app.get("/")
def inicio():
    if request.args:
        return redirect(url_for("buscar") + "?" + request.query_string.decode("ascii"))
    return render_template("inicio.html")


@app.get("/propuesta")
def propuesta():
    return render_template("propuesta.html")


@app.get("/analisis")
def analisis():
    with conectar(app.config["DATABASE"]) as db:
        procesos = db.execute("""SELECT origen, ocid, titulo, entidad FROM convocatorias
                                 ORDER BY (origen = 'oece') DESC, fecha DESC""").fetchall()
    return render_template("analisis.html", procesos=procesos)


@app.post("/analisis/chat")
def chat():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        abort(400)
    ids = datos.get("documentos")
    historial = datos.get("historial")
    if not isinstance(ids, list) or len(ids) != 2 or not all(isinstance(i, str) for i in ids) or ids[0] == ids[1]:
        return {"error": "Elige dos documentos distintos."}, 400
    if not isinstance(historial, list) or not 1 <= len(historial) <= 9 or len(historial) % 2 == 0:
        abort(400)
    for i, mensaje in enumerate(historial):
        rol = "assistant" if i % 2 else "user"
        if (not isinstance(mensaje, dict) or mensaje.get("role") != rol or
                not isinstance(mensaje.get("content"), str) or not 0 < len(mensaje["content"].strip()) <= 4000):
            abort(400)
    documentos = []
    with conectar(app.config["DATABASE"]) as db:
        for clave in ids:
            origen, _, ocid = clave.partition("/")
            fila = db.execute("SELECT * FROM convocatorias WHERE origen=? AND ocid=?", (origen, ocid)).fetchone()
            if not fila:
                return {"error": "Uno de los expedientes ya no está disponible."}, 404
            doc = dict(fila)
            doc["adjudicaciones"] = [dict(r) for r in db.execute(
                "SELECT proveedores, monto, moneda, fecha, award_id FROM adjudicaciones WHERE origen=? AND ocid=? LIMIT 30",
                (origen, ocid))]
            documentos.append(doc)
    try:
        return {"respuesta": conversar(documentos, historial)}
    except (OSError, ValueError, KeyError, TypeError):
        return {"error": "Ollama no respondió. Comprueba que el servicio esté activo y el modelo instalado."}, 503


@app.post("/alertas")
def gestionar_alerta():
    accion = request.form.get("accion")
    codigo = request.form.get("codigo", "").strip()
    with conectar(app.config["DATABASE"]) as db:
        if accion == "confirmar":
            ok = alertas.confirmar(db, codigo)
            mensaje = "Alerta activada." if ok else "Código incorrecto o vencido."
        elif accion == "cancelar":
            ok = db.execute("DELETE FROM suscripciones WHERE token=?", (codigo,)).rowcount
            mensaje = "Alerta cancelada." if ok else "Código de cancelación incorrecto."
        elif accion == "crear":
            correo = request.form.get("correo", "").strip().lower()
            frecuencia = request.form.get("frecuencia")
            origen = request.form.get("origen")
            if (len(correo) > 254 or not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}", correo)
                    or frecuencia not in ("semanal", "mensual") or origen not in ("demo", "oece")):
                return {"error": "Revisa el correo y la frecuencia."}, 400
            filtros = {k: request.form.get(k, "").strip()[:150] for k in ("q","region","objeto","estado","anio")}
            try:
                alertas.solicitar(db, correo, frecuencia, origen, filtros)
            except (KeyError, OSError, ValueError):
                db.rollback()
                return {"error": "No se pudo enviar el código. Revisa la configuración del correo saliente."}, 503
            mensaje = "Revisa tu correo y confirma la alerta con el código recibido."
        else:
            abort(400)
    return {"mensaje": mensaje}


@app.get("/fuentes")
def fuentes():
    return render_template("fuentes.html")


@app.get("/buscador")
def buscar():
    origen = request.args.get("origen", "demo")
    if origen not in ("demo", "oece"):
        abort(404)
    filtros = {k: request.args.get(k, "").strip()[:150] for k in ("q", "region", "objeto", "estado", "anio")}
    pagina = max(1, min(request.args.get("pagina", 1, type=int), 10_000_000))
    where, parametros = alertas.condiciones_busqueda(origen, filtros)
    with conectar(app.config["DATABASE"]) as db:
        regiones = db.execute(
            "SELECT DISTINCT region FROM convocatorias WHERE origen = ? AND region <> '' ORDER BY region",
            (origen,),
        ).fetchall()
        total = db.execute(f"SELECT count(*) FROM convocatorias WHERE {where}", parametros).fetchone()[0]
        resultados = db.execute(
            f"""SELECT * FROM convocatorias WHERE {where}
                ORDER BY fecha DESC, ocid LIMIT 15 OFFSET ?""",
            [*parametros, (pagina - 1) * 15],
        ).fetchall()
    return render_template(
        "index.html", origen=origen, filtros=filtros, regiones=regiones, resultados=resultados,
        pagina=pagina, total=total,
    )


def comparar(db, proceso):
    palabras = [
        palabra for palabra in dict.fromkeys(re.findall(r"[a-z]{4,}", normalizar(proceso["titulo"])))
        if palabra not in PALABRAS_COMUNES
    ][:12]
    if not palabras or not proceso["objeto"]:
        return []
    coincidencias = " + ".join(
        "(instr(normalizar(c.titulo), ?) > 0)" for _ in palabras
    )
    return db.execute(
        f"""SELECT a.*, c.titulo, c.entidad, c.descripcion, ({coincidencias}) AS coincidencias
              FROM adjudicaciones a JOIN convocatorias c USING (origen, ocid)
             WHERE c.origen = ? AND c.ocid <> ? AND c.objeto = ?
               AND coincidencias > 0
             ORDER BY coincidencias DESC, (a.moneda = ?) DESC, a.fecha DESC, a.ocid, a.award_id LIMIT 5""",
        [*palabras, proceso["origen"], proceso["ocid"], proceso["objeto"], proceso["moneda"]],
    ).fetchall()


@app.route("/expediente/<origen>/<path:ocid>", methods=["GET", "POST"])
def expediente(origen, ocid):
    with conectar(app.config["DATABASE"]) as db:
        proceso = db.execute(
            "SELECT * FROM convocatorias WHERE origen = ? AND ocid = ?", (origen, ocid)
        ).fetchone()
        if proceso is None:
            abort(404)
        propios = db.execute(
            "SELECT * FROM adjudicaciones WHERE origen = ? AND ocid = ? ORDER BY fecha DESC, award_id",
            (origen, ocid),
        ).fetchall()
        casos = comparar(db, proceso)

    analisis = error = ""
    pregunta = request.form.get("pregunta", "").strip()
    if request.method == "POST":
        if not casos:
            error = "La base actual no contiene antecedentes comparables para este expediente."
        elif not 1 <= len(pregunta) <= 300:
            error = "Escribe una pregunta de 1 a 300 caracteres."
        else:
            try:
                analisis = consultar(proceso, casos, pregunta)
            except (OSError, ValueError, KeyError, TypeError):
                error = "Ollama no respondió correctamente. Comprueba que esté abierto y que el modelo esté descargado."
    return render_template(
        "expediente.html", proceso=proceso, casos=casos, propios=propios,
        pregunta=pregunta, analisis=analisis, error=error, origen=origen,
    )


with conectar(app.config["DATABASE"]) as db:
    inicializar(db)
    if not db.execute("SELECT 1 FROM convocatorias WHERE origen = 'demo' LIMIT 1").fetchone():
        importar_ocds(db, ROOT / "data" / "demo.json", "demo")


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Radar Público")
    parser.add_argument("--importar", type=Path, metavar="ARCHIVO_OCDS")
    args = parser.parse_args()
    if args.importar:
        try:
            cargar_archivo(args.importar)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            parser.exit(1, f"Importación cancelada: {error}\n")
    else:
        alertas.iniciar(app.config["DATABASE"])
        app.run(host="127.0.0.1", port=8000)
