"""Regresión de POST /api/execution/trigger-trazalo y su endpoint de estado.

Bug cubierto: el disparador manual corría `sync_trazalo` DENTRO del request.
El sync recorre todo el roster (~1200 empleados) por cada período, así que la
petición quedaba abierta minutos y, al estar el endpoint declarado `async def`
con código bloqueante dentro, además paraba el bucle de eventos de uvicorn.
Cuando el proxy o el navegador cortaban la conexión, el frontend solo recibía
`TypeError: Failed to fetch`, sin manera de saber si el sync había terminado.

Lo que se verifica aquí:
  - el POST responde 202 MIENTRAS el sync sigue corriendo (no lo espera),
  - GET /trazalo-status llega a su handler y no lo captura /{execution_id},
  - el resultado (y el error) del sync quedan disponibles al terminar,
  - dos disparos simultáneos no lanzan dos sincronizaciones en paralelo.

No toca la base de datos: `require_admin` se sustituye por un usuario ficticio
y `sync_trazalo` por un doble, así que solo se ejerce el camino HTTP + el
runner de segundo plano.

Depende de FastAPI/httpx — se salta limpio si no están instalados (mismo
criterio que test_users_router.py; el CI hermético no instala requirements).
"""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from fastapi.testclient import TestClient
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

# Timeout generoso: solo protege contra un cuelgue real, no mide rendimiento.
ESPERA_MAX_S = 10


@unittest.skipUnless(HAS_DEPS, "fastapi/httpx no instalados (CI hermetico no lo requiere)")
class TestTriggerTrazalo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from app.main import app
            from app.services import trazalo_job
            from app.services.auth_service import require_admin
        except Exception as e:  # config inválida, dependencias a medias, etc.
            raise unittest.SkipTest(f"No se pudo importar la app: {e}")

        cls.app = app
        cls.trazalo_job = trazalo_job
        # El lifespan (create_tables + seed_admin + scheduler) no hace falta:
        # ningún endpoint de este archivo toca la BD.
        cls.client = TestClient(app)
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(username="tester")
        # El límite es de 10/hora y esta suite dispara varias veces; sin esto
        # el orden de los tests podría dejar el último en 429.
        cls._limiter_enabled = app.state.limiter.enabled
        app.state.limiter.enabled = False

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()
        cls.app.state.limiter.enabled = cls._limiter_enabled

    def setUp(self):
        # Estado de módulo: cada test arranca desde cero para no depender del
        # orden de ejecución.
        self.trazalo_job._state.update({
            "status": "idle", "started_at": None, "finished_at": None,
            "duration_seconds": None, "triggered_by": None, "result": None, "error": None,
        })

    def _esperar_fin(self):
        limite = time.monotonic() + ESPERA_MAX_S
        while time.monotonic() < limite:
            estado = self.client.get("/api/execution/trazalo-status").json()
            if estado["status"] != "running":
                return estado
            time.sleep(0.05)
        self.fail("la sincronizacion no termino dentro del timeout del test")

    def test_el_sync_corre_fuera_del_request(self):
        """El corazón del bug: el POST no debe esperar a que termine el sync."""
        arrancado, liberar = threading.Event(), threading.Event()

        def sync_lento(db):
            arrancado.set()
            liberar.wait(ESPERA_MAX_S)
            return {"status": "ok", "periodos_sincronizados": 3, "registros_insertados": 42}

        with mock.patch("app.services.trazalo_sync.sync_trazalo", sync_lento):
            r = self.client.post("/api/execution/trigger-trazalo")
            self.assertEqual(r.status_code, 202, r.text)
            self.assertTrue(r.json()["started"])

            # El POST ya volvió y el sync todavía no ha terminado: prueba de
            # que no se ejecutó dentro del request.
            self.assertTrue(arrancado.wait(ESPERA_MAX_S), "el sync no llego a arrancar")
            self.assertEqual(
                self.client.get("/api/execution/trazalo-status").json()["status"], "running"
            )

            liberar.set()
            estado = self._esperar_fin()

        self.assertEqual(estado["status"], "ok")
        self.assertEqual(estado["result"]["registros_insertados"], 42)
        self.assertEqual(estado["triggered_by"], "tester")
        self.assertIsNotNone(estado["duration_seconds"])

    def test_estado_inicial_sin_ninguna_sincronizacion(self):
        """/trazalo-status tiene que llegar a su handler: declarado después de
        /{execution_id} lo capturaría esa ruta e intentaría leer
        'trazalo-status' como un entero, devolviendo 422."""
        r = self.client.get("/api/execution/trazalo-status")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "idle")

    def test_un_error_del_sync_queda_visible_en_el_estado(self):
        def sync_roto(db):
            raise RuntimeError("trazalo caido")

        with mock.patch("app.services.trazalo_sync.sync_trazalo", sync_roto):
            self.assertEqual(self.client.post("/api/execution/trigger-trazalo").status_code, 202)
            estado = self._esperar_fin()

        self.assertEqual(estado["status"], "error")
        self.assertIn("trazalo caido", estado["error"])

    def test_segundo_disparo_no_lanza_un_sync_paralelo(self):
        """Dos sincronizaciones a la vez se pisarían los DELETE/INSERT por
        período. La segunda debe reportar que ya hay una en curso."""
        llamadas, liberar = [], threading.Event()

        def sync_lento(db):
            llamadas.append(1)
            liberar.wait(ESPERA_MAX_S)
            return {"status": "ok", "periodos_sincronizados": 1, "registros_insertados": 1}

        with mock.patch("app.services.trazalo_sync.sync_trazalo", sync_lento):
            self.assertTrue(self.client.post("/api/execution/trigger-trazalo").json()["started"])
            segundo = self.client.post("/api/execution/trigger-trazalo")
            self.assertEqual(segundo.status_code, 202, segundo.text)
            self.assertFalse(segundo.json()["started"])
            self.assertEqual(segundo.json()["job"]["status"], "running")

            liberar.set()
            self._esperar_fin()

        self.assertEqual(len(llamadas), 1)

    def test_sync_omitido_se_propaga_tal_cual(self):
        """sync_trazalo devuelve status=skipped cuando falta TRAZALO_DB_HOST;
        el frontend lo distingue de un error para avisar de configuración."""
        def sync_omitido(db):
            return {"status": "skipped", "reason": "TRAZALO_DB_HOST no configurado"}

        with mock.patch("app.services.trazalo_sync.sync_trazalo", sync_omitido):
            self.client.post("/api/execution/trigger-trazalo")
            estado = self._esperar_fin()

        self.assertEqual(estado["status"], "skipped")
        self.assertEqual(estado["result"]["reason"], "TRAZALO_DB_HOST no configurado")


if __name__ == "__main__":
    unittest.main()
