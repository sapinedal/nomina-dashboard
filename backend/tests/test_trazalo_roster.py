"""El roster de Trazalo debe dejar la identidad de TODOS los activos.

Bug reportado el 2026-08-26: el Excel de nómina traía filas con cédula y salario
pero con Nombre, Área y Cargo vacíos. Causa: `sincronizar_roster` descartaba la
fila entera cuando Trazalo no exponía salario (`if salario is not None`), y ese
es el caso del grueso del personal clínico. Su identidad nunca se guardaba.

Depende de SQLAlchemy: se salta limpio si no está, igual que
test_area_authorization.py.
"""
import tempfile
import unittest

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    # El modulo arrastra pandas via excel_processor; el driver de Trazalo
    # (psycopg2) ya no, porque se importa donde se usa.
    from app.services.trazalo_sync import sincronizar_roster
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "deps no disponibles en este entorno (CI hermetico)")
class TestSincronizarRoster(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE salarios_empleados (
                    cedula VARCHAR(30) PRIMARY KEY, salario REAL NOT NULL,
                    nombre VARCHAR(200), area VARCHAR(200),
                    sede VARCHAR(200), cargo VARCHAR(200), activo INTEGER
                )
            """))
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()

    def _fila(self, cedula):
        r = self.db.execute(text(
            "SELECT cedula, salario, nombre, area, cargo, activo "
            "FROM salarios_empleados WHERE cedula = :c"), {"c": cedula}).fetchone()
        return dict(r._mapping) if r else None

    @staticmethod
    def _emp(cedula, nombre, area="Enfermeria", cargo="AUXILIAR", salario=None):
        return {"cedula": cedula, "nombre": nombre, "area": area,
                "sede": "PRINCIPAL", "cargo": cargo, "salario": salario}

    def test_sin_salario_igual_recibe_su_identidad(self):
        """El caso del bug: ya tenía fila con salario de un sync viejo, pero
        Trazalo dejó de exponerle salario. Su nombre debe llegar igual."""
        self.db.execute(text(
            "INSERT INTO salarios_empleados (cedula, salario) VALUES ('2', 2000000)"))
        self.db.commit()

        sincronizar_roster(self.db, [self._emp("2", "LUIS PEREZ", "Cirugia", "ENFERMERO")])

        fila = self._fila("2")
        self.assertEqual(fila["nombre"], "LUIS PEREZ")
        self.assertEqual(fila["area"], "CIRUGIA")   # normalizada en mayúsculas
        self.assertEqual(fila["cargo"], "ENFERMERO")
        self.assertEqual(fila["activo"], 1)

    def test_sin_salario_no_borra_el_salario_que_ya_habia(self):
        """Es el único salario con el que se puede liquidar a esa persona."""
        self.db.execute(text(
            "INSERT INTO salarios_empleados (cedula, salario) VALUES ('2', 2000000)"))
        self.db.commit()

        sincronizar_roster(self.db, [self._emp("2", "LUIS PEREZ")])

        self.assertEqual(self._fila("2")["salario"], 2000000)

    def test_con_salario_crea_la_fila_y_la_actualiza(self):
        res = sincronizar_roster(self.db, [self._emp("1", "ANA GOMEZ", salario=3000000)])
        self.assertEqual(res["con_salario"], 1)
        self.assertEqual(self._fila("1")["salario"], 3000000)

        sincronizar_roster(self.db, [self._emp("1", "ANA GOMEZ", salario=3500000)])
        self.assertEqual(self._fila("1")["salario"], 3500000)

    def test_sin_salario_y_sin_fila_previa_no_se_inventa_una(self):
        """`salario` es NOT NULL: insertarla exigiría un salario que no existe.
        Seguir fuera de la prenómina es la decisión ya tomada de no liquidar con
        cifras inventadas."""
        res = sincronizar_roster(self.db, [self._emp("9", "NUEVO SIN SALARIO")])
        self.assertEqual(res["sin_salario"], 1)
        self.assertIsNone(self._fila("9"))

    def test_un_salario_ilegible_no_cuesta_la_identidad(self):
        self.db.execute(text(
            "INSERT INTO salarios_empleados (cedula, salario) VALUES ('3', 1500000)"))
        self.db.commit()

        sincronizar_roster(self.db, [self._emp("3", "PEPE RUIZ", salario="no-es-un-numero")])

        fila = self._fila("3")
        self.assertEqual(fila["nombre"], "PEPE RUIZ")
        self.assertEqual(fila["salario"], 1500000)

    def test_cedula_vacia_se_ignora_sin_reventar(self):
        res = sincronizar_roster(self.db, [self._emp("", "SIN CEDULA", salario=1000000)])
        self.assertEqual(res, {"con_salario": 0, "sin_salario": 0})


if __name__ == "__main__":
    unittest.main()
