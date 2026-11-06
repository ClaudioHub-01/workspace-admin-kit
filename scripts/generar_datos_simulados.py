"""
Genera un dominio de Google Workspace SIMULADO para probar el kit sin una cuenta real.

Crea en data/simulado/:
  - usuarios.json   -> con la misma estructura que devuelve la Admin SDK (Directory API)
  - licencias.json  -> como la Enterprise License Manager API
  - drive.json      -> archivos con sus permisos, como la Drive API v3
y en data/:
  - ejemplo_altas.xlsx -> planilla de alta masiva con algunos errores a propósito

Todos los nombres, correos y archivos son ficticios. El dominio usa el sufijo
reservado ".example", que no existe en internet.

Uso:
    python scripts/generar_datos_simulados.py
"""
from __future__ import annotations

import json
import random
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

SEED = 7
DOMINIO = "losandes.example"
RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "data" / "simulado"

NOMBRES = ["Ana", "Pedro", "Camila", "Luis", "Javiera", "Matías", "Fernanda", "Diego", "Valentina",
           "Tomás", "Catalina", "Benjamín", "Francisca", "Joaquín", "Constanza", "Nicolás", "Daniela",
           "Sebastián", "Antonia", "Felipe", "Isidora", "Vicente", "Martina", "Cristóbal", "Josefa"]
APELLIDOS = ["Rojas", "Soto", "Díaz", "Muñoz", "Pérez", "Vera", "Silva", "González", "Contreras",
             "Morales", "Fuentes", "Castillo", "Tapia", "Reyes", "Araya", "Espinoza", "Valenzuela",
             "Carrasco", "Sepúlveda", "Herrera"]
UNIDADES = {"/Administración": 14, "/Ventas": 38, "/Operaciones": 30, "/TI": 8, "/Gerencia": 6, "/Bodega": 24}
SKUS = [("1010020027", "Google Workspace Business Starter"),
        ("1010020028", "Google Workspace Business Standard"),
        ("1010020025", "Google Workspace Business Plus")]
