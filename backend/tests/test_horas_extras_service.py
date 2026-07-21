"""
Tests de regresion para el panel de Horas Extras & Recargos y su drill-down
por tipo (get_panel_horas_extras / get_detalle_horas_extras_tipo).

A diferencia de test_normalizers_characterization.py, esta suite SI depende
de SQLAlchemy (el servicio ejecuta SQL crudo contra el modelo NovedadNomina +
la tabla salarios_empleados). El pipeline de CI actual corre
`python -m unittest discover` sin instalar backend/requirements.txt, por
diseno (ver docstring de test_normalizers_characterization.py: "hermetico
... corre en CI sin instalar nada"). Para no romper esa convencion, esta
suite se salta a si misma limpiamente si sqlalchemy no esta instalado, en
vez de fallar la coleccion de tests.

Correr con las dependencias del proyecto instaladas (.venv):
    python -m unittest tests.test_horas_extras_service -v
"""
import os
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
class TestHorasExtrasDetalle(unittest.TestCase):
    """Verifica que get_detalle_horas_extras_tipo cuadre exactamente con la
    fila agregada de get_panel_horas_extras para el mismo tipo, y que el
    refactor de HE_FACTORES/_HE_VALOR_EXPR no altere ningun valor calculado."""

    def setUp(self):
        self._tmp_path = tempfile.mktemp(suffix=".db")
        self.engine = create_engine(f"sqlite:///{self._tmp_path}")
        NovedadNomina.__table__.create(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE salarios_empleados (cedula VARCHAR(30) PRIMARY KEY, salario REAL)"
            ))
            conn.execute(text(
                "INSERT INTO salarios_empleados (cedula, salario) VALUES "
                "('1', 240000), ('2', 480000)"
            ))
            # cedula '3' queda deliberadamente SIN salario (empleado "sin_salario")

        Session = sessionmaker(bind=self.engine)
        self.db = Session()

        def nov(cedula, nombre, area, tipo, horas, sede="PRINCIPAL", archivo="072025.xlsx", periodo="2025-07"):
            return NovedadNomina(
                archivo_origen=archivo, hoja_origen="H", cedula=cedula,
                nombre_empleado=nombre, area=area, sede=sede,
                tipo_novedad=tipo, dias=horas, unidad="horas",
                periodo=periodo, es_valido=1,
            )

        self.db.add_all([
            nov("1", "ANA", "URGENCIAS", "RECARGO NOCTURNO", 6),
            nov("1", "ANA", "URGENCIAS", "RECARGO NOCTURNO", 4),
            nov("2", "LUIS", "UCI", "RECARGO NOCTURNO", 5),
            nov("2", "LUIS", "UCI", "HORAS EXTRAS DIURNAS", 8),
            nov("3", "PEPE", "UCI", "RECARGO NOCTURNO", 3),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self._tmp_path):
            os.remove(self._tmp_path)

    def test_panel_calcula_valor_esperado_por_factor(self):
        panel = svc.get_panel_horas_extras(self.db, {})
        fila = next(t for t in panel["valor_por_tipo"] if t["tipo"] == "RECARGO NOCTURNO")
        # (6+4)*1000*0.35 [ANA] + 5*2000*0.35 [LUIS] + 3*sin_salario(0) [PEPE]
        # valor-hora = salario/240 -> ANA: 240000/240=1000, LUIS: 480000/240=2000
        self.assertEqual(fila["eventos"], 4)
        self.assertAlmostEqual(fila["horas"], 18.0, places=1)
        self.assertAlmostEqual(fila["valor"], 7000.0, delta=0.5)
        self.assertEqual(fila["factor"], 0.35)

    def test_detalle_cuadra_exactamente_con_fila_del_panel(self):
        panel = svc.get_panel_horas_extras(self.db, {})
        fila = next(t for t in panel["valor_por_tipo"] if t["tipo"] == "RECARGO NOCTURNO")

        detalle = svc.get_detalle_horas_extras_tipo(self.db, {}, "RECARGO NOCTURNO")

        self.assertEqual(detalle["total_eventos"], fila["eventos"])
        self.assertAlmostEqual(detalle["total_horas"], fila["horas"], places=1)
        self.assertAlmostEqual(detalle["total_valor"], fila["valor"], delta=0.5)
        self.assertEqual(detalle["factor"], fila["factor"])
        self.assertEqual(detalle["total_empleados"], 3)

    def test_empleado_sin_salario_se_marca_y_no_suma_valor(self):
        detalle = svc.get_detalle_horas_extras_tipo(self.db, {}, "RECARGO NOCTURNO")
        pepe = next(e for e in detalle["data"] if e["cedula"] == "3")
        self.assertTrue(pepe["sin_salario"])
        self.assertEqual(pepe["valor"], 0)
        self.assertEqual(pepe["eventos"], 1)
        self.assertAlmostEqual(pepe["horas"], 3.0, places=1)

    def test_detalle_respeta_filtro_de_area(self):
        detalle_uci = svc.get_detalle_horas_extras_tipo(self.db, {"area": "UCI"}, "RECARGO NOCTURNO")
        self.assertEqual({e["cedula"] for e in detalle_uci["data"]}, {"2", "3"})

    def test_tipo_inexistente_devuelve_vacio_sin_error(self):
        detalle = svc.get_detalle_horas_extras_tipo(self.db, {}, "TIPO_QUE_NO_EXISTE")
        self.assertEqual(detalle["total_empleados"], 0)
        self.assertEqual(detalle["data"], [])

    def test_orden_por_valor_descendente(self):
        detalle = svc.get_detalle_horas_extras_tipo(self.db, {}, "RECARGO NOCTURNO")
        valores = [e["valor"] for e in detalle["data"]]
        self.assertEqual(valores, sorted(valores, reverse=True))


@unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy no instalado (CI hermetico no lo requiere)")
class TestHeFactoresFuenteUnica(unittest.TestCase):
    """HE_FACTORES es la fuente de verdad de los multiplicadores legales;
    congela los valores para detectar cualquier cambio accidental."""

    EXPECTED = {
        "HORAS EXTRAS DIURNAS": 1.25,
        "HORAS EXTRAS NOCTURNAS": 1.75,
        "HORAS EXTRAS DIURNAS FESTIVAS": 2.00,
        "HORAS EXTRAS NOCTURNAS FESTIVAS": 2.50,
        "RECARGO FESTIVO": 0.75,
        "RECARGO FESTIVO NOCTURNO": 1.10,
        "RECARGO NOCTURNO": 0.35,
    }

    def test_factores_congelados(self):
        self.assertEqual(svc.HE_FACTORES, self.EXPECTED)

    def test_tipo_desconocido_usa_factor_uno(self):
        self.assertEqual(svc.HE_FACTORES.get("PERMISO", 1.0), 1.0)
        self.assertEqual(svc.HE_FACTORES.get("DISPONIBILIDAD", 1.0), 1.0)


if __name__ == "__main__":
    unittest.main()
