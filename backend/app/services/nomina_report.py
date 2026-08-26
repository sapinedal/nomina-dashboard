"""Liquidación de incapacidades según los tramos de la normativa colombiana.

Módulo puro: sin FastAPI, sin base de datos y sin dependencias externas, para
que el cálculo se pueda probar en cualquier entorno (mismo criterio que
excel_report.py). Aquí solo se decide CUÁNTO se paga; de dónde salen los días
y el salario es asunto de dashboard_service.

Alcance y límites, deliberados y acordados con el área de nómina:

- Se liquida todo como **incapacidad de origen común (EPS)**. La rama de origen
  laboral (ARL, 100% desde el día 1) NO se implementa porque el dato de origen
  no existe: solo se tiene el texto del tipo de novedad. Un accidente de
  trabajo se liquidará por debajo de lo que realmente paga la ARL.
- Los días 1 y 2, a cargo del empleador, se liquidan al mismo porcentaje que
  los días 3-90. Cambia quién paga, no cuánto.
- Más allá del día 180 la prestación corresponde a la AFP. Se liquida en 0 y se
  deja constancia, en vez de afirmar una cifra que la empresa no desembolsa.
- La liquidación va SIEMPRE sobre lo que gana cada empleado: su salario del
  roster / 30, por el porcentaje del tramo. El SMLMV no reemplaza ese salario.
- Sobre ese cálculo se aplica el piso legal de 1 SMLMV por día (SMLMV/30), y se
  aplica a TODOS, no solo a quien devenga el mínimo: la norma dice que ninguna
  incapacidad puede pagarse por debajo del salario mínimo diario vigente
  (Decreto 780 de 2016 art. 3.2.1.10; Sentencia C-543/2007). En la práctica el
  piso muerde por debajo de `SMLMV / 0,6667`: con el mínimo de 2026 eso son
  2.626.357, así que un salario de 2.000.000 cobra el piso (58.363,50/día) y no
  el 66,67% de su día (44.446,67). Confirmado con el área de nómina el
  2026-08-26.
- Ese umbral se mueve cada enero y NO es menor: el salto del 23% del mínimo de
  2026 metió bajo el piso a salarios que en 2025 se liquidaban al porcentaje.
  Por eso el SMLMV se toma del año del periodo (ver services/smlmv.py).
- Los días **solo se acumulan dentro de un mismo episodio continuo** (prórroga).
  Dos incapacidades separadas por un día o más se liquidan de forma
  independiente, cada una arrancando en el día 1. Sin diagnóstico en el dato,
  la continuidad de fechas es el único criterio defendible: sumar todo el
  historial empujaría al tramo del 50% a quien tuvo dos gripas en el año.
"""
from datetime import date, datetime, timedelta
from typing import Optional

# Días acumulados en que cambia el porcentaje.
LIMITE_TRAMO_66 = 90
LIMITE_TRAMO_50 = 180

# Convención de nómina: el mes se liquida sobre 30 días.
DIAS_MES = 30.0


def _solape(inicio_a: float, fin_a: float, inicio_b: float, fin_b: float) -> float:
    """Días en común entre dos intervalos. 0 si no se tocan."""
    return max(0.0, min(fin_a, fin_b) - max(inicio_a, inicio_b))


