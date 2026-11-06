"""
Workspace Admin Kit - línea de comandos.

Ejemplos (modo simulado, sin cuenta real):
    wskit auditar
    wskit auditar --sin-drive --dias 90
    wskit alta-masiva data/ejemplo_altas.xlsx
    wskit alta-masiva data/ejemplo_altas.xlsx --aplicar

Contra un dominio real (ver README > "Conectar a un dominio real"):
    wskit --modo google auditar
"""
from __future__ import annotations

import argparse
import logging
import sys
import tomllib
from datetime import datetime
from pathlib import Path

log = logging.getLogger("wskit")


def _config(ruta: Path) -> dict:
    if ruta.exists():
        with ruta.open("rb") as f:
            return tomllib.load(f)
    return {}


def _cliente(args, cfg: dict):
    if args.modo == "simulado":
        from .clientes import ClienteSimulado

        return ClienteSimulado(Path(cfg.get("simulado", {}).get("carpeta", "data/simulado")))
    from .clientes import ClienteGoogle

    g = cfg.get("google", {})
    faltan = [k for k in ("credenciales", "admin", "dominio") if not g.get(k)]
    if faltan:
        raise RuntimeError(f"Completa la sección [google] de config.toml: falta {', '.join(faltan)}")
    return ClienteGoogle(Path(g["credenciales"]), g["admin"], g["dominio"])


def cmd_auditar(args, cfg: dict) -> None:
    from .auditoria import PRECIOS_REFERENCIALES, auditar
    from .reportes import exportar_excel, exportar_html

    cliente = _cliente(args, cfg)
    precios = {**PRECIOS_REFERENCIALES, **cfg.get("precios", {})}
    dias = args.dias or cfg.get("auditoria", {}).get("dias_inactividad", 60)
    log.info("Auditando %s (modo %s)...", cliente.dominio, args.modo)
    r = auditar(cliente, dias_inactividad=dias, precios=precios, revisar_drive=not args.sin_drive)

    marca = datetime.now().strftime("%Y%m%d_%H%M")
    excel = args.salida / f"auditoria_{marca}.xlsx"
    pagina = args.salida / f"auditoria_{marca}.html"
    exportar_excel(r, excel)
    exportar_html(r, pagina)

    log.info("Puntaje de seguridad: %s/100", r.puntaje)
    for h in r.hallazgos:
        log.info("  [%-5s] %-55s %4d", h.severidad, h.descripcion, h.cantidad)
    log.info("Ahorro mensual posible en licencias: US$%.2f", r.ahorro_mensual)
    log.info("Reportes: %s  |  %s", excel, pagina)


def cmd_alta(args, cfg: dict) -> None:
    from .alta_masiva import aplicar, leer_planilla, validar

    cliente = _cliente(args, cfg)
    resultado = validar(leer_planilla(args.planilla), cliente)
    for f in resultado.filas.to_dict("records"):
        if f["estado"] == "OK":
            log.info("  Fila %-3s OK     %s", f["fila_excel"], f["correo"])
        else:
            log.warning("  Fila %-3s ERROR  %s -> %s", f["fila_excel"], f["correo"], f["detalle"])
    log.info("%d filas válidas, %d con errores.", resultado.validas, resultado.con_error)

    marca = datetime.now().strftime("%Y%m%d_%H%M")
    args.salida.mkdir(parents=True, exist_ok=True)
    validacion = args.salida / f"alta_validacion_{marca}.xlsx"
    resultado.filas.drop(columns=["sku"]).to_excel(validacion, index=False)
    log.info("Detalle de la validación: %s", validacion)

    if not args.aplicar:
        log.info("Modo revisión: no se creó ningún usuario. Corrige los errores y usa --aplicar.")
        return
    credenciales = aplicar(resultado, cliente)
    archivo = args.salida / f"credenciales_temporales_{marca}.xlsx"
    credenciales.to_excel(archivo, index=False)
    sufijo = " (simulado: no se creó nada real)" if args.modo == "simulado" else ""
    log.info("%d usuarios creados%s.", resultado.creadas, sufijo)
    log.warning("Credenciales en %s: entrégalas por un canal seguro y borra el archivo después.", archivo)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    p = argparse.ArgumentParser(prog="wskit", description="Kit de administración para Google Workspace")
    p.add_argument("--modo", choices=["simulado", "google"], default="simulado",
                   help="simulado = datos de prueba (por defecto); google = dominio real")
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    p.add_argument("--salida", type=Path, default=Path("salida"))
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("auditar", help="Auditoría de usuarios, seguridad, licencias y Drive")
    a.add_argument("--dias", type=int, help="Días sin acceso para considerar una cuenta inactiva (60)")
    a.add_argument("--sin-drive", action="store_true", help="Omitir la revisión de Drive (más rápido)")
    a.set_defaults(func=cmd_auditar)

    b = sub.add_parser("alta-masiva", help="Crear usuarios desde una planilla Excel/CSV")
    b.add_argument("planilla", type=Path)
    b.add_argument("--aplicar", action="store_true", help="Crear los usuarios (sin esto solo se valida)")
    b.set_defaults(func=cmd_alta)

    args = p.parse_args()
    try:
        args.func(args, _config(args.config))
    except Exception as exc:  # noqa: BLE001
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
