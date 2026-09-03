"""Tests del registro de roles dinámicos."""
from app.services.role_registry_service import slugify_role_key


class TestRoleSlugify:
    def test_basic(self):
        assert slugify_role_key('Coordinación RRHH') == 'coordinacion_rrhh'

    def test_strips_junk(self):
        assert slugify_role_key('  Empleo!!  ') == 'empleo'
