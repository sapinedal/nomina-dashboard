"""El reporte de nómina no puede sacar filas con la identidad en blanco.

Bug reportado el 2026-08-26 sobre el Excel de producción: filas con cédula y
salario, pero Nombre / Área / Cargo vacíos. Causa: el join de novedades está
acotado al periodo (a propósito, para no perder a los empleados sin novedades),
así que para quien no tuvo ninguna ese mes no había de dónde sacar el nombre si
el roster tampoco lo traía — aunque el dato SÍ estuviera en sus novedades de
otros meses.

Depende de SQLAlchemy: se salta limpio si no está, igual que
test_area_authorization.py.
"""
import tempfile
import unittest

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

if HAS_SQLALCHEMY:
    from app.models.nomina import NovedadNomina
    from app.services import dashboard_service as svc


@unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy no instalado (CI hermetico no lo requiere)")
class TestReporteNominaIdentidad(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
        NovedadNomina.__table__.create(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE salarios_empleados (
                    cedula VARCHAR(30) PRIMARY KEY, salario REAL,
                    nombre VARCHAR(200), area VARCHAR(200),
                    sede VARCHAR(200), cargo VARCHAR(200), activo INTEGER
                )
            """))
            # ANA vino del roster de Trazalo: identidad completa.
            conn.execute(text(
                "INSERT INTO salarios_empleados VALUES "
                "('1', 3000000, 'ANA', 'NOMINA', 'PRINCIPAL', 'AUXILIAR', 1)"))
            # LUIS es de la carga historica de salarios: solo cedula y salario.
            # Es la fila que salia en blanco.
            conn.execute(text(
                "INSERT INTO salarios_empleados VALUES "
                "('2', 2000000, NULL, NULL, NULL, NULL, NULL)"))
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()

    def _nov(self, cedula, nombre, area, cargo, periodo, tipo="PERMISO", dias=1.0):
        return NovedadNomina(
            archivo_origen=f"{periodo[5:]}{periodo[:4]}.xlsx", hoja_origen="H",
            cedula=cedula, nombre_empleado=nombre, area=area, cargo=cargo,
            sede="PRINCIPAL", tipo_novedad=tipo, dias=dias, unidad="dias",
            periodo=periodo, es_valido=1,
        )

    def _fila(self, cedula, periodo="2026-08"):
        filas = svc.get_reporte_nomina_rows(self.db, {"periodo": periodo})
        return next(f for f in filas if f["cedula"] == cedula)

    def test_sin_novedades_en_el_periodo_toma_la_identidad_del_historial(self):
        """El caso del bug: LUIS no tiene novedades en agosto, pero sí en junio.
        Su nombre, área y cargo salen de ahí en vez de quedar en blanco."""
        self.db.add(self._nov("2", "LUIS", "CONTABILIDAD", "ANALISTA", "2026-06"))
        self.db.commit()

        fila = self._fila("2")
        self.assertEqual(fila["nombre_empleado"], "LUIS")
        self.assertEqual(fila["area"], "CONTABILIDAD")
        self.assertEqual(fila["cargo"], "ANALISTA")
        self.assertEqual(fila["num_novedades"], 0)  # sigue sin novedades del mes

    def test_el_roster_manda_sobre_el_historial(self):
        """Si RRHH ya tiene el dato, una novedad vieja no puede sobrescribirlo:
        el roster es la fuente autorizada."""
        self.db.add(self._nov("1", "ANA VIEJA", "AREA VIEJA", "CARGO VIEJO", "2026-06"))
        self.db.commit()

        fila = self._fila("1")
        self.assertEqual(fila["nombre_empleado"], "ANA")
        self.assertEqual(fila["area"], "NOMINA")
        self.assertEqual(fila["cargo"], "AUXILIAR")

    def test_el_historial_no_multiplica_los_totales(self):
        """La regresión cara: si el historial se uniera en crudo en vez de
        pre-agrupado, cada novedad vieja duplicaría los días del periodo."""
        for periodo in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05"):
            self.db.add(self._nov("2", "LUIS", "CONTABILIDAD", "ANALISTA", periodo,
                                  tipo="INCAPACIDAD", dias=10.0))
        self.db.add(self._nov("2", "LUIS", "CONTABILIDAD", "ANALISTA", "2026-08",
                              tipo="INCAPACIDAD", dias=3.0))
        self.db.commit()

        fila = self._fila("2")
        self.assertEqual(fila["num_novedades"], 1)
        self.assertAlmostEqual(fila["dias_incapacidad"], 3.0, places=2)

    def test_sin_novedades_en_ningun_periodo_no_revienta(self):
        """Un empleado que nunca tuvo una novedad sigue saliendo con su salario,
        con la identidad vacía: no hay de dónde sacarla y eso es un hueco de
        datos del roster, no un error del reporte."""
        fila = self._fila("2")
        self.assertIsNone(fila["nombre_empleado"])
        self.assertEqual(fila["salario"], 2000000)


@unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy no instalado (CI hermetico no lo requiere)")
class TestExcluyeRazonesSociales(unittest.TestCase):
    """AGUAS DEL PUERTO no puede salir ni en el Excel ni en Empleados del Período."""

    def setUp(self):
        self.engine = create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
        NovedadNomina.__table__.create(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE salarios_empleados (
                    cedula VARCHAR(30) PRIMARY KEY, salario REAL,
                    nombre VARCHAR(200), area VARCHAR(200),
                    sede VARCHAR(200), cargo VARCHAR(200), activo INTEGER
                )
            """))
            conn.execute(text(
                "INSERT INTO salarios_empleados VALUES "
                "('1', 3000000, 'ANA', 'NOMINA', 'PRINCIPAL', 'AUXILIAR', 1)"))
            conn.execute(text(
                "INSERT INTO salarios_empleados VALUES "
                "('811012043', 1000, 'AGUAS DEL PUERTO SA E.S.P', NULL, NULL, NULL, 1)"))
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(NovedadNomina(
            archivo_origen="092026.xlsx", hoja_origen="TRAZALO",
            cedula="1", nombre_empleado="ANA", area="NOMINA", cargo="AUXILIAR",
            tipo_novedad="PRESENTE EN NOMINA", periodo="2026-09", es_valido=1,
        ))
        self.db.add(NovedadNomina(
            archivo_origen="092026.xlsx", hoja_origen="TRAZALO",
            cedula="811012043", nombre_empleado="AGUAS DEL PUERTO SA E.S.P",
            tipo_novedad="PRESENTE EN NOMINA", periodo="2026-09", es_valido=1,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_reporte_omite_la_empresa(self):
        filas = svc.get_reporte_nomina_rows(self.db, {"periodo": "2026-09"})
        cedulas = [f["cedula"] for f in filas]
        self.assertIn("1", cedulas)
        self.assertNotIn("811012043", cedulas)

    def test_lista_del_dashboard_omite_la_empresa(self):
        lista = svc.get_empleados_lista(self.db, {"periodo": "2026-09"})
        nombres = [e.nombre for e in lista.data]
        self.assertIn("ANA", nombres)
        self.assertNotIn("AGUAS DEL PUERTO SA E.S.P", nombres)


if __name__ == "__main__":
    unittest.main()
