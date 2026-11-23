import os
import re

from flask import Flask, abort, render_template, request

from asistente import MODELO, consultar
from datos import ESTADOS, OBJETOS, OECE, ROOT, SEACE, conectar, importar_ocds, normalizar

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get("RADAR_DB", ROOT / "instance" / "radar.sqlite3")
app.config["MAX_CONTENT_LENGTH"] = 8192
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
def buscar():
    origen = request.args.get("origen", "demo")
    if origen not in ("demo", "oece"):
        abort(404)
    filtros = {k: request.args.get(k, "").strip()[:150] for k in ("q", "region", "objeto", "estado", "anio")}
    pagina = max(1, min(request.args.get("pagina", 1, type=int), 10_000_000))
    condiciones, parametros = ["origen = ?"], [origen]
    for palabra in normalizar(filtros["q"]).split():
        condiciones.append(
            "instr(normalizar(titulo || ' ' || coalesce(entidad, '') || ' ' || ocid || ' ' || coalesce(descripcion, '')), ?) > 0"
        )
        parametros.append(palabra)
    for campo in ("region", "objeto", "estado"):
        if filtros[campo]:
            condiciones.append(f"{campo} = ?")
            parametros.append(filtros[campo])
    if filtros["anio"]:
        condiciones.append("substr(fecha, 1, 4) = ?")
        parametros.append(filtros["anio"])
    where = " AND ".join(condiciones)
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
        app.run(host="127.0.0.1", port=8000)
