"""
Exportación de datos a Excel y PDF.
"""
import io
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_user_areas, require_permission
from app.services.permissions import PERM_EXPORT_EXCEL, PERM_EXPORT_PDF
from app.services import dashboard_service as svc
from app.services.excel_report import construir_libro_excel

router = APIRouter(prefix="/api/export", tags=["Exportación"])


@router.get("/excel", summary="Exportar datos a Excel")
async def export_excel(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[List[str]] = Query(None, description="Área. Repetir para varias: ?area=NOMINA&area=SST"),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_EXPORT_EXCEL)),
):
    filters = {
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "area": area,
        "tipo_novedad": tipo_novedad,
        "periodo": periodo,
        "cedula": None,
        "_allowed_areas": get_user_areas(current_user),
    }
    # Trae categoria y valor ya calculados con las mismas expresiones que
    # los paneles: el campo `valor` de la tabla se guarda nulo en la carga.
    output = construir_libro_excel(svc.get_export_rows(db, filters))
    filename = f"novedades_nomina_{periodo or 'todos'}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pdf", summary="Exportar resumen a PDF")
async def export_pdf(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[List[str]] = Query(None, description="Área. Repetir para varias: ?area=NOMINA&area=SST"),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM_EXPORT_PDF)),
):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from datetime import datetime

    filters = {
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "area": area,
        "tipo_novedad": tipo_novedad,
        "periodo": periodo,
        "cedula": None,
        "_allowed_areas": get_user_areas(current_user),
    }
    kpis = svc.get_kpis(db, filters)
    result = svc.get_table_data(db, filters, page=1, page_size=500)

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=1.5*cm, rightMargin=1.5*cm)
    styles = getSampleStyleSheet()
    elements = []

    # Título
    elements.append(Paragraph("Reporte de Novedades de Nómina", styles["Title"]))
    elements.append(Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 0.5*cm))

    # KPIs
    kpi_data = [
        ["Total Novedades", "Empleados", "Áreas", "Tipos", "Valor Total", "Prom. Días"],
        [
            str(kpis.total_novedades),
            str(kpis.total_empleados),
            str(kpis.total_areas),
            str(kpis.total_tipos_novedad),
            f"${kpis.valor_total:,.2f}",
            f"{kpis.promedio_dias:.1f}",
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[4*cm] * 6)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C4770")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 0.5*cm))

    # Tabla de datos (hasta 500 filas)
    headers = ["Cédula", "Nombre", "Área", "Tipo Novedad", "F. Inicio", "Días", "Valor", "Período"]
    keys = ["cedula", "nombre_empleado", "area", "tipo_novedad", "fecha_inicio", "dias", "valor", "periodo"]

    table_data = [headers]
    for row in result.data:
        table_data.append([
            str(row.get(k, "") or "") for k in keys
        ])

    col_widths = [2.5*cm, 5*cm, 4*cm, 4.5*cm, 2.5*cm, 1.5*cm, 3*cm, 2.5*cm]
    data_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    data_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF3FA")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    ]))
    elements.append(data_table)

    doc.build(elements)
    output.seek(0)

    filename = f"novedades_nomina_{periodo or 'todos'}.pdf"
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
