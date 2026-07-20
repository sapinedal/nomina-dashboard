"""
Tests de arranque seguro para Settings (config.py) — SEC-1.

Verifica que Settings.model_post_init impide arrancar con DEBUG=false y
credenciales por defecto conocidas (SECRET_KEY / SEED_ADMIN_PASSWORD),
publicadas en el propio codigo fuente del repo.

Requiere pydantic-settings instalado. El CI actual (.github/workflows/ci.yml)
todavia no instala requirements.txt (ver DEVOPS-1 en el roadmap), asi que si
la dependencia no esta disponible estos tests se OMITEN en vez de romper la
ejecucion — en cuanto DEVOPS-1 instale dependencias reales en CI, empiezan a
correr de verdad sin tocar este archivo.

Correr desde backend/ con las dependencias instaladas:
    python -m unittest discover -s tests -v
"""
import unittest


class TestSettingsFailClosed(unittest.TestCase):
    STRONG_SECRET = "x" * 40
    STRONG_ADMIN_PASSWORD = "Un-P4ssword-Fuerte-2026"
    DUMMY_DB_URL = "sqlite:///:memory:"

    @classmethod
    def setUpClass(cls):
        try:
            from app.config import (
                Settings,
                _INSECURE_DEFAULT_SECRET_KEY,
                _INSECURE_DEFAULT_ADMIN_PASSWORD,
            )
        except ImportError as exc:
            raise unittest.SkipTest(
                f"pydantic-settings no instalado en este entorno ({exc}); "
                "correr tras `pip install -r requirements.txt`."
            )
        cls.Settings = Settings
        cls.DEFAULT_SECRET = _INSECURE_DEFAULT_SECRET_KEY
        cls.DEFAULT_ADMIN_PASSWORD = _INSECURE_DEFAULT_ADMIN_PASSWORD

    def _settings(self, **overrides):
        """Construye Settings con overrides explicitos para cada caso,
        sin depender del .env real del entorno donde corre el test."""
        base = dict(
            DEBUG=False,
            SECRET_KEY=self.STRONG_SECRET,
            SEED_ADMIN_PASSWORD=self.STRONG_ADMIN_PASSWORD,
            DATABASE_URL=self.DUMMY_DB_URL,
        )
        base.update(overrides)
        return self.Settings(**base)

    def test_debug_true_no_valida_credenciales(self):
        """Dev local (DEBUG=true) arranca rapido sin exigir secretos."""
        self._settings(
            DEBUG=True,
            SECRET_KEY=self.DEFAULT_SECRET,
            SEED_ADMIN_PASSWORD=self.DEFAULT_ADMIN_PASSWORD,
        )

    def test_debug_false_rechaza_secret_key_default(self):
        with self.assertRaisesRegex(ValueError, "SECRET_KEY"):
            self._settings(SECRET_KEY=self.DEFAULT_SECRET)

    def test_debug_false_rechaza_secret_key_vacio(self):
        with self.assertRaisesRegex(ValueError, "SECRET_KEY"):
            self._settings(SECRET_KEY="")

    def test_debug_false_rechaza_secret_key_corto(self):
        with self.assertRaisesRegex(ValueError, "32"):
            self._settings(SECRET_KEY="clave-corta")

    def test_debug_false_rechaza_seed_admin_password_default(self):
        with self.assertRaisesRegex(ValueError, "SEED_ADMIN_PASSWORD"):
            self._settings(SEED_ADMIN_PASSWORD=self.DEFAULT_ADMIN_PASSWORD)

    def test_debug_false_rechaza_seed_admin_password_vacio(self):
        with self.assertRaisesRegex(ValueError, "SEED_ADMIN_PASSWORD"):
            self._settings(SEED_ADMIN_PASSWORD="")

    def test_debug_false_con_credenciales_seguras_arranca(self):
        settings = self._settings()
        self.assertEqual(settings.SECRET_KEY, self.STRONG_SECRET)
        self.assertEqual(settings.SEED_ADMIN_PASSWORD, self.STRONG_ADMIN_PASSWORD)


if __name__ == "__main__":
    unittest.main()
