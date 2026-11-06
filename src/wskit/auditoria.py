"""Reglas de auditoría: usuarios, seguridad, licencias y archivos compartidos en Drive."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

# Precios mensuales REFERENCIALES por licencia (USD, plan flexible).
# Verifica los valores vigentes de tu contrato y ajústalos en config.toml.
PRECIOS_REFERENCIALES = {
    "Google Workspace Business Starter": 7.0,
    "Google Workspace Business Standard": 14.0,
    "Google Workspace Business Plus": 22.0,
}
NUNCA = "1970-01-01"


@dataclass
class Hallazgo:
    severidad: str  # "Alta", "Media", "Baja"
    categoria: str
    descripcion: str
    cantidad: int
    recomendacion: str


@dataclass
class ResultadoAuditoria:
    dominio: str
    fecha: datetime
    usuarios: pd.DataFrame
    licencias: pd.DataFrame
    archivos_riesgo: pd.DataFrame
    hallazgos: list[Hallazgo] = field(default_factory=list)
    ahorro_mensual: float = 0.0
    puntaje: int = 100


def tabla_usuarios(usuarios: list[dict], dias_inactividad: int, ahora: datetime | None = None) -> pd.DataFrame:
    ahora = ahora or datetime.now(timezone.utc)
    filas = []
    for u in usuarios:
        ultimo_txt = u.get("lastLoginTime", NUNCA)
        nunca = ultimo_txt.startswith(NUNCA)
        ultimo = None if nunca else datetime.fromisoformat(ultimo_txt.replace("Z", "+00:00"))
        dias = None if nunca else (ahora - ultimo).days
        if u.get("suspended"):
            estado = "Suspendido"
        elif nunca:
            estado = "Nunca ha ingresado"
        elif dias > dias_inactividad:
            estado = "Inactivo"
        else:
            estado = "Activo"
        filas.append({
            "correo": u["primaryEmail"],
            "nombre": u.get("name", {}).get("fullName", ""),
            "unidad": u.get("orgUnitPath", "/"),
            "administrador": bool(u.get("isAdmin")),
            "verificacion_2_pasos": bool(u.get("isEnrolledIn2Sv")),
            "estado": estado,
            "ultimo_acceso": ultimo.date() if ultimo else None,
            "dias_sin_acceso": dias,
            "creado": u.get("creationTime", "")[:10],
        })
    return pd.DataFrame(filas)


def tabla_licencias(licencias: list[dict], usuarios: pd.DataFrame, precios: dict[str, float]) -> pd.DataFrame:
    lic = pd.DataFrame(licencias)
    if lic.empty:
        return pd.DataFrame(columns=["correo", "licencia", "costo_mensual", "estado", "recuperable"])
    lic = lic.rename(columns={"userId": "correo", "skuName": "licencia"})
    lic["correo"] = lic["correo"].str.lower()
    estados = usuarios.set_index(usuarios["correo"].str.lower())["estado"]
    lic["estado"] = lic["correo"].map(estados).fillna("Usuario no encontrado")
    lic["costo_mensual"] = lic["licencia"].map(precios).fillna(0.0)
    lic["recuperable"] = lic["estado"] != "Activo"
    return lic[["correo", "licencia", "skuId", "costo_mensual", "estado", "recuperable"]]


def archivos_en_riesgo(archivos: list[dict], dominio: str) -> pd.DataFrame:
    """Archivos públicos, compartidos con personas externas o visibles para todo el dominio."""
    filas = []
    for f in archivos:
        for p in f.get("permissions", []):
            tipo, correo = p.get("type"), p.get("emailAddress", "")
            if tipo == "anyone":
                nivel, riesgo, con = "Público (cualquiera con el enlace)", "Alta", "Cualquiera"
            elif tipo in ("user", "group") and correo and not correo.lower().endswith("@" + dominio):
                nivel, riesgo, con = "Compartido con externo", "Media", correo
            elif tipo == "domain" and p.get("domain") != dominio:
                nivel, riesgo, con = "Compartido con otro dominio", "Media", p.get("domain")
            elif tipo == "domain" and p.get("allowFileDiscovery"):
                nivel, riesgo, con = "Visible en búsqueda para todo el dominio", "Baja", dominio
            else:
                continue
            filas.append({
                "riesgo": riesgo,
                "archivo": f["name"],
                "dueño": f["owners"][0]["emailAddress"],
                "exposición": nivel,
                "compartido_con": con,
                "permiso": {"reader": "Lector", "writer": "Editor", "commenter": "Comentador"}.get(p.get("role"), p.get("role")),
                "modificado": f.get("modifiedTime", "")[:10],
                "enlace": f.get("webViewLink", ""),
            })
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    return df.sort_values(by=["riesgo", "archivo"], key=lambda s: s.map(orden) if s.name == "riesgo" else s)


def _hallazgos(usuarios: pd.DataFrame, lic: pd.DataFrame, riesgo: pd.DataFrame, dias: int) -> list[Hallazgo]:
    h = []
    activos = usuarios[usuarios["estado"] != "Suspendido"]
    admins_sin_2sv = activos[activos["administrador"] & ~activos["verificacion_2_pasos"]]
    if len(admins_sin_2sv):
        h.append(Hallazgo("Alta", "Seguridad", "Administradores sin verificación en dos pasos", len(admins_sin_2sv),
                          "Exigir 2SV a todas las cuentas con privilegios de administrador de inmediato."))
    publicos = riesgo[riesgo["riesgo"] == "Alta"] if not riesgo.empty else riesgo
    if len(publicos):
        h.append(Hallazgo("Alta", "Drive", "Archivos públicos (cualquiera con el enlace)", len(publicos),
                          "Revisar con cada dueño y restringir el acceso a personas específicas."))
    sin_2sv = activos[~activos["verificacion_2_pasos"] & ~activos["administrador"]]
    if len(sin_2sv):
        h.append(Hallazgo("Media", "Seguridad", "Usuarios sin verificación en dos pasos", len(sin_2sv),
                          "Activar 2SV obligatoria por unidad organizativa con un período de inscripción."))
    externos = riesgo[riesgo["riesgo"] == "Media"] if not riesgo.empty else riesgo
    if len(externos):
        h.append(Hallazgo("Media", "Drive", "Archivos compartidos con cuentas externas", len(externos),
                          "Validar que cada acceso externo siga siendo necesario."))
    recuperables = lic[lic["recuperable"]]
    if len(recuperables):
        h.append(Hallazgo("Media", "Licencias", "Licencias asignadas a cuentas suspendidas o inactivas",
                          len(recuperables), "Reasignar o liberar estas licencias para reducir el costo mensual."))
    inactivos = usuarios[usuarios["estado"] == "Inactivo"]
    if len(inactivos):
        h.append(Hallazgo("Baja", "Usuarios", f"Cuentas sin acceso hace más de {dias} días", len(inactivos),
                          "Confirmar con cada jefatura si la cuenta debe suspenderse."))
    nunca = usuarios[usuarios["estado"] == "Nunca ha ingresado"]
    if len(nunca):
        h.append(Hallazgo("Baja", "Usuarios", "Cuentas que nunca han iniciado sesión", len(nunca),
                          "Verificar si fueron creadas por error o si la persona necesita ayuda para ingresar."))
    return h


def _puntaje(usuarios: pd.DataFrame, riesgo: pd.DataFrame) -> int:
    """Puntaje simple de 0 a 100 (mientras más alto, mejor)."""
    activos = usuarios[usuarios["estado"] != "Suspendido"]
    if activos.empty:
        return 100
    p = 100.0
    p -= 40 * (1 - activos["verificacion_2_pasos"].mean())
    admins = activos[activos["administrador"]]
    if len(admins):
        p -= 20 * (1 - admins["verificacion_2_pasos"].mean())
    if not riesgo.empty:
        p -= min(25, 2.5 * (riesgo["riesgo"] == "Alta").sum() + 0.5 * (riesgo["riesgo"] == "Media").sum())
    p -= 15 * (activos["estado"].isin(["Inactivo", "Nunca ha ingresado"]).mean())
    return max(0, round(p))


def auditar(cliente, dias_inactividad: int = 60, precios: dict[str, float] | None = None,
            revisar_drive: bool = True) -> ResultadoAuditoria:
    precios = precios or PRECIOS_REFERENCIALES
    usuarios = tabla_usuarios(cliente.usuarios(), dias_inactividad)
    lic = tabla_licencias(cliente.licencias(), usuarios, precios)
    riesgo = pd.DataFrame()
    if revisar_drive:
        correos = usuarios.loc[usuarios["estado"] != "Suspendido", "correo"].tolist()
        riesgo = archivos_en_riesgo(cliente.archivos_drive(correos), cliente.dominio)
    resultado = ResultadoAuditoria(
        dominio=cliente.dominio,
        fecha=datetime.now(),
        usuarios=usuarios,
        licencias=lic,
        archivos_riesgo=riesgo,
        hallazgos=_hallazgos(usuarios, lic, riesgo, dias_inactividad),
        ahorro_mensual=float(lic.loc[lic["recuperable"], "costo_mensual"].sum()),
        puntaje=_puntaje(usuarios, riesgo),
    )
    return resultado
