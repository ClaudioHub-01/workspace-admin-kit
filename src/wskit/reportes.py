"""Exporta la auditoría a Excel (para trabajar) y a HTML (para presentar al cliente)."""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .auditoria import ResultadoAuditoria

AZUL = "1A73E8"
COLORES_SEVERIDAD = {"Alta": "F8D7DA", "Media": "FFF3CD", "Baja": "E2E3E5"}


# ------------------------------------------------------------------ Excel
def _tabla(ws, df: pd.DataFrame, fila: int, nombre: str, formatos: dict | None = None) -> None:
    formatos = formatos or {}
    for j, col in enumerate(df.columns, start=1):
        ws.cell(row=fila, column=j, value=str(col).replace("_", " ").capitalize())
    for i, registro in enumerate(df.itertuples(index=False), start=fila + 1):
        for j, valor in enumerate(registro, start=1):
            if isinstance(valor, bool):
                valor = "Sí" if valor else "No"
            elif valor is None or (pd.api.types.is_scalar(valor) and pd.isna(valor)):
                valor = None
            celda = ws.cell(row=i, column=j, value=valor)
            if df.columns[j - 1] in formatos:
                celda.number_format = formatos[df.columns[j - 1]]
    if len(df):
        ref = f"A{fila}:{get_column_letter(len(df.columns))}{fila + len(df)}"
        t = Table(displayName=nombre, ref=ref)
        t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
        ws.add_table(t)
    for j, col in enumerate(df.columns, start=1):
        largo = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)])
        ws.column_dimensions[get_column_letter(j)].width = min(60, max(10, largo + 3))
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)


def _encabezado(ws, titulo: str, sub: str) -> None:
    ws["A1"], ws["A2"] = titulo, sub
    ws["A1"].font = Font(size=16, bold=True, color=AZUL)
    ws["A2"].font = Font(size=10, italic=True, color="5F6368")
    ws.sheet_view.showGridLines = False


def exportar_excel(r: ResultadoAuditoria, destino: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    _encabezado(ws, f"Auditoría Google Workspace · {r.dominio}", f"Generada el {r.fecha:%d-%m-%Y %H:%M}")
    kpis = [("Puntaje de seguridad", f"{r.puntaje}/100"), ("Usuarios", len(r.usuarios)),
            ("Ahorro mensual posible (USD)", round(r.ahorro_mensual, 2)),
            ("Archivos expuestos", len(r.archivos_riesgo))]
    for j, (k, v) in enumerate(kpis):
        c = 1 + j * 2
        ws.cell(row=4, column=c, value=k).font = Font(bold=True, color="FFFFFF")
        ws.cell(row=4, column=c).fill = PatternFill("solid", fgColor=AZUL)
        ws.cell(row=5, column=c, value=v).font = Font(size=16, bold=True, color=AZUL)
        for f in (4, 5):
            ws.merge_cells(start_row=f, start_column=c, end_row=f, end_column=c + 1)
            ws.cell(row=f, column=c).alignment = Alignment(horizontal="center")
    hallazgos = pd.DataFrame([h.__dict__ for h in r.hallazgos])
    ws["A7"] = "Hallazgos y recomendaciones"
    ws["A7"].font = Font(size=12, bold=True, color=AZUL)
    _tabla(ws, hallazgos, 8, "TablaHallazgos")
    for i, sev in enumerate(hallazgos.get("severidad", []), start=9):
        ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor=COLORES_SEVERIDAD.get(sev, "FFFFFF"))
    ws.freeze_panes = None

    hojas = [
        ("Usuarios", "Estado de todas las cuentas", r.usuarios, "TablaUsuarios", {"ultimo_acceso": "DD-MM-YYYY"}),
        ("Licencias", "Licencias asignadas y recuperables", r.licencias, "TablaLicencias",
         {"costo_mensual": '"US$"#,##0.00'}),
        ("Drive expuesto", "Archivos públicos o compartidos fuera de la organización", r.archivos_riesgo,
         "TablaDrive", {}),
    ]
    for titulo, sub, df, nombre, fmt in hojas:
        h = wb.create_sheet(titulo)
        _encabezado(h, titulo, sub)
        _tabla(h, df, 4, nombre, fmt)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)


# ------------------------------------------------------------------ HTML
def _barras(conteo: pd.Series, total: int, colores: dict[str, str] | None = None) -> str:
    colores = colores or {}
    filas = []
    for etiqueta, valor in conteo.items():
        pct = 100 * valor / total if total else 0
        color = colores.get(etiqueta, "var(--azul)")
        filas.append(
            f'<div class="barra"><span class="et">{html.escape(str(etiqueta))}</span>'
            f'<span class="pista"><span class="relleno" style="width:{pct:.1f}%;background:{color}"></span></span>'
            f'<span class="val">{valor} <small>({pct:.0f}%)</small></span></div>'
        )
    return "\n".join(filas)


