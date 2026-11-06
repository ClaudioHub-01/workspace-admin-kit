"""
Alta masiva de usuarios desde una planilla Excel o CSV.

Flujo seguro en dos pasos:
  1. Validación (por defecto): revisa cada fila y muestra qué se crearía, sin tocar nada.
  2. --aplicar: crea solo las filas válidas, asigna licencia y entrega contraseñas temporales.
"""
from __future__ import annotations

import re
import secrets
import string
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

COLUMNAS = {"nombre": "nombre", "apellido": "apellido", "usuario": "usuario",
            "unidad organizativa": "unidad", "unidad": "unidad", "licencia": "licencia"}
SKU_POR_NOMBRE = {
    "business starter": "1010020027",
    "business standard": "1010020028",
    "business plus": "1010020025",
}
PATRON_USUARIO = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,62}[a-z0-9])?$")


@dataclass
class ResultadoAlta:
    filas: pd.DataFrame
    validas: int
    con_error: int
    creadas: int = 0


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return texto.strip().lower()


def contrasena_temporal(largo: int = 14) -> str:
    """Contraseña aleatoria segura con mayúscula, minúscula, número y símbolo."""
    alfabeto = string.ascii_letters + string.digits + "!@#$%&*?"
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(largo))
        if (any(c.islower() for c in clave) and any(c.isupper() for c in clave)
                and any(c.isdigit() for c in clave) and any(c in "!@#$%&*?" for c in clave)):
            return clave


def leer_planilla(ruta: Path) -> pd.DataFrame:
    df = pd.read_excel(ruta, dtype=str) if ruta.suffix.lower() in (".xlsx", ".xls") \
        else pd.read_csv(ruta, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    df.columns = [COLUMNAS.get(_normalizar(c), _normalizar(c)) for c in df.columns]
    faltan = {"nombre", "apellido", "usuario", "unidad"} - set(df.columns)
    if faltan:
        raise ValueError(f"A la planilla le faltan columnas: {', '.join(sorted(faltan))}")
    if "licencia" not in df.columns:
        df["licencia"] = ""
    return df.fillna("").apply(lambda s: s.str.strip())


def validar(df: pd.DataFrame, cliente) -> ResultadoAlta:
    existentes = {u["primaryEmail"].lower() for u in cliente.usuarios()}
    unidades = set(cliente.unidades())
    vistos: set[str] = set()
    resultados = []
    for i, fila in enumerate(df.to_dict("records"), start=2):  # fila 2 = primera fila de datos en Excel
        errores = []
        usuario = _normalizar(fila["usuario"]).split("@")[0]
        correo = f"{usuario}@{cliente.dominio}"
        if not fila["nombre"]:
            errores.append("Falta el nombre")
        if not fila["apellido"]:
            errores.append("Falta el apellido")
        if not PATRON_USUARIO.match(usuario):
            errores.append("Usuario con caracteres no permitidos")
        elif correo in existentes:
            errores.append("El usuario ya existe en el dominio")
        elif correo in vistos:
            errores.append("Usuario repetido en la planilla")
        unidad = fila["unidad"] if fila["unidad"].startswith("/") else "/" + fila["unidad"]
        if unidad not in unidades:
            errores.append(f"La unidad {unidad} no existe")
        sku = None
        if fila["licencia"]:
            sku = SKU_POR_NOMBRE.get(_normalizar(fila["licencia"]).replace("google workspace ", ""))
            if not sku:
                errores.append(f"Licencia desconocida: {fila['licencia']}")
        vistos.add(correo)
        resultados.append({
            "fila_excel": i, "nombre": fila["nombre"], "apellido": fila["apellido"], "correo": correo,
            "unidad": unidad, "licencia": fila["licencia"], "sku": sku,
            "estado": "OK" if not errores else "Error", "detalle": "; ".join(errores),
        })
    filas = pd.DataFrame(resultados)
    validas = int((filas["estado"] == "OK").sum())
    return ResultadoAlta(filas=filas, validas=validas, con_error=len(filas) - validas)


def aplicar(resultado: ResultadoAlta, cliente) -> pd.DataFrame:
    """Crea los usuarios válidos. Devuelve las credenciales temporales generadas."""
    credenciales = []
    for fila in resultado.filas[resultado.filas["estado"] == "OK"].to_dict("records"):
        clave = contrasena_temporal()
        cliente.crear_usuario({
            "primaryEmail": fila["correo"],
            "name": {"givenName": fila["nombre"], "familyName": fila["apellido"]},
            "password": clave,
            "changePasswordAtNextLogin": True,  # obliga a cambiarla en el primer ingreso
            "orgUnitPath": fila["unidad"],
        })
        if fila["sku"]:
            cliente.asignar_licencia(fila["correo"], fila["sku"])
        credenciales.append({"nombre": f"{fila['nombre']} {fila['apellido']}", "correo": fila["correo"],
                             "contraseña_temporal": clave, "unidad": fila["unidad"]})
        resultado.creadas += 1
    return pd.DataFrame(credenciales)
