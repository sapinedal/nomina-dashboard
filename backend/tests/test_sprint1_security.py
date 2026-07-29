"""Sprint 1 — DEF-0002 OpenAPI exposure helpers (unittest hermético).

Importa `app.main` solo si las deps están instaladas; si no, se omite
(mismo criterio que el CI hermético actual).
"""
import unittest


class TestOpenApiExposure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from app import main as main_mod
            from app.config import settings
        except ImportError as exc:
            raise unittest.SkipTest(
                f"deps de app no disponibles en este entorno ({exc})"
            )
        cls.main_mod = main_mod
        cls.settings = settings
        cls._orig_expose = settings.EXPOSE_OPENAPI

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "settings"):
            cls.settings.EXPOSE_OPENAPI = cls._orig_expose

    def tearDown(self):
        self.settings.EXPOSE_OPENAPI = self._orig_expose

    def test_openapi_hidden_by_default(self):
        self.settings.EXPOSE_OPENAPI = False
        self.assertIsNone(self.main_mod._openapi_url())
        self.assertIsNone(self.main_mod._docs_url())
        self.assertIsNone(self.main_mod._redoc_url())

    def test_openapi_only_with_explicit_flag(self):
        self.settings.EXPOSE_OPENAPI = False
        self.assertIsNone(self.main_mod._openapi_url())
        self.settings.EXPOSE_OPENAPI = True
        self.assertEqual(self.main_mod._openapi_url(), "/api/openapi.json")
        self.assertEqual(self.main_mod._docs_url(), "/api/docs")


if __name__ == "__main__":
    unittest.main()
