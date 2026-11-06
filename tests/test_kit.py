from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from wskit.alta_masiva import aplicar, contrasena_temporal, validar
from wskit.auditoria import archivos_en_riesgo, auditar, tabla_licencias, tabla_usuarios

DOMINIO = "prueba.example"
AHORA = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _iso(dias_atras):
    return (AHORA - timedelta(days=dias_atras)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ClienteFalso:
    dominio = DOMINIO

    def __init__(self):
        self.creados = []

    def usuarios(self):
        return [
            {"primaryEmail": f"activo@{DOMINIO}", "lastLoginTime": _iso(3), "isAdmin": True, "isEnrolledIn2Sv": False},
            {"primaryEmail": f"inactivo@{DOMINIO}", "lastLoginTime": _iso(120), "isEnrolledIn2Sv": True},
            {"primaryEmail": f"nunca@{DOMINIO}", "lastLoginTime": "1970-01-01T00:00:00.000Z"},
            {"primaryEmail": f"suspendido@{DOMINIO}", "lastLoginTime": _iso(10), "suspended": True},
        ]

    def licencias(self):
        return [{"userId": u["primaryEmail"], "skuName": "Google Workspace Business Standard", "skuId": "1"}
                for u in self.usuarios()]

    def unidades(self):
        return ["/", "/Ventas"]

    def archivos_drive(self, usuarios):
        return []

    def crear_usuario(self, cuerpo):
        self.creados.append(cuerpo)

    def asignar_licencia(self, correo, sku):
        pass


def test_estados_de_usuario():
    df = tabla_usuarios(ClienteFalso().usuarios(), dias_inactividad=60, ahora=AHORA)
    assert df["estado"].tolist() == ["Activo", "Inactivo", "Nunca ha ingresado", "Suspendido"]


def test_licencias_recuperables_y_ahorro():
    c = ClienteFalso()
    usuarios = tabla_usuarios(c.usuarios(), 60, ahora=AHORA)
    lic = tabla_licencias(c.licencias(), usuarios, {"Google Workspace Business Standard": 14.0})
    assert lic["recuperable"].sum() == 3
    assert lic.loc[lic["recuperable"], "costo_mensual"].sum() == 42.0


def test_admin_sin_2sv_es_hallazgo_alto():
    r = auditar(ClienteFalso(), revisar_drive=False)
    assert r.hallazgos[0].severidad == "Alta"
    assert "Administradores" in r.hallazgos[0].descripcion


def test_clasificacion_de_archivos_expuestos():
    archivos = [{
        "name": "Doc", "owners": [{"emailAddress": f"a@{DOMINIO}"}],
        "permissions": [
            {"type": "user", "role": "owner", "emailAddress": f"a@{DOMINIO}"},  # interno: se ignora
            {"type": "anyone", "role": "reader"},
            {"type": "user", "role": "writer", "emailAddress": "x@gmail.com"},
            {"type": "domain", "role": "reader", "domain": DOMINIO, "allowFileDiscovery": True},
        ],
    }]
    df = archivos_en_riesgo(archivos, DOMINIO)
    assert df["riesgo"].tolist() == ["Alta", "Media", "Baja"]


def test_validacion_alta_masiva():
    planilla = pd.DataFrame([
        {"nombre": "Ana", "apellido": "Rojas", "usuario": "ana.rojas", "unidad": "/Ventas", "licencia": "Business Standard"},
        {"nombre": "Ana", "apellido": "Rojas", "usuario": "ana.rojas", "unidad": "/Ventas", "licencia": ""},
        {"nombre": "Luis", "apellido": "Soto", "usuario": "activo", "unidad": "/Ventas", "licencia": ""},
        {"nombre": "Eva", "apellido": "Paz", "usuario": "eva paz", "unidad": "/X", "licencia": "Ultra"},
    ])
    c = ClienteFalso()
    r = validar(planilla, c)
    assert r.filas["estado"].tolist() == ["OK", "Error", "Error", "Error"]
    assert "repetido" in r.filas.loc[1, "detalle"]
    assert "ya existe" in r.filas.loc[2, "detalle"]
    assert r.filas.loc[3, "detalle"].count(";") == 2  # tres errores en la misma fila
    cred = aplicar(r, c)
    assert len(c.creados) == 1 and c.creados[0]["changePasswordAtNextLogin"] is True
    assert len(cred) == 1


@pytest.mark.parametrize("_", range(20))
def test_contrasena_temporal_robusta(_):
    clave = contrasena_temporal()
    assert len(clave) == 14
    assert any(c.isupper() for c in clave) and any(c.isdigit() for c in clave)
