"""Construccion del informe Excel de novedades.

Vive en services y no en el router a proposito: sin FastAPI ni base de
datos por medio, el libro se puede probar directamente. Antes estaba
dentro de la ruta y cualquier test tenia que arrastrar todo el stack web.
"""
import io
from typing import List


def construir_libro_excel(filas: List[dict]) -> io.BytesIO:
    """Arma el .xlsx a partir de las filas ya calculadas.

    Separada de la ruta a proposito: asi se puede probar el libro sin
    levantar FastAPI ni una base de datos.
    """
    import xlsxwriter
    from datetime import date as _date, datetime as _datetime

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})

    header_fmt = workbook.add_format({
        "bold": True, "bg_color": "#2C4770", "font_color": "white",
        "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy"})
    money_fmt = workbook.add_format({"num_format": "#,##0.00"})
    qty_fmt = workbook.add_format({"num_format": "#,##0.00"})
    tot_lbl_fmt = workbook.add_format({"bold": True, "top": 1})
    tot_num_fmt = workbook.add_format({"bold": True, "top": 1, "num_format": "#,##0.00"})

    CABECERA = [
        ("Cédula", "cedula"), ("Nombre Empleado", "nombre_empleado"),
        ("Área", "area"), ("Cargo", "cargo"),
        ("Tipo Novedad", "tipo_novedad"), ("Categoría", "categoria"),
        ("Fecha Inicio", "fecha_inicio"), ("Fecha Fin", "fecha_fin"),
    ]
    COLA = [
        ("Período", "periodo"), ("Estado", "estado"),
        ("Archivo Origen", "archivo_origen"), ("Hoja", "hoja_origen"),
    ]

    def _escribir_celda(ws, r, c, clave, valor):
        if valor is None or valor == "":
            ws.write_blank(r, c, None)
        elif clave in ("fecha_inicio", "fecha_fin"):
            if isinstance(valor, (_datetime, _date)):
                ws.write_datetime(r, c, valor, date_fmt)
            else:
                ws.write(r, c, str(valor))
        else:
            ws.write(r, c, str(valor))

    def _hoja(nombre, filas_hoja, cantidades):
        """`cantidades` es una lista de (titulo, unidad) — la celda solo se
        rellena cuando la fila trae esa unidad, para no mezclar horas con dias
        en una misma columna."""
        ws = workbook.add_worksheet(nombre)
        columnas = CABECERA + [(t, None) for t, _ in cantidades] + [("Valor (COP)", None)] + COLA
        for c, (titulo, _) in enumerate(columnas):
            ws.write(0, c, titulo, header_fmt)
            ws.set_column(c, c, 26 if c in (1, 2, 3, 4) else 15)
        ws.freeze_panes(1, 0)
        if filas_hoja:
            ws.autofilter(0, 0, len(filas_hoja), len(columnas) - 1)

        totales = [0.0] * len(cantidades)
        total_valor = 0.0
        for r, fila in enumerate(filas_hoja, start=1):
            c = 0
            for _, clave in CABECERA:
                _escribir_celda(ws, r, c, clave, fila.get(clave))
                c += 1
            for i, (_, unidad) in enumerate(cantidades):
                if fila.get("unidad") == unidad and fila.get("dias") is not None:
                    cantidad = float(fila["dias"])
                    ws.write_number(r, c, cantidad, qty_fmt)
                    totales[i] += cantidad
                else:
                    ws.write_blank(r, c, None)
                c += 1
            valor = fila.get("valor_calculado")
            if valor is None:
                ws.write_blank(r, c, None)
            else:
                ws.write_number(r, c, float(valor), money_fmt)
                total_valor += float(valor)
            c += 1
            for _, clave in COLA:
                _escribir_celda(ws, r, c, clave, fila.get(clave))
                c += 1

        # Fila de totales: solo suma lo que es sumable dentro de su unidad.
        if filas_hoja:
            r = len(filas_hoja) + 1
            ws.write(r, 0, "TOTAL", tot_lbl_fmt)
            for c in range(1, len(CABECERA)):
                ws.write_blank(r, c, None, tot_lbl_fmt)
            c = len(CABECERA)
            for total in totales:
                ws.write_number(r, c, total, tot_num_fmt)
                c += 1
            ws.write_number(r, c, total_valor, tot_num_fmt)

    horas = [f for f in filas if f.get("unidad") == "horas"]
    dias_ = [f for f in filas if f.get("unidad") == "dias"]

    # Hoja consolidada: horas y dias en columnas distintas, nunca en la misma.
    _hoja("Novedades", filas, [("Horas", "horas"), ("Días", "dias")])
    # Y las dos vistas segregadas que pidio el area de nomina.
    _hoja("Horas extras y recargos", horas, [("Horas", "horas")])
    _hoja("Ausencias y días", dias_, [("Días", "dias")])

    workbook.close()
    output.seek(0)
    return output
