"""Resolución del SMLMV que se usa como piso de las incapacidades.

Son cifras con efecto legal: cada valor de la tabla se comprueba contra el
decretado para ese año, no contra lo que devuelva la función. Un typo aquí
liquida miles de incapacidades por el piso equivocado.
"""
import unittest
from datetime import date

from app.services.nomina_report import liquidar_incapacidad
from app.services.smlmv import (
    SMLMV_POR_ANIO,
    SMLMVNoConfigurado,
    anio_de_periodo,
    parse_tabla_env,
    resolver_smlmv,
)


class TestTablaOficial(unittest.TestCase):
    """Los valores decretados, uno por uno."""

    def test_valores_decretados(self):
        self.assertEqual(SMLMV_POR_ANIO[2023], 1_160_000)
        self.assertEqual(SMLMV_POR_ANIO[2024], 1_300_000)
        self.assertEqual(SMLMV_POR_ANIO[2025], 1_423_500)
        self.assertEqual(SMLMV_POR_ANIO[2026], 1_750_905)

    def test_la_serie_nunca_baja(self):
        """El mínimo legal solo sube. Una tabla que retroceda tiene un typo."""
        anios = sorted(SMLMV_POR_ANIO)
        for previo, actual in zip(anios, anios[1:]):
            self.assertEqual(actual, previo + 1, "faltan años intermedios en la tabla")
            self.assertGreater(SMLMV_POR_ANIO[actual], SMLMV_POR_ANIO[previo])


class TestAnioDePeriodo(unittest.TestCase):

    def test_toma_el_anio_del_periodo(self):
        self.assertEqual(anio_de_periodo("2025-06"), 2025)

    def test_sin_periodo_usa_el_anio_corriente(self):
        """Sin período el reporte agrega todos los meses: no hay año al cual
        atribuirlo más que el de hoy."""
        self.assertEqual(anio_de_periodo(None, hoy=date(2026, 8, 26)), 2026)

    def test_periodo_ilegible_no_pasa_en_silencio(self):
        with self.assertRaises(ValueError):
            anio_de_periodo("agosto")


class TestResolverSmlmv(unittest.TestCase):

    def test_el_periodo_manda_sobre_el_anio_corriente(self):
        """El defecto que corrige este módulo: 2025 no se liquida con el piso
        de 2026, que es un 23% más alto."""
        valor, anio = resolver_smlmv("2025-06", hoy=date(2026, 8, 26))
        self.assertEqual(valor, 1_423_500)
        self.assertEqual(anio, 2025)

    def test_funciona_sin_ninguna_variable_de_entorno(self):
        """El caso que devolvía 400 en producción."""
        valor, anio = resolver_smlmv("2026-08", tabla_env=None, override=None)
        self.assertEqual(valor, 1_750_905)
        self.assertEqual(anio, 2026)

    def test_el_entorno_puede_cubrir_un_anio_que_la_tabla_no_trae(self):
        valor, anio = resolver_smlmv("2030-01", tabla_env="2030:2500000")
        self.assertEqual(valor, 2_500_000)
        self.assertEqual(anio, 2030)

    def test_el_entorno_pisa_la_tabla_para_ese_anio(self):
        """Si un decreto corrige el valor a mitad de año, se ajusta sin desplegar."""
        valor, _ = resolver_smlmv("2026-08", tabla_env="2026:1800000")
        self.assertEqual(valor, 1_800_000)

    def test_smlmv_mensual_no_pisa_el_valor_por_anio(self):
        """Configurar el respaldo global no debe volver a liquidar los períodos
        viejos con el mínimo de hoy."""
        valor, _ = resolver_smlmv("2024-03", override=1_750_905)
        self.assertEqual(valor, 1_300_000)

    def test_smlmv_mensual_solo_cubre_anios_desconocidos(self):
        valor, anio = resolver_smlmv("2031-01", override=2_600_000)
        self.assertEqual(valor, 2_600_000)
        self.assertEqual(anio, 2031)

    def test_anio_sin_dato_falla_y_dice_que_configurar(self):
        with self.assertRaises(SMLMVNoConfigurado) as ctx:
            resolver_smlmv("2032-01")
        mensaje = str(ctx.exception)
        self.assertIn("2032", mensaje)
        self.assertIn("SMLMV_POR_ANIO", mensaje)


class TestParseTablaEnv(unittest.TestCase):

    def test_vacio_es_tabla_vacia(self):
        self.assertEqual(parse_tabla_env(None), {})
        self.assertEqual(parse_tabla_env("   "), {})

    def test_varios_anios_con_espacios(self):
        self.assertEqual(
            parse_tabla_env(" 2027:1900000 , 2028:2050000 "),
            {2027: 1_900_000.0, 2028: 2_050_000.0},
        )

    def test_acepta_el_valor_con_puntos_de_miles(self):
        """'1.900.000' es como se escribe la cifra en Colombia; leerlo como
        1.9 pesos dejaría el piso en cero sin que nadie lo note."""
        self.assertEqual(parse_tabla_env("2027:1.900.000"), {2027: 1_900_000.0})

    def test_un_decimal_no_se_confunde_con_separador_de_miles(self):
        """El punto de '1.900.000' separa miles; el de '1750905.50' no."""
        self.assertEqual(parse_tabla_env("2027:1750905.50"), {2027: 1_750_905.50})

    def test_formato_invalido_no_se_ignora_en_silencio(self):
        for texto in ("1900000", "2027=1900000", "2027:mucho", "2027:0"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                parse_tabla_env(texto)


class TestEfectoEnLaLiquidacion(unittest.TestCase):
    """El piso no es decorativo: cambia el dinero de quien gana el mínimo."""

    def test_un_salario_minimo_se_liquida_al_piso_de_su_anio(self):
        smlmv_2025, _ = resolver_smlmv("2025-06")
        r = liquidar_incapacidad(0, 3, smlmv_2025, smlmv_2025)
        self.assertAlmostEqual(r["valor"], 3 * (smlmv_2025 / 30), places=2)
        self.assertIn("se aplico el piso de 1 SMLMV", r["observaciones"])

    def test_el_piso_de_2026_no_debe_aplicarse_a_2025(self):
        smlmv_2025, _ = resolver_smlmv("2025-06")
        smlmv_2026, _ = resolver_smlmv("2026-06")
        correcto = liquidar_incapacidad(0, 10, smlmv_2025, smlmv_2025)["valor"]
        inflado = liquidar_incapacidad(0, 10, smlmv_2025, smlmv_2026)["valor"]
        self.assertLess(correcto, inflado)

    def test_el_salto_de_2026_metio_bajo_el_piso_salarios_que_no_lo_estaban(self):
        """2.500.000 se liquidaba al 66,67% con el umbral de 2025 (2.135.000) y
        queda bajo el piso con el de 2026 (2.626.357). Usar el año equivocado le
        cambia el pago, y por eso el SMLMV se toma del año del periodo."""
        salario = 2_500_000.0
        smlmv_2025, _ = resolver_smlmv("2025-06")
        smlmv_2026, _ = resolver_smlmv("2026-06")

        en_2025 = liquidar_incapacidad(0, 10, salario, smlmv_2025)["valor"]
        self.assertAlmostEqual(en_2025, 10 * 0.6667 * salario / 30, places=2)

        en_2026 = liquidar_incapacidad(0, 10, salario, smlmv_2026)["valor"]
        self.assertAlmostEqual(en_2026, 10 * smlmv_2026 / 30, places=2)

        self.assertLess(en_2025, en_2026)


if __name__ == "__main__":
    unittest.main()
