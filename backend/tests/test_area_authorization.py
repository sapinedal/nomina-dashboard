"""
Tests de regresion para la autorizacion por areas (many-to-many usuario<->area).

Cubre:
  - dashboard_service._effective_areas / _apply_area_filter / _area_sql_clause
    (los 3 puntos de union usados por TODAS las consultas del dashboard)
  - Comportamiento fail-closed: usuario restringido sin areas asignadas no ve nada
  - Admin sin restriccion ve todo, igual que antes de este cambio
  - Un usuario restringido que pide un area ajena NO la recibe (se ignora, se
    aplican sus propias areas -- nunca se confia en lo que mande el frontend)
  - get_filter_options acota tambien areas/sedes/tipos al usuario restringido
  - UserArea: relacion many-to-many, restriccion unique (user_id, area)

Depende de SQLAlchemy -- se salta limpio si no esta instalado (mismo criterio
que test_horas_extras_service.py, ver su docstring).
"""
import os
import tempfile
import unittest

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

if HAS_SQLALCHEMY:
    from app.models.nomina import NovedadNomina
    from app.models.user import User, UserArea
    from app.services import dashboard_service as svc


@unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy no instalado (CI hermetico no lo requiere)")
class TestAreaAuthorization(unittest.TestCase):

    def setUp(self):
        self._tmp_path = tempfile.mktemp(suffix=".db")
        self.engine = create_engine(f"sqlite:///{self._tmp_path}")
        NovedadNomina.__table__.create(self.engine)
        User.__table__.create(self.engine)
        UserArea.__table__.create(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE salarios_empleados (cedula VARCHAR(30) PRIMARY KEY, salario REAL)"
            ))

        Session = sessionmaker(bind=self.engine)
        self.db = Session()

        def nov(cedula, nombre, area, tipo="PRESENTE EN NOMINA", horas=None, dias=None,
                unidad="dias", archivo="072025.xlsx", periodo="2025-07"):
            return NovedadNomina(
                archivo_origen=archivo, hoja_origen="H", cedula=cedula,
                nombre_empleado=nombre, area=area, sede="PRINCIPAL",
                tipo_novedad=tipo, dias=(horas if horas is not None else dias),
                unidad=unidad, periodo=periodo, es_valido=1,
            )

        # 3 áreas, con datos distinguibles para verificar el filtrado
        self.db.add_all([
            nov("1", "ANA",   "NOMINA",       tipo="PERMISO",  dias=1, unidad="dias"),
            nov("2", "LUIS",  "SST",          tipo="PERMISO",  dias=1, unidad="dias"),
            nov("3", "PEPE",  "SELECCION",    tipo="PERMISO",  dias=1, unidad="dias"),
            nov("4", "MARIA", "CONTABILIDAD", tipo="PERMISO",  dias=1, unidad="dias"),
            nov("5", "JUAN",  "COMPRAS",      tipo="PERMISO",  dias=1, unidad="dias"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self._tmp_path):
            os.remove(self._tmp_path)

    # ── _effective_areas: la función de más bajo nivel, cubre todos los casos ──

    def test_admin_sin_filtro_no_restringe(self):
        self.assertIsNone(svc._effective_areas({"_allowed_areas": None}))

    def test_admin_con_filtro_usa_solo_ese_filtro(self):
        self.assertEqual(svc._effective_areas({"_allowed_areas": None, "area": "NOMINA"}), ["NOMINA"])

    def test_restringido_sin_elegir_area_ve_todas_las_suyas(self):
        allowed = ["NOMINA", "SST", "SELECCION"]
        self.assertEqual(sorted(svc._effective_areas({"_allowed_areas": allowed})), sorted(allowed))

    def test_restringido_elige_una_de_las_suyas(self):
        allowed = ["NOMINA", "SST", "SELECCION"]
        self.assertEqual(svc._effective_areas({"_allowed_areas": allowed, "area": "SST"}), ["SST"])

    def test_restringido_elige_area_ajena_se_ignora_y_usa_las_suyas(self):
        """Núcleo de 'nunca confiar en el frontend': aunque el cliente mande
        ?area=CONTABILIDAD, un usuario restringido a NOMINA/SST no debe
        poder verla -- se le devuelven SUS áreas, no la pedida."""
        allowed = ["NOMINA", "SST"]
        result = svc._effective_areas({"_allowed_areas": allowed, "area": "CONTABILIDAD"})
        self.assertEqual(sorted(result), sorted(allowed))
        self.assertNotIn("CONTABILIDAD", result)

    def test_restringido_sin_areas_asignadas_falla_cerrado(self):
        self.assertEqual(svc._effective_areas({"_allowed_areas": []}), [])

    # ── Verificación end-to-end contra consultas reales del servicio ──

    def test_kpis_admin_ve_todas_las_areas(self):
        kpis = svc.get_kpis(self.db, {"_allowed_areas": None})
        self.assertEqual(kpis.total_areas, 5)

    def test_kpis_restringido_solo_ve_sus_areas(self):
        kpis = svc.get_kpis(self.db, {"_allowed_areas": ["NOMINA", "SST"]})
        self.assertEqual(kpis.total_areas, 2)
        self.assertEqual(kpis.total_novedades, 2)

    def test_kpis_restringido_sin_areas_ve_cero(self):
        kpis = svc.get_kpis(self.db, {"_allowed_areas": []})
        self.assertEqual(kpis.total_novedades, 0)
        self.assertEqual(kpis.total_areas, 0)

    def test_novedades_por_area_respeta_restriccion(self):
        chart = svc.get_novedades_por_area(self.db, {"_allowed_areas": ["SELECCION"]})
        self.assertEqual(chart.labels, ["SELECCION"])

    def test_table_data_respeta_restriccion(self):
        result = svc.get_table_data(self.db, {"_allowed_areas": ["COMPRAS"]})
        self.assertEqual(result.total, 1)
        self.assertEqual(result.data[0]["area"], "COMPRAS")

    def test_filter_options_admin_ve_todas_las_areas(self):
        opts = svc.get_filter_options(self.db, allowed_areas=None)
        self.assertEqual(len(opts["areas"]), 5)

    def test_filter_options_restringido_solo_ve_sus_areas_en_dropdown(self):
        opts = svc.get_filter_options(self.db, allowed_areas=["NOMINA", "SST"])
        self.assertEqual(sorted(opts["areas"]), ["NOMINA", "SST"])

    def test_filter_options_restringido_sin_areas_ve_dropdown_vacio(self):
        opts = svc.get_filter_options(self.db, allowed_areas=[])
        self.assertEqual(opts["areas"], [])


@unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy no instalado (CI hermetico no lo requiere)")
class TestUserAreaModel(unittest.TestCase):
    """Relación many-to-many User<->UserArea: creación, cascade, unicidad."""

    def setUp(self):
        self._tmp_path = tempfile.mktemp(suffix=".db")
        self.engine = create_engine(f"sqlite:///{self._tmp_path}")
        User.__table__.create(self.engine)
        UserArea.__table__.create(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self._tmp_path):
            os.remove(self._tmp_path)

    def _crear_usuario(self, username="luisa"):
        u = User(username=username, email=f"{username}@x.com", full_name=username,
                  hashed_password="x", role="readonly", is_active=True)
        self.db.add(u)
        self.db.commit()
        self.db.refresh(u)
        return u

    def test_usuario_con_varias_areas(self):
        u = self._crear_usuario()
        self.db.add_all([
            UserArea(user_id=u.id, area="NOMINA", created_by="admin"),
            UserArea(user_id=u.id, area="SST", created_by="admin"),
            UserArea(user_id=u.id, area="SELECCION", created_by="admin"),
        ])
        self.db.commit()
        self.db.refresh(u)
        self.assertEqual(sorted(u.areas), ["NOMINA", "SELECCION", "SST"])

    def test_area_repetida_para_mismo_usuario_falla(self):
        u = self._crear_usuario()
        self.db.add(UserArea(user_id=u.id, area="NOMINA", created_by="admin"))
        self.db.commit()
        self.db.add(UserArea(user_id=u.id, area="NOMINA", created_by="admin"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_misma_area_en_dos_usuarios_distintos_es_valido(self):
        """La restricción unique es (user_id, area), no area sola -- muchos
        usuarios pueden compartir la misma área (Área -> muchos usuarios)."""
        u1 = self._crear_usuario("luisa")
        u2 = self._crear_usuario("carlos")
        self.db.add_all([
            UserArea(user_id=u1.id, area="NOMINA", created_by="admin"),
            UserArea(user_id=u2.id, area="NOMINA", created_by="admin"),
        ])
        self.db.commit()  # no debe lanzar
        self.assertEqual(self.db.query(UserArea).filter(UserArea.area == "NOMINA").count(), 2)

    def test_eliminar_usuario_elimina_sus_areas_en_cascada(self):
        u = self._crear_usuario()
        self.db.add(UserArea(user_id=u.id, area="NOMINA", created_by="admin"))
        self.db.commit()
        uid = u.id
        self.db.delete(u)
        self.db.commit()
        self.assertEqual(self.db.query(UserArea).filter(UserArea.user_id == uid).count(), 0)

    def test_usuario_sin_areas_asignadas_tiene_lista_vacia(self):
        u = self._crear_usuario()
        self.assertEqual(u.areas, [])


if __name__ == "__main__":
    unittest.main()
