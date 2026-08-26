"""Construccion del informe Excel de novedades.

Vive en services y no en el router a proposito: sin FastAPI ni base de
datos por medio, el libro se puede probar directamente. Antes estaba
dentro de la ruta y cualquier test tenia que arrastrar todo el stack web.
"""
import io
from typing import List, Optional


def construir_libro_excel(filas: List[dict], panel: Optional[str] = None) -> io.BytesIO:
    """Arma el .xlsx a partir de las filas ya calculadas.

    Separada de la ruta a proposito: asi se puede probar el libro sin
    levantar FastAPI ni una base de datos.

    Sin `panel` se arma el libro general: una hoja consolidada mas las dos
    segregadas. Con `panel` las filas ya vienen acotadas a una sola unidad, asi
    que se entrega UNA hoja: las otras dos saldrian vacias o duplicadas.
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

    if panel == "horas-extras":
        _hoja("Horas extras y recargos", filas, [("Horas", "horas")])
    elif panel == "ausentismo":
        _hoja("Ausencias y días", filas, [("Días", "dias")])
    else:
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


def construir_libro_nomina(filas: List[dict], periodo: Optional[str] = None,
                           smlmv: Optional[float] = None,
                           anio_smlmv: Optional[int] = None) -> io.BytesIO:
    """Reporte de nomina: una fila por empleado, con su salario y el neto.

    Las filas llegan ya liquidadas de nomina_report.armar_reporte. Aqui solo se
    dibuja: ningun calculo de dinero vive en esta funcion.

    `smlmv` y `anio_smlmv` solo se imprimen como constancia: el piso legal con
    el que se liquido tiene que quedar en el libro, porque cambia cada año y sin
    el dato no hay forma de auditar una cifra meses despues.
    """
    import xlsxwriter

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = workbook.add_worksheet("Reporte de nómina")

    header_fmt = workbook.add_format({
        "bold": True, "bg_color": "#2C4770", "font_color": "white",
        "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    aviso_fmt = workbook.add_format({"italic": True, "font_color": "#8A6D3B", "text_wrap": True})
    money_fmt = workbook.add_format({"num_format": "#,##0.00"})
    qty_fmt = workbook.add_format({"num_format": "#,##0.00"})
    neg_fmt = workbook.add_format({"num_format": "#,##0.00", "font_color": "#A9373B"})
    tot_lbl = workbook.add_format({"bold": True, "top": 1})
    tot_num = workbook.add_format({"bold": True, "top": 1, "num_format": "#,##0.00"})

    # El reporte no reemplaza una liquidacion oficial: conviene que quien lo
    # abra lo lea antes que las cifras.
    aviso = ("Prenómina de apoyo. No incluye aportes, retenciones, auxilio de transporte "
             "ni prestaciones. Las incapacidades se liquidan como origen común (EPS): un "
             "accidente laboral aparecerá por debajo del 100% que paga la ARL.")
    ws.merge_range(0, 0, 0, 13, aviso, aviso_fmt)
    ws.set_row(0, 28)
    if periodo:
        ws.write(1, 0, f"Período: {periodo}")
    if smlmv:
        etiqueta = f"SMLMV {anio_smlmv}" if anio_smlmv else "SMLMV"
        ws.write(2, 0, f"Piso legal aplicado: 1 {etiqueta} = {smlmv:,.0f} "
                       f"(día = {smlmv / 30:,.2f})")

    FILA_CAB = 3
    columnas = [
        ("Cédula", "cedula", "txt"), ("Nombre Empleado", "nombre_empleado", "txt"),
        ("Área", "area", "txt"), ("Cargo", "cargo", "txt"),
        ("Salario base", "salario", "money"),
        ("Novedades", "num_novedades", "qty"),
        ("Días incapacidad", "dias_incapacidad", "qty"),
        ("Días no remunerados", "dias_no_remunerados", "qty"),
        ("Días efectivos", "dias_efectivos", "qty"),
        ("Salario devengado", "salario_devengado", "money"),
        ("Horas extras y recargos", "valor_extras", "money"),
        ("Valor incapacidad", "valor_incapacidad", "money"),
        ("Otros pagos", "valor_otros_pagos", "money"),
        ("Total a pagar", "total_a_pagar", "money"),
        ("Diferencia vs salario", "diferencia_vs_salario", "dif"),
        ("Observaciones", "observaciones", "txt"),
    ]
    for c, (titulo, _, _) in enumerate(columnas):
        ws.write(FILA_CAB, c, titulo, header_fmt)
        ws.set_column(c, c, 30 if titulo == "Observaciones" else (24 if c in (1, 2, 3) else 16))
    ws.freeze_panes(FILA_CAB + 1, 0)
    if filas:
        ws.autofilter(FILA_CAB, 0, FILA_CAB + len(filas), len(columnas) - 1)

    sumables = {"salario", "salario_devengado", "valor_extras", "valor_incapacidad",
                "valor_otros_pagos", "total_a_pagar", "diferencia_vs_salario",
                "dias_incapacidad", "dias_no_remunerados"}
    totales = {k: 0.0 for k in sumables}

    for i, fila in enumerate(filas):
        r = FILA_CAB + 1 + i
        for c, (_, clave, tipo) in enumerate(columnas):
            v = fila.get(clave)
            if v is None or v == "":
                ws.write_blank(r, c, None)
                continue
            if tipo == "money":
                ws.write_number(r, c, float(v), money_fmt)
            elif tipo == "qty":
                ws.write_number(r, c, float(v), qty_fmt)
            elif tipo == "dif":
                ws.write_number(r, c, float(v), neg_fmt if float(v) < 0 else money_fmt)
            else:
                ws.write(r, c, str(v))
            if clave in sumables:
                totales[clave] += float(v)

    if filas:
        r = FILA_CAB + 1 + len(filas)
        ws.write(r, 0, "TOTAL", tot_lbl)
        for c, (_, clave, tipo) in enumerate(columnas):
            if c == 0:
                continue
            if clave in sumables:
                ws.write_number(r, c, totales[clave], tot_num)
            else:
                ws.write_blank(r, c, None, tot_lbl)

    workbook.close()
    output.seek(0)
    return output
