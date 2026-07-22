"""
Tests end-to-end del router /api/users (creacion/edicion/eliminacion de
usuarios con areas + auditoria), contra un servidor FastAPI real (TestClient)
-- no mocks de la capa HTTP ni del ORM.

Cubre un bug real encontrado en verificacion manual: _sync_areas escribía
las filas de UserArea directo con db.add()/db.delete() (sin pasar por la
colección user.area_assignments), así que leer esa colección justo después
del flush() para armar el diff de auditoría devolvía el estado VIEJO -- la
acción "areas_changed" nunca se registraba aunque el cambio sí se guardaba
bien en la BD. Fix: _sync_areas devuelve (antes, después) desde sus propios
sets en vez de releer la colección ORM.

Nota sobre la BD usada: app.config.Settings se lee UNA vez al importar
app.config (no hay soporte de reconfiguración dinámica en este proyecto), y
ese import puede ser disparado por OTRO archivo de test que se cargue antes
en `unittest discover` (orden alfabético) -- así que este archivo NO asume
un DATABASE_URL/SEED_ADMIN_PASSWORD propios vía os.environ (funcionaría
corriendo este archivo solo, pero fallaría de forma flaky dentro de la
suite completa). En cambio, lee `settings.DATABASE_URL` /
`settings.SEED_ADMIN_PASSWORD` que ya haya resuelto la app (típicamente el
`backend/.env` de desarrollo local) y limpia únicamente los usuarios de
prueba que crea, sin tocar ni borrar la BD compartida.

Depende de FastAPI/SQLAlchemy/httpx -- se salta limpio si no están
instalados (mismo criterio que test_horas_extras_service.py).
"""
import unittest

try:
    from fastapi.testclient import TestClient
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "fastapi/httpx no instalados (CI hermetico no lo requiere)")
class TestUsersRouterConAreas(unittest.TestCase):

    _PREFIJO_PRUEBA = "test_areas_tmp_"  # todos los usuarios que crea este archivo empiezan así

    @classmethod
    def setUpClass(cls):
        from app.main import app
        from app.config import settings
        from app.database import SessionLocal

        cls.SessionLocal = SessionLocal
        cls.client = TestClient(app)
        cls.client.__enter__()  # dispara el lifespan: create_tables + seed_admin_user

        r = cls.client.post(
            "/api/auth/token",
            data={"username": "admin", "password": settings.SEED_ADMIN_PASSWORD},
        )
        if r.status_code != 200:
            raise unittest.SkipTest(
                f"No se pudo autenticar con el admin sembrado en {settings.DATABASE_URL} "
                f"({r.status_code}: {r.text}) -- revisar backend/.env"
            )
        cls.admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        cls._created_ids: list[int] = []

    @classmethod
    def tearDownClass(cls):
        # Limpieza: borra SOLO los usuarios de prueba que este archivo creó,
        # no la BD entera (puede ser el archivo de dev local compartido).
        for uid in cls._created_ids:
            cls.client.delete(f"/api/users/{uid}", headers=cls.admin_headers)
        cls.client.__exit__(None, None, None)

    def _crear_usuario(self, suffix, role="readonly", areas=None):
        username = f"{self._PREFIJO_PRUEBA}{suffix}"
        r = self.client.post("/api/users/", json={
            "username": username, "email": f"{username}@x.com", "full_name": username,
            "role": role, "password": "Pw12345!", "areas": areas,
        }, headers=self.admin_headers)
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        self.__class__._created_ids.append(data["id"])
        return data

    def _acciones_auditoria(self, entity_id):
        db = self.SessionLocal()
        try:
            from app.models.audit_log import AuditLog
            rows = (
                db.query(AuditLog.action)
                .filter(AuditLog.entity_type == "user", AuditLog.entity_id == entity_id)
                .order_by(AuditLog.id)
                .all()
            )
            return [r[0] for r in rows]
        finally:
            db.close()

    def _contar_user_areas(self, user_id):
        db = self.SessionLocal()
        try:
            from app.models.user import UserArea
            return db.query(UserArea).filter(UserArea.user_id == user_id).count()
        finally:
            db.close()

    def test_crear_usuario_con_multiples_areas(self):
        u = self._crear_usuario("luisa1", areas=["NOMINA", "SST", "SELECCION"])
        self.assertEqual(sorted(u["areas"]), ["NOMINA", "SELECCION", "SST"])

    def test_areas_duplicadas_en_payload_se_deduplican(self):
        u = self._crear_usuario("carlos1", role="analyst", areas=["COMPRAS", "COMPRAS", "CONTABILIDAD"])
        self.assertEqual(sorted(u["areas"]), ["COMPRAS", "CONTABILIDAD"])

    def test_admin_no_guarda_areas_aunque_se_envien(self):
        u = self._crear_usuario("admin2", role="admin", areas=["NOMINA"])
        self.assertEqual(u["areas"], [])

    def test_editar_areas_sin_afectar_otros_campos(self):
        u = self._crear_usuario("luisa2", areas=["NOMINA", "SST"])
        r = self.client.put(f"/api/users/{u['id']}", json={"areas": ["NOMINA", "COMPRAS"]}, headers=self.admin_headers)
        self.assertEqual(r.status_code, 200, r.text)
        actualizado = r.json()
        self.assertEqual(sorted(actualizado["areas"]), ["COMPRAS", "NOMINA"])
        self.assertEqual(actualizado["full_name"], u["full_name"])
        self.assertEqual(actualizado["email"], u["email"])

    def test_auditoria_registra_create_y_areas_changed(self):
        """Regresión del bug descrito en el docstring del módulo."""
        u = self._crear_usuario("luisa3", areas=["NOMINA"])
        self.client.put(f"/api/users/{u['id']}", json={"areas": ["NOMINA", "SST"]}, headers=self.admin_headers)
        acciones = self._acciones_auditoria(u["id"])
        self.assertIn("create", acciones)
        self.assertIn("areas_changed", acciones)

    def test_eliminar_usuario_borra_areas_en_cascada(self):
        u = self._crear_usuario("luisa4", areas=["NOMINA", "SST"])
        self.__class__._created_ids.remove(u["id"])  # se borra manualmente en este test, no en tearDownClass
        r = self.client.delete(f"/api/users/{u['id']}", headers=self.admin_headers)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self._contar_user_areas(u["id"]), 0)
        acciones = self._acciones_auditoria(u["id"])
        self.assertEqual(acciones[-1], "delete")


if __name__ == "__main__":
    unittest.main()
