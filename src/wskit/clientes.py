"""
Capa de acceso a Google Workspace.

Hay dos implementaciones con la misma interfaz:
  - ClienteSimulado: lee los JSON de data/simulado (para demos y pruebas).
  - ClienteGoogle:   usa las APIs reales (Admin SDK, Licensing y Drive) con una
                     cuenta de servicio con delegación de todo el dominio.

El resto del kit no sabe con cuál está trabajando, así que todo lo que se
prueba en modo simulado funciona igual contra un dominio real.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

# Permisos mínimos que debe tener la cuenta de servicio (delegación de todo el dominio)
SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.orgunit.readonly",
    "https://www.googleapis.com/auth/apps.licensing",
    "https://www.googleapis.com/auth/drive.readonly",
]


class ClienteWorkspace(Protocol):
    dominio: str

    def usuarios(self) -> list[dict]: ...
    def licencias(self) -> list[dict]: ...
    def unidades(self) -> list[str]: ...
    def archivos_drive(self, usuarios: list[str]) -> list[dict]: ...
    def crear_usuario(self, cuerpo: dict) -> dict: ...
    def asignar_licencia(self, correo: str, sku_id: str) -> None: ...


class ClienteSimulado:
    """Lee un dominio ficticio desde archivos JSON (misma estructura que las APIs)."""

    def __init__(self, carpeta: Path = Path("data/simulado")):
        if not (carpeta / "usuarios.json").exists():
            raise FileNotFoundError(
                f"No hay datos simulados en {carpeta}. Ejecuta: python scripts/generar_datos_simulados.py"
            )
        self._carpeta = carpeta
        datos = self._leer("usuarios.json")
        self.dominio = datos["dominio"]
        self._usuarios = datos["users"]
        self.creados: list[dict] = []

    def _leer(self, nombre: str) -> dict:
        return json.loads((self._carpeta / nombre).read_text(encoding="utf-8"))

    def usuarios(self) -> list[dict]:
        return self._usuarios

    def licencias(self) -> list[dict]:
        return self._leer("licencias.json")["items"]

    def unidades(self) -> list[str]:
        return sorted({u["orgUnitPath"] for u in self._usuarios} | {"/"})

    def archivos_drive(self, usuarios: list[str]) -> list[dict]:
        incluidos = set(usuarios)
        return [f for f in self._leer("drive.json")["files"] if f["owners"][0]["emailAddress"] in incluidos]

    def crear_usuario(self, cuerpo: dict) -> dict:
        self.creados.append(cuerpo)  # en modo simulado no se escribe nada
        return {"primaryEmail": cuerpo["primaryEmail"], "simulado": True}

    def asignar_licencia(self, correo: str, sku_id: str) -> None:
        return None


class ClienteGoogle:
    """Cliente real. Requiere: pip install -e .[google] y un archivo de credenciales."""

    def __init__(self, credenciales: Path, admin: str, dominio: str):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Faltan librerías de Google. Ejecuta: pip install -e .[google]") from exc

        self._service_account = service_account
        self._build = build
        self._archivo = credenciales
        self.dominio = dominio
        self._cred_admin = self._credenciales(admin)
        self._directory = build("admin", "directory_v1", credentials=self._cred_admin, cache_discovery=False)
        self._licensing = build("licensing", "v1", credentials=self._cred_admin, cache_discovery=False)

    def _credenciales(self, sujeto: str):
        cred = self._service_account.Credentials.from_service_account_file(str(self._archivo), scopes=SCOPES)
        return cred.with_subject(sujeto)  # actúa en nombre de este usuario (delegación)

    @staticmethod
    def _paginar(peticion_fn, clave: str, **params) -> list[dict]:
        resultados, token = [], None
        while True:
            respuesta = peticion_fn(pageToken=token, **params).execute()
            resultados.extend(respuesta.get(clave, []))
            token = respuesta.get("nextPageToken")
            if not token:
                return resultados

    def usuarios(self) -> list[dict]:
        return self._paginar(self._directory.users().list, "users",
                             customer="my_customer", projection="full", maxResults=500)

    def licencias(self) -> list[dict]:
        return self._paginar(self._licensing.licenseAssignments().listForProduct, "items",
                             productId="Google-Apps", customerId=self.dominio, maxResults=1000)

    def unidades(self) -> list[str]:
        respuesta = self._directory.orgunits().list(customerId="my_customer", type="all").execute()
        return sorted({o["orgUnitPath"] for o in respuesta.get("organizationUnits", [])} | {"/"})

    def archivos_drive(self, usuarios: list[str]) -> list[dict]:
        campos = ("nextPageToken, files(id, name, mimeType, owners(emailAddress), modifiedTime, "
                  "webViewLink, permissions(type, role, emailAddress, domain, allowFileDiscovery))")
        archivos = []
        for correo in usuarios:  # se revisa el Drive de cada usuario actuando en su nombre
            drive = self._build("drive", "v3", credentials=self._credenciales(correo), cache_discovery=False)
            archivos.extend(self._paginar(drive.files().list, "files", q="'me' in owners and trashed = false",
                                          fields=campos, pageSize=1000))
        return archivos

    def crear_usuario(self, cuerpo: dict) -> dict:
        return self._directory.users().insert(body=cuerpo).execute()

    def asignar_licencia(self, correo: str, sku_id: str) -> None:
        self._licensing.licenseAssignments().insert(
            productId="Google-Apps", skuId=sku_id, body={"userId": correo}
        ).execute()