def liquidar_incapacidad(
    dias_previos: float,
    dias: float,
    salario_mensual: Optional[float],
    smlmv: float,
    pct_66: float = 0.6667,
    pct_50: float = 0.50,
) -> dict:
    """Liquida `dias` de incapacidad para alguien que ya acumulaba `dias_previos`.

    Reparte los días entre los tramos y **parte la novedad cuando cruza un
    límite**: quien va por el día 89 y pide 5 días cobra 1 al 66,67% y 4 al 50%.

    Devuelve un dict con el valor y el desglose, para que el reporte pueda
    mostrar de dónde sale cada cifra en vez de un número sin explicación.
    """
    if not dias or dias <= 0:
        return {"valor": 0.0, "dias_66": 0.0, "dias_50": 0.0,
                "dias_sin_pago": 0.0, "observaciones": []}

    if salario_mensual is None or salario_mensual <= 0:
        return {"valor": 0.0, "dias_66": 0.0, "dias_50": 0.0, "dias_sin_pago": dias,
                "observaciones": ["sin salario en Trazalo: no se puede liquidar"]}

    inicio = max(0.0, float(dias_previos or 0.0))
    fin = inicio + float(dias)

    dias_66 = _solape(inicio, fin, 0.0, LIMITE_TRAMO_66)
    dias_50 = _solape(inicio, fin, LIMITE_TRAMO_66, LIMITE_TRAMO_50)
    dias_sin_pago = _solape(inicio, fin, LIMITE_TRAMO_50, float("inf"))

    salario_dia = salario_mensual / DIAS_MES
    piso_dia = smlmv / DIAS_MES

    valor = (dias_66 * max(pct_66 * salario_dia, piso_dia)
             + dias_50 * max(pct_50 * salario_dia, piso_dia))

    observaciones = []
    if dias_66 and dias_50:
        observaciones.append(
            f"cruza el dia {LIMITE_TRAMO_66}: {dias_66:g}d al "
            f"{pct_66 * 100:.2f}% y {dias_50:g}d al {pct_50 * 100:.2f}%"
        )
    elif dias_50:
        observaciones.append(f"tramo {pct_50 * 100:.2f}% (dia 91-180)")
    if dias_sin_pago:
        observaciones.append(
            f"{dias_sin_pago:g}d superan el dia {LIMITE_TRAMO_50}: corresponden a la AFP, "
            f"no se liquidan aqui"
        )
    if piso_dia > pct_66 * salario_dia:
        observaciones.append("se aplico el piso de 1 SMLMV")

    return {
        "valor": round(valor, 2),
        "dias_66": dias_66,
        "dias_50": dias_50,
        "dias_sin_pago": dias_sin_pago,
        "observaciones": observaciones,
    }


def armar_reporte(
    filas: list,
    incapacidades_por_cedula: dict,
    smlmv: float,
    pct_66: float = 0.6667,
    pct_50: float = 0.50,
) -> list:
    """Cruza el agregado de novedades de cada empleado con su salario y liquida.

    Puro a proposito: recibe las filas ya consultadas y devuelve las filas ya
    calculadas, sin tocar la base de datos. Asi el reporte se puede probar
    entero sin levantar nada.

    `incapacidades_por_cedula` trae los registros CON FECHAS para agrupar por
    episodio: dos incapacidades separadas se liquidan independientes, cada una
    desde el dia 1; solo las continuas acumulan.

    El neto se arma asi:

        dias_efectivos    = 30 - dias_incapacidad - dias_no_remunerados
        salario_devengado = salario/30 * dias_efectivos
        total             = devengado + incapacidad + extras + otros_pagos
        diferencia        = total - salario        (negativa = disminucion)

    Vacaciones y licencias remuneradas NO restan: el empleado sigue cobrando su
    salario esos dias, asi que entran en los dias efectivos.
    """
    salida = []
    for fila in filas:
        salario = fila.get("salario")
        salario = float(salario) if salario is not None else None
        dias_inc = float(fila.get("dias_incapacidad") or 0)
        dias_nr = float(fila.get("dias_no_remunerados") or 0)
        extras = float(fila.get("valor_extras") or 0)
        otros = float(fila.get("valor_otros_pagos") or 0)

        liq = liquidar_incapacidades_empleado(
            incapacidades_por_cedula.get(fila.get("cedula"), []),
            salario, smlmv, pct_66, pct_50,
        )

        # Nunca menos de cero dias efectivos: si las novedades suman mas de 30
        # dias (solapes o errores de carga) el devengado no puede ser negativo.
        dias_efectivos = max(0.0, DIAS_MES - dias_inc - dias_nr)
        devengado = (salario / DIAS_MES * dias_efectivos) if salario else 0.0
        total = devengado + liq["valor"] + extras + otros

        observaciones = list(liq["observaciones"])
        if salario is None:
            observaciones.insert(0, "sin salario en Trazalo")
        if dias_inc + dias_nr > DIAS_MES:
            observaciones.append(
                f"las novedades suman {dias_inc + dias_nr:g} dias, mas de un mes: revisar"
            )

        salida.append({
            **fila,
            "salario": salario,
            "dias_incapacidad": dias_inc,
            "dias_no_remunerados": dias_nr,
            "dias_efectivos": dias_efectivos,
            "salario_devengado": round(devengado, 2),
            "valor_extras": round(extras, 2),
            "valor_incapacidad": liq["valor"],
            "valor_otros_pagos": round(otros, 2),
            "total_a_pagar": round(total, 2),
            "diferencia_vs_salario": round(total - salario, 2) if salario else None,
            "observaciones": "; ".join(observaciones),
        })
    return salida


