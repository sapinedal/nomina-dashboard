"""
Test de CARACTERIZACION de normalize_sede / normalize_area.

Hermetico: importa SOLO app.utils.normalizers (unica dependencia: `re`), sin BD
ni dependencias pesadas -> corre en CI sin instalar nada.

Congela el comportamiento OBSERVADO hoy (no el ideal): si un refactor cambia
cualquier salida, el test falla. Los pares golden fueron verificados ejecutando
las funciones reales contra el vocabulario de produccion.

Correr desde backend/:
    python -m unittest discover -s tests -v
"""
import unittest

from app.utils.normalizers import normalize_sede, normalize_area


class TestNormalizeSede(unittest.TestCase):
    GOLDEN = [
        ("CLINICA VICTORIANA", "CLINICA"),
        ("Torre Villanueva", "TORRE VILLANUEVA"),
        ("sede 80", "SEDE ADMINISTRATIVA"),
        # enfermeria es AREA, no sede: no mapea -> limpio en mayusculas
        ("ENFERMERIA 3er piso", "ENFERMERIA 3ER PISO"),
    ]

    def test_golden(self):
        for entrada, esperado in self.GOLDEN:
            with self.subTest(entrada=entrada):
                self.assertEqual(normalize_sede(entrada), esperado)

    def test_vacios_devuelven_cadena_vacia(self):
        for entrada in ("", "   ", "\t"):
            with self.subTest(entrada=repr(entrada)):
                self.assertEqual(normalize_sede(entrada), "")

    def test_idempotente(self):
        for entrada, _ in self.GOLDEN:
            once = normalize_sede(entrada)
            self.assertEqual(normalize_sede(once), once, f"no idempotente: {entrada!r}")


class TestNormalizeArea(unittest.TestCase):
    GOLDEN = [
        ("FARMACIA CENTRAL", "FARMACIA"),
        ("si-nr", "SI NR"),
    ]

    def test_golden(self):
        for entrada, esperado in self.GOLDEN:
            with self.subTest(entrada=entrada):
                self.assertEqual(normalize_area(entrada), esperado)

    def test_vacios_devuelven_cadena_vacia(self):
        for entrada in ("", "   "):
            with self.subTest(entrada=repr(entrada)):
                self.assertEqual(normalize_area(entrada), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
