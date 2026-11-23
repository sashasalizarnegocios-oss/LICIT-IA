"""Genera vistas previas locales sin enviar correos ni acceder a secretos SMTP."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alertas import _html_confirmacion, _html_resumen


def main():
    parser = argparse.ArgumentParser(description="Vista previa HTML de los correos de LicitIA")
    parser.add_argument("--salida", type=Path, default=Path("/tmp/licitia-correos"),
                        help="Carpeta de salida para los HTML (por defecto /tmp/licitia-correos)")
    argumentos = parser.parse_args()
    argumentos.salida.mkdir(parents=True, exist_ok=True)
    ejemplos = [
        {"titulo": "Servicio de mantenimiento de instalaciones", "ocid": "ocds-demo-001", "cierre": "2026-12-12"},
        {"titulo": "Adquisición de equipamiento informático", "ocid": "ocds-demo-002", "cierre": None},
    ]
    archivos = {
        "confirmacion.html": _html_confirmacion("CODIGO-DE-EJEMPLO-123456", "semanal"),
        "resumen.html": _html_resumen(ejemplos, "CANCELACION-DE-EJEMPLO-123456", "semanal"),
    }
    for nombre, contenido in archivos.items():
        ruta = argumentos.salida / nombre
        ruta.write_text(contenido, encoding="utf-8")
        print(ruta)
    print("Solo vistas previas con datos ficticios. No se envió ningún correo.")


if __name__ == "__main__":
    main()