def _a_fecha(valor) -> Optional[date]:
    """Las fechas llegan como `date` desde PostgreSQL y como texto desde SQLite."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def agrupar_episodios(registros: list) -> list:
    """Agrupa incapacidades en episodios continuos (prórrogas).

    Dos registros pertenecen al mismo episodio si el segundo empieza el día
    siguiente al fin del primero, o antes (solape). Un hueco de un día o más
    abre un episodio nuevo, que vuelve a contar desde el día 1.

    Devuelve una lista de listas, cada una ordenada por fecha de inicio. Los
    registros sin fecha de inicio no se pueden encadenar: cada uno queda en su
    propio episodio, que es el criterio conservador (no empuja a nadie a un
    tramo peor por un dato incompleto).
    """
    con_fecha, sin_fecha = [], []
    for r in registros:
        (con_fecha if _a_fecha(r.get("fecha_inicio")) else sin_fecha).append(r)

    con_fecha.sort(key=lambda r: _a_fecha(r["fecha_inicio"]))
    episodios, actual, fin_actual = [], [], None

    for r in con_fecha:
        inicio = _a_fecha(r["fecha_inicio"])
        dias = float(r.get("dias") or 0)
        fin = _a_fecha(r.get("fecha_fin"))
        if fin is None:
            # Sin fecha final, se deduce de los días: un día de incapacidad
            # empieza y termina el mismo día.
            fin = inicio + timedelta(days=max(0, int(round(dias)) - 1))

        if actual and fin_actual is not None and inicio <= fin_actual + timedelta(days=1):
            actual.append(r)
            fin_actual = max(fin_actual, fin)
        else:
            if actual:
                episodios.append(actual)
            actual, fin_actual = [r], fin

    if actual:
        episodios.append(actual)
    episodios.extend([[r] for r in sin_fecha])
    return episodios


def liquidar_incapacidades_empleado(
    registros: list,
    salario_mensual: Optional[float],
    smlmv: float,
    pct_66: float = 0.6667,
    pct_50: float = 0.50,
) -> dict:
    """Liquida las incapacidades de un empleado agrupándolas por episodio.

    `registros` son TODAS las del empleado, con fechas, incluidas las de
    periodos anteriores: hacen falta para saber si la del periodo es una
    prórroga. Solo se cobra lo marcado con `en_periodo`; el resto únicamente
    aporta días acumulados dentro de su episodio.
    """
    total, dias_66, dias_50, dias_sin_pago = 0.0, 0.0, 0.0, 0.0
    observaciones, episodios_cobrados = [], 0

    for episodio in agrupar_episodios(registros):
        acumulados = 0.0
        cobra_algo = False
        for r in episodio:
            dias = float(r.get("dias") or 0)
            if r.get("en_periodo"):
                liq = liquidar_incapacidad(acumulados, dias, salario_mensual, smlmv,
                                           pct_66, pct_50)
                total += liq["valor"]
                dias_66 += liq["dias_66"]
                dias_50 += liq["dias_50"]
                dias_sin_pago += liq["dias_sin_pago"]
                for o in liq["observaciones"]:
                    if o not in observaciones:
                        observaciones.append(o)
                cobra_algo = True
            acumulados += dias
        if cobra_algo:
            episodios_cobrados += 1
            if len(episodio) > 1:
                observaciones.append(
                    f"episodio continuo de {len(episodio)} registros, {acumulados:g}d en total"
                )

    if episodios_cobrados > 1:
        observaciones.insert(
            0, f"{episodios_cobrados} episodios independientes: cada uno cuenta desde el dia 1"
        )

    return {
        "valor": round(total, 2),
        "dias_66": dias_66,
        "dias_50": dias_50,
        "dias_sin_pago": dias_sin_pago,
        "observaciones": observaciones,
    }
