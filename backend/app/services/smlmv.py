"""Salario mínimo legal mensual vigente (SMLMV), por año.

El SMLMV es el PISO de una incapacidad: ningún día puede liquidarse por debajo
de `SMLMV/30`. Antes vivía como una sola variable de entorno
(`SMLMV_MENSUAL`), lo que tenía dos problemas:

- Si nadie la configuraba, el reporte de nómina devolvía 400 y no había forma
  de emitirlo (que fue justo lo que pasó en producción).
- Un único valor global se aplicaba a CUALQUIER período. Exportar 2025-06 con
  el mínimo de 2026 sube el piso un 23% y liquida ese mes por encima de la
  norma que regía entonces.

Aquí se resuelve el valor que corresponde al AÑO del período que se reporta.
La tabla no es "una cifra inventada" —el motivo por el que el endpoint fallaba
en vez de asumir un default—: son valores decretados, públicos y verificables,
y cada uno queda anotado con su fuente. La garantía original se conserva donde
importa: un año que no está ni en la tabla ni en la configuración **sigue
fallando** con un mensaje que dice exactamente qué definir.

Módulo puro (sin FastAPI ni base de datos), igual que `nomina_report`, para que
se pueda probar sin levantar nada.
"""
import re
from datetime import date
from typing import Optional

# Salario mínimo mensual decretado para cada año, en pesos.
# Fuentes: Decreto 1469 de 2025 (SMLMV 2026), ratificado transitoriamente por
# el Decreto 159 del 19 de febrero de 2026 tras la suspensión del Consejo de
# Estado; años anteriores, decretos de cierre de cada vigencia.
# ACTUALIZAR cada enero. Mientras no se actualice, el año nuevo se puede cubrir
# sin tocar código con la variable de entorno SMLMV_POR_ANIO.
SMLMV_POR_ANIO: dict[int, float] = {
    2020: 877_803.0,
    2021: 908_526.0,
    2022: 1_000_000.0,
    2023: 1_160_000.0,
    2024: 1_300_000.0,
    2025: 1_423_500.0,
    2026: 1_750_905.0,
}


class SMLMVNoConfigurado(Exception):
    """No hay SMLMV para el año pedido, ni en la tabla ni en la configuración."""

    def __init__(self, anio: int):
        self.anio = anio
        super().__init__(
            f"No hay salario mínimo (SMLMV) registrado para {anio}, y sin ese piso "
            f"legal el reporte liquidaría las incapacidades por debajo de la norma. "
            f"Defina en el servidor SMLMV_POR_ANIO=\"{anio}:<valor>\" (o "
            f"SMLMV_MENSUAL=<valor> como respaldo) y reinicie."
        )


def anio_de_periodo(periodo: Optional[str], hoy: Optional[date] = None) -> int:
    """Año al que pertenece un período 'YYYY-MM'.

    Sin período el reporte agrega TODOS los meses en una sola fila por empleado,
    así que no hay un año al cual atribuirlo: se usa el corriente, que es el
    único defendible para una prenómina que se emite hoy.
    """
    if not periodo:
        return (hoy or date.today()).year
    try:
        return int(str(periodo)[:4])
    except ValueError:
        raise ValueError(
            f"Período inválido: '{periodo}'. Se espera el formato YYYY-MM."
        ) from None


# "1.900.000" es como se escribe la cifra aqui; "1900000.50" es como la escribe
# un decimal. Distinguirlas por la forma evita convertir 1.750.905,00 en
# 175.090.500 al quitar los puntos a ciegas.
_MILES_CON_PUNTO = re.compile(r"^\d{1,3}(\.\d{3})+$")


def _a_pesos(texto: str) -> float:
    """Lee un valor en pesos escrito con o sin separador de miles."""
    limpio = texto.replace("_", "").replace(" ", "")
    if _MILES_CON_PUNTO.match(limpio):
        limpio = limpio.replace(".", "")
    return float(limpio)


def parse_tabla_env(texto: Optional[str]) -> dict[int, float]:
    """Lee la tabla de override 'anio:valor' separada por comas.

    Ejemplo: "2027:1900000, 2028:2050000".

    Un valor mal escrito lanza ValueError en vez de ignorarse en silencio: si
    alguien se equivoca al configurarlo, es preferible que el reporte lo diga a
    que liquide con el año equivocado sin avisar.
    """
    if not texto or not str(texto).strip():
        return {}
    tabla: dict[int, float] = {}
    for parte in str(texto).split(","):
        parte = parte.strip()
        if not parte:
            continue
        anio_txt, sep, valor_txt = parte.partition(":")
        if not sep:
            raise ValueError(
                f"SMLMV_POR_ANIO mal formado en '{parte}': se espera 'anio:valor', "
                f"por ejemplo '2027:1900000'."
            )
        try:
            anio = int(anio_txt.strip())
            valor = _a_pesos(valor_txt.strip())
        except ValueError:
            raise ValueError(
                f"SMLMV_POR_ANIO mal formado en '{parte}': el año debe ser entero y "
                f"el valor numérico, por ejemplo '2027:1900000'."
            ) from None
        if valor <= 0:
            raise ValueError(f"SMLMV_POR_ANIO: el valor de {anio} debe ser mayor que cero.")
        tabla[anio] = valor
    return tabla


def resolver_smlmv(
    periodo: Optional[str],
    tabla_env: Optional[str] = None,
    override: Optional[float] = None,
    hoy: Optional[date] = None,
) -> tuple[float, int]:
    """Devuelve (smlmv, año) para el período pedido.

    Precedencia, de más específico a más genérico:

    1. `SMLMV_POR_ANIO` del entorno — el año exacto, puesto a mano por quien
       opera el servidor (sirve para cubrir un año nuevo sin desplegar código).
    2. La tabla de este módulo — el año exacto, con su decreto.
    3. `SMLMV_MENSUAL` del entorno — respaldo global, solo para años que no
       aparecen arriba. NO gana sobre un valor por año: si ganara, configurarla
       volvería a liquidar los períodos históricos con el mínimo de hoy, que es
       el defecto que este módulo corrige.
    4. Nada: SMLMVNoConfigurado.
    """
    anio = anio_de_periodo(periodo, hoy)

    valor = parse_tabla_env(tabla_env).get(anio) or SMLMV_POR_ANIO.get(anio)
    if valor is None and override:
        valor = float(override)
    if valor is None:
        raise SMLMVNoConfigurado(anio)
    return float(valor), anio
