"""Permisos por perfil: analista ve empleados por período y exporta Excel/PDF."""
import unittest

from app.services.permissions import (
    PERM_EMPLEADOS_PERIODO,
    PERM_EXPORT_EXCEL,
    PERM_EXPORT_PDF,
    PERM_ETL,
    PERM_USUARIOS,
    catalog_for_role,
    permissions_for_role,
    role_has_permission,
)


class TestRolePermissions(unittest.TestCase):

    def test_analyst_can_see_empleados_and_export_excel(self):
        perms = permissions_for_role("analyst")
        self.assertIn(PERM_EMPLEADOS_PERIODO, perms)
        self.assertIn(PERM_EXPORT_EXCEL, perms)
        self.assertIn(PERM_EXPORT_PDF, perms)
        self.assertTrue(role_has_permission("analyst", PERM_EMPLEADOS_PERIODO))
        self.assertTrue(role_has_permission("analyst", PERM_EXPORT_EXCEL))

    def test_admin_has_same_plus_admin_actions(self):
        self.assertTrue(role_has_permission("admin", PERM_EMPLEADOS_PERIODO))
        self.assertTrue(role_has_permission("admin", PERM_EXPORT_EXCEL))
        self.assertTrue(role_has_permission("admin", PERM_USUARIOS))
        self.assertTrue(role_has_permission("admin", PERM_ETL))

    def test_readonly_cannot_see_empleados_or_export(self):
        self.assertEqual(permissions_for_role("readonly"), [])
        self.assertFalse(role_has_permission("readonly", PERM_EMPLEADOS_PERIODO))
        self.assertFalse(role_has_permission("readonly", PERM_EXPORT_EXCEL))

    def test_unknown_role_has_no_permissions(self):
        self.assertEqual(permissions_for_role("no-existe"), [])
        self.assertFalse(role_has_permission(None, PERM_EXPORT_EXCEL))

    def test_analyst_catalog_marks_empleados_and_excel_granted(self):
        by_code = {row["code"]: row for row in catalog_for_role("analyst")}
        self.assertTrue(by_code[PERM_EMPLEADOS_PERIODO]["granted"])
        self.assertTrue(by_code[PERM_EXPORT_EXCEL]["granted"])
        self.assertFalse(by_code[PERM_USUARIOS]["granted"])