DOMINIOS_EXTERNOS = ["gmail.com", "hotmail.com", "proveedor-sur.example", "contadores-asociados.example", "outlook.com"]
DOCUMENTOS = ["Planilla de sueldos {m}", "Cotización cliente {n}", "Contrato proveedor {n}", "Inventario bodega {m}",
              "Presentación ventas {m}", "Base de clientes {m}", "Respaldo facturas {m}", "Acta reunión {n}",
              "Lista de precios {m}", "Claves wifi sucursal", "Evaluaciones de desempeño {m}", "Plan comercial {m}"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre"]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def _usuarios(ahora: datetime) -> list[dict]:
    usuarios, usados = [], set()
    for unidad, cantidad in UNIDADES.items():
        for _ in range(cantidad):
            while True:
                nombre, apellido = random.choice(NOMBRES), random.choice(APELLIDOS)
                correo = f"{_sin_tildes(nombre)}.{_sin_tildes(apellido)}@{DOMINIO}"
                if correo not in usados:
                    usados.add(correo)
                    break
            creado = ahora - timedelta(days=random.randint(60, 1500))
            perfil = random.choices(["activo", "inactivo", "nunca", "suspendido"], weights=[78, 12, 4, 6])[0]
            if perfil == "activo":
                ultimo = ahora - timedelta(days=random.randint(0, 25), hours=random.randint(0, 23))
            elif perfil in ("inactivo", "suspendido"):
                ultimo = ahora - timedelta(days=random.randint(65, 400))
            else:
                ultimo = None
            admin = unidad == "/TI" and random.random() < 0.5 or unidad == "/Gerencia" and random.random() < 0.2
            dos_pasos = random.random() < (0.85 if unidad in ("/TI", "/Gerencia") else 0.55)
            usuarios.append({
                "primaryEmail": correo,
                "name": {"givenName": nombre, "familyName": apellido, "fullName": f"{nombre} {apellido}"},
                "orgUnitPath": unidad,
                "isAdmin": admin,
                "suspended": perfil == "suspendido",
                "isEnrolledIn2Sv": dos_pasos,
                "isEnforcedIn2Sv": False,
                "creationTime": _iso(creado),
                # la API real devuelve 1970-01-01 cuando el usuario nunca ha iniciado sesión
                "lastLoginTime": _iso(ultimo) if ultimo else "1970-01-01T00:00:00.000Z",
            })
    # caso típico de auditoría: algunos administradores sin verificación en dos pasos
    for admin in [u for u in usuarios if u["isAdmin"]][:2]:
        admin["isEnrolledIn2Sv"] = False
    return usuarios


def _licencias(usuarios: list[dict]) -> list[dict]:
    items = []
    for u in usuarios:
        if u["orgUnitPath"] == "/Bodega" and random.random() < 0.6:
            sku = SKUS[0]
        elif u["orgUnitPath"] in ("/Gerencia", "/TI"):
            sku = SKUS[2] if random.random() < 0.5 else SKUS[1]
        else:
            sku = SKUS[1] if random.random() < 0.8 else SKUS[0]
        items.append({"productId": "Google-Apps", "skuId": sku[0], "skuName": sku[1], "userId": u["primaryEmail"]})
    return items


def _drive(usuarios: list[dict], ahora: datetime) -> list[dict]:
    archivos = []
    activos = [u for u in usuarios if not u["suspended"]]
    for i in range(420):
        dueno = random.choice(activos)["primaryEmail"]
        plantilla = random.choice(DOCUMENTOS)
        nombre = plantilla.format(m=random.choice(MESES), n=random.randint(100, 999))
        tipo = random.choice(["spreadsheet", "document", "presentation", "pdf"])
        permisos = [{"type": "user", "role": "owner", "emailAddress": dueno}]
        for _ in range(random.randint(0, 3)):  # compartido internamente
            permisos.append({"type": "user", "role": random.choice(["reader", "writer"]),
                             "emailAddress": random.choice(usuarios)["primaryEmail"]})
        riesgo = random.random()
        if riesgo < 0.07:
            permisos.append({"type": "anyone", "role": random.choice(["reader", "writer"]), "allowFileDiscovery": False})
        elif riesgo < 0.16:
            correo_ext = f"{_sin_tildes(random.choice(NOMBRES))}{random.randint(1, 99)}@{random.choice(DOMINIOS_EXTERNOS)}"
            permisos.append({"type": "user", "role": random.choice(["reader", "writer"]), "emailAddress": correo_ext})
        elif riesgo < 0.20:
            permisos.append({"type": "domain", "role": "reader", "domain": DOMINIO, "allowFileDiscovery": True})
        archivos.append({
            "id": f"sim{i:05d}",
            "name": nombre,
            "mimeType": f"application/vnd.google-apps.{tipo}" if tipo != "pdf" else "application/pdf",
            "owners": [{"emailAddress": dueno}],
            "modifiedTime": _iso(ahora - timedelta(days=random.randint(0, 700))),
            "webViewLink": f"https://drive.google.com/file/d/sim{i:05d}/view",
            "permissions": permisos,
        })
    return archivos


def _planilla_altas(usuarios: list[dict]) -> pd.DataFrame:
    existente = usuarios[3]
    filas = [
        ("Rocío", "Navarro", "rocio.navarro", "/Ventas", "Business Standard"),
        ("Gabriel", "Ortiz", "gabriel.ortiz", "/Operaciones", "Business Standard"),
        ("Paula", "Leiva", "paula.leiva", "/Bodega", "Business Starter"),
        ("Ignacio", "Bravo", "ignacio.bravo", "/TI", "Business Plus"),
        ("Emilia", "Cortés", "emilia.cortes", "/Administración", "Business Standard"),
        (existente["name"]["givenName"], existente["name"]["familyName"],
         existente["primaryEmail"].split("@")[0], "/Ventas", "Business Standard"),  # ya existe
        ("Agustín", "Pizarro", "agustin pizarro", "/Ventas", "Business Standard"),  # usuario inválido
        ("Trinidad", "Lagos", "trinidad.lagos", "/Marketing", "Business Standard"),  # unidad no existe
        ("Rocío", "Navarro", "rocio.navarro", "/Ventas", "Business Standard"),  # duplicada en la planilla
        ("", "Salinas", "m.salinas", "/Bodega", "Business Starter"),  # falta nombre
        ("Maximiliano", "Toro", "maximiliano.toro", "/Bodega", "Business Starter"),
        ("Florencia", "Medina", "florencia.medina", "/Ventas", "Business Ultra"),  # licencia no existe
    ]
    return pd.DataFrame(filas, columns=["Nombre", "Apellido", "Usuario", "Unidad organizativa", "Licencia"])


def main() -> None:
    random.seed(SEED)
    ahora = datetime.now(timezone.utc)
    DESTINO.mkdir(parents=True, exist_ok=True)
    usuarios = _usuarios(ahora)
    datos = {
        "usuarios.json": {"dominio": DOMINIO, "generado": _iso(ahora), "users": usuarios},
        "licencias.json": {"items": _licencias(usuarios)},
        "drive.json": {"files": _drive(usuarios, ahora)},
    }
    for nombre, contenido in datos.items():
        (DESTINO / nombre).write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    _planilla_altas(usuarios).to_excel(RAIZ / "data" / "ejemplo_altas.xlsx", index=False)
    print(f"Dominio simulado '{DOMINIO}': {len(usuarios)} usuarios, {len(datos['drive.json']['files'])} archivos.")
    print(f"Archivos en {DESTINO} y data/ejemplo_altas.xlsx")


if __name__ == "__main__":
    main()