def exportar_html(r: ResultadoAuditoria, destino: Path) -> None:
    u = r.usuarios
    activos = u[u["estado"] != "Suspendido"]
    pct_2sv = 100 * activos["verificacion_2_pasos"].mean() if len(activos) else 0
    color_puntaje = "#188038" if r.puntaje >= 80 else "#E37400" if r.puntaje >= 60 else "#D93025"
    estados = u["estado"].value_counts()
    colores_estado = {"Activo": "#188038", "Inactivo": "#E37400", "Nunca ha ingresado": "#9AA0A6",
                      "Suspendido": "#D93025"}
    por_unidad = (activos.groupby("unidad")["verificacion_2_pasos"].mean() * 100).sort_values()
    unidades_2sv = "\n".join(
        f'<div class="barra"><span class="et">{html.escape(k)}</span><span class="pista">'
        f'<span class="relleno" style="width:{v:.0f}%;background:{"#188038" if v >= 80 else "#E37400" if v >= 50 else "#D93025"}">'
        f'</span></span><span class="val">{v:.0f}%</span></div>' for k, v in por_unidad.items())
    hallazgos = "\n".join(
        f'<tr><td><span class="sev {h.severidad.lower()}">{h.severidad}</span></td><td>{h.categoria}</td>'
        f'<td>{html.escape(h.descripcion)}</td><td class="num">{h.cantidad}</td>'
        f'<td>{html.escape(h.recomendacion)}</td></tr>' for h in r.hallazgos)
    top = r.archivos_riesgo.head(10)
    archivos = "\n".join(
        f'<tr><td><span class="sev {f.riesgo.lower()}">{f.riesgo}</span></td><td>{html.escape(f.archivo)}</td>'
        f'<td>{html.escape(f.dueño)}</td><td>{html.escape(f.exposición)}</td><td>{f.permiso}</td></tr>'
        for f in top.itertuples()) if not top.empty else '<tr><td colspan="5">Sin archivos expuestos</td></tr>'
    recuperables = r.licencias[r.licencias["recuperable"]]

    pagina = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Auditoría Google Workspace · {html.escape(r.dominio)}</title>
<style>
:root{{--azul:#1A73E8;--texto:#202124;--suave:#5F6368;--borde:#DADCE0;--fondo:#F8F9FA}}
*{{box-sizing:border-box}}body{{margin:0;font-family:"Segoe UI",Roboto,Arial,sans-serif;color:var(--texto);background:var(--fondo)}}
header{{background:var(--azul);color:#fff;padding:28px 40px}}header h1{{margin:0;font-size:24px}}header p{{margin:4px 0 0;opacity:.85}}
main{{max-width:1100px;margin:0 auto;padding:24px 20px 48px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:-44px}}
.kpi{{background:#fff;border-radius:12px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,.12)}}
.kpi small{{color:var(--suave);font-size:13px}}.kpi b{{display:block;font-size:30px;margin-top:6px}}
section{{background:#fff;border-radius:12px;padding:20px 24px;margin-top:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
h2{{font-size:17px;margin:0 0 14px;color:var(--azul)}}.dos{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.dos section{{margin-top:0}}@media(max-width:800px){{.dos{{grid-template-columns:1fr}}header{{padding:24px 16px}}}}
.barra{{display:grid;grid-template-columns:150px 1fr 90px;align-items:center;gap:10px;margin:8px 0;font-size:14px}}
.pista{{background:#EEF0F2;border-radius:6px;height:14px;overflow:hidden}}.relleno{{display:block;height:100%;border-radius:6px}}
.val{{text-align:right;font-variant-numeric:tabular-nums}}.val small{{color:var(--suave)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th{{text-align:left;color:var(--suave);font-weight:600;border-bottom:2px solid var(--borde);padding:8px}}
td{{border-bottom:1px solid var(--borde);padding:9px 8px;vertical-align:top}}td.num{{text-align:right;font-weight:600}}
.tabla{{overflow-x:auto}}.sev{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}}
.alta{{background:#FCE8E6;color:#C5221F}}.media{{background:#FEF7E0;color:#B06000}}.baja{{background:#F1F3F4;color:#5F6368}}
footer{{text-align:center;color:var(--suave);font-size:12px;margin-top:28px}}
</style></head><body>
<header><h1>Auditoría de Google Workspace</h1><p>{html.escape(r.dominio)} · {r.fecha:%d-%m-%Y %H:%M}</p></header>
<main>
<div class="kpis">
  <div class="kpi"><small>Puntaje de seguridad</small><b style="color:{color_puntaje}">{r.puntaje}<small>/100</small></b></div>
  <div class="kpi"><small>Usuarios con verificación en 2 pasos</small><b>{pct_2sv:.0f}%</b></div>
  <div class="kpi"><small>Ahorro mensual posible en licencias</small><b>US${r.ahorro_mensual:,.0f}</b></div>
  <div class="kpi"><small>Archivos expuestos en Drive</small><b>{len(r.archivos_riesgo)}</b></div>
</div>
<section><h2>Hallazgos y recomendaciones</h2><div class="tabla"><table>
<tr><th>Severidad</th><th>Área</th><th>Hallazgo</th><th>Cant.</th><th>Recomendación</th></tr>
{hallazgos}</table></div></section>
<div class="dos" style="margin-top:20px">
<section><h2>Estado de las cuentas ({len(u)})</h2>{_barras(estados, len(u), colores_estado)}</section>
<section><h2>Verificación en 2 pasos por unidad</h2>{unidades_2sv}</section>
</div>
<section><h2>Licencias recuperables ({len(recuperables)})</h2>{_barras(recuperables["licencia"].str.replace("Google Workspace ", "").value_counts(), len(recuperables))}
<p style="color:var(--suave);font-size:13px">Costo referencial; ajustar según el contrato del cliente.</p></section>
<section><h2>Archivos más expuestos (top 10 de {len(r.archivos_riesgo)})</h2><div class="tabla"><table>
<tr><th>Riesgo</th><th>Archivo</th><th>Dueño</th><th>Exposición</th><th>Permiso</th></tr>
{archivos}</table></div></section>
<footer>Generado automáticamente con Workspace Admin Kit · El detalle completo está en el archivo Excel.</footer>
</main></body></html>"""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf-8")
