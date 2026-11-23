import gzip
import json
import math
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
OECE = "https://www.gob.pe/52005-acceder-al-portal-de-contrataciones-abiertas-de-la-compra-publica-ocds"
SEACE = "https://www.gob.pe/32306-como-acceder-a-los-procesos-de-seleccion-convocados-y-en-curso"
OBJETOS = {"goods": "Bienes", "services": "Servicios", "works": "Obras"}
ESTADOS = {
    "active": "En curso", "complete": "Concluido", "cancelled": "Cancelado",
    "unsuccessful": "Desierto", "planned": "Planificado", "withdrawn": "Retirado",
}


def normalizar(texto):
    base = unicodedata.normalize("NFKD", texto or "").casefold()
    return "".join(letra for letra in base if not unicodedata.combining(letra))


@contextmanager
def conectar(ruta):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ruta)
    db.row_factory = sqlite3.Row
    db.create_function("normalizar", 1, normalizar, deterministic=True)
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def importe(valor):
    monto = (valor or {}).get("amount")
    if isinstance(monto, (int, float)) and not isinstance(monto, bool):
        if math.isfinite(monto) and monto >= 0:
            return monto
    return None


def enlace_documento(documentos):
    for documento in documentos or []:
        enlace = documento.get("url") or ""
        partes = urlsplit(enlace)
        if partes.scheme in {"https", "http"} and partes.netloc and not partes.username:
            return enlace
    return None


def leer_procesos(ruta):
    ruta = Path(ruta)
    if ruta.suffixes[-2:] == [".jsonl", ".gz"] or ruta.suffix == ".jsonl":
        abrir = gzip.open if ruta.suffix == ".gz" else open
        with abrir(ruta, "rt", encoding="utf-8-sig") as archivo:
            for linea in archivo:
                if linea.strip():
                    proceso = json.loads(linea)
                    yield proceso.get("compiledRelease") or proceso, proceso.get("ocid")
        return
    with ruta.open(encoding="utf-8-sig") as archivo:
        paquete = json.load(archivo)
    if not isinstance(paquete, dict) or not isinstance(paquete.get("records"), list):
        raise ValueError("Se requiere un Record Package OCDS o un archivo JSONL de procesos compilados.")
    for registro in paquete["records"]:
        yield registro.get("compiledRelease") or {}, registro.get("ocid")


def importar_ocds(db, ruta, origen):
    """Importa snapshots compilados de procesos. Devuelve importados y omitidos."""
    importados = omitidos = 0
    for proceso, ocid_registro in leer_procesos(ruta):
        licitacion = proceso.get("tender") or {}
        ocid = proceso.get("ocid") or ocid_registro
        fecha_snapshot = proceso.get("date")
        titulo = licitacion.get("title") or licitacion.get("description")
        if not (ocid and fecha_snapshot and titulo):
            omitidos += 1
            continue
        anterior = db.execute(
            "SELECT actualizado FROM convocatorias WHERE origen = ? AND ocid = ?", (origen, ocid)
        ).fetchone()
        # OCDS entrega marcas de tiempo ISO 8601; convertir para respetar husos.
        if anterior and instante(fecha_snapshot) < instante(anterior["actualizado"]):
            omitidos += 1
            continue
        instante(fecha_snapshot)
        comprador = proceso.get("buyer") or licitacion.get("procuringEntity") or {}
        parte = next(
            (p for p in proceso.get("parties") or [] if comprador.get("id") and p.get("id") == comprador["id"]),
            {},
        )
        periodo = licitacion.get("tenderPeriod") or {}
        valor = licitacion.get("value") or {}
        db.execute(
            """INSERT INTO convocatorias VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (origen, ocid) DO UPDATE SET
               titulo=excluded.titulo, entidad=excluded.entidad, region=excluded.region,
               objeto=excluded.objeto, estado=excluded.estado, fecha=excluded.fecha,
               cierre=excluded.cierre, descripcion=excluded.descripcion,
               referencia=excluded.referencia, moneda=excluded.moneda, enlace=excluded.enlace,
               actualizado=excluded.actualizado""",
            (origen, ocid, titulo, comprador.get("name") or parte.get("name"),
             (parte.get("address") or {}).get("region"),
             licitacion.get("mainProcurementCategory"), licitacion.get("status"),
             periodo.get("startDate"), periodo.get("endDate"), licitacion.get("description"),
             importe(valor), valor.get("currency"), enlace_documento(licitacion.get("documents")),
             fecha_snapshot),
        )
        db.execute("DELETE FROM adjudicaciones WHERE origen = ? AND ocid = ?", (origen, ocid))
        for award in proceso.get("awards") or []:
            estado = award.get("status") or None
            proveedores = ", ".join(p["name"] for p in award.get("suppliers") or [] if p.get("name"))
            publicada = estado == "active" or (estado is None and proveedores and award.get("date"))
            if not publicada or not award.get("id"):
                continue
            valor_award = award.get("value") or {}
            db.execute(
                "INSERT INTO adjudicaciones VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (origen, ocid, award["id"], proveedores or None, estado, importe(valor_award),
                 valor_award.get("currency"), award.get("date"),
                 enlace_documento(award.get("documents"))),
            )
        importados += 1
    return importados, omitidos


def instante(texto):
    fecha = datetime.fromisoformat(texto)
    if fecha.tzinfo is None:
        return fecha.replace(tzinfo=timezone.utc)
    return fecha
