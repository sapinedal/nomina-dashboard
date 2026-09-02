"""Detector de razón social: sin deps, corre en el CI hermético."""
import unittest

from app.utils.razon_social import es_razon_social


class TestEsRazonSocial(unittest.TestCase):

    def test_ejemplos_reportados(self):
        self.assertTrue(es_razon_social("AGUAS DEL PUERTO SA E.S.P"))
        self.assertTrue(es_razon_social("AGUAS NACIONALES EPM S.A. E.S.P"))
        self.assertTrue(es_razon_social("ALSIMON'S S.A.S"))

    def test_otros_sufijos(self):
        self.assertTrue(es_razon_social("FOO LTDA"))
        self.assertTrue(es_razon_social("BAR LIMITADA"))
        self.assertTrue(es_razon_social("BAZ Y CIA"))
        self.assertTrue(es_razon_social("acme sas"))

    def test_persona_natural_no_es_empresa(self):
        self.assertFalse(es_razon_social("ROSA MARIA GOMEZ"))
        self.assertFalse(es_razon_social("LUIS PEREZ"))
        self.assertFalse(es_razon_social("SARA LOPEZ"))
        self.assertFalse(es_razon_social("ADRIANA PATRICIA BETANCUR"))
        self.assertFalse(es_razon_social(""))
        self.assertFalse(es_razon_social(None))

    def test_sql_like_exige_espacio_antes_del_sufijo(self):
        """'%SA' marcaría a ROSA; el patrón tiene que llevar espacio."""
        from app.utils.razon_social import _SQL_LIKE_PATTERNS
        for p in _SQL_LIKE_PATTERNS:
            self.assertTrue(p.startswith("% "), p)


if __name__ == "__main__":
    unittest.main()
