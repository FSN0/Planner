"""
Tests unitarios del servicio de importación (detección de columnas).
"""
import pandas as pd


class TestImportColumnDetection:
    def test_detect_obras_spanish_headers(self):
        from app.services.import_service import detect_columns

        df = pd.DataFrame(columns=[
            "Código", "Nombre", "Cliente", "Dirección", "Fecha de inicio", "Fecha de fin",
        ])
        mapping = detect_columns(df, "obras")

        assert mapping["codigo"] == "Código"
        assert mapping["nombre"] == "Nombre"
        assert mapping["cliente"] == "Cliente"
        assert mapping["direccion"] == "Dirección"
        assert mapping["fecha_inicio"] == "Fecha de inicio"
        assert mapping["fecha_fin"] == "Fecha de fin"

    def test_detect_obras_fuzzy_variants(self):
        from app.services.import_service import detect_columns

        df = pd.DataFrame(columns=[
            "COD", "Titulo obra", "Promotor", "Ubicacion", "Inicio", "Fin",
        ])
        mapping = detect_columns(df, "obras")

        assert mapping["codigo"] == "COD"
        assert mapping["nombre"] == "Titulo obra"
        assert mapping["cliente"] == "Promotor"
        assert mapping["direccion"] == "Ubicacion"
        assert mapping["fecha_inicio"] == "Inicio"
        assert mapping["fecha_fin"] == "Fin"

    def test_detect_users_headers(self):
        from app.services.import_service import detect_columns

        df = pd.DataFrame(columns=[
            "Email", "Rol", "Nombre", "Apellidos", "DNI", "Empresa",
            "Contraseña", "Activo",
        ])
        mapping = detect_columns(df, "users")

        assert mapping["email"] == "Email"
        assert mapping["rol"] == "Rol"
        assert mapping["nombre"] == "Nombre"
        assert mapping["apellidos"] == "Apellidos"
        assert mapping["dni"] == "DNI"
        assert mapping["empresa"] == "Empresa"
        assert mapping["password"] == "Contraseña"
        assert mapping["activo"] == "Activo"

    def test_detect_companies_headers(self):
        from app.services.import_service import detect_columns

        df = pd.DataFrame(columns=[
            "Razón Social", "CIF", "Código", "Gremio", "Correo", "Observaciones",
        ])
        mapping = detect_columns(df, "companies")

        assert mapping["nombre"] == "Razón Social"
        assert mapping["nif"] == "CIF"
        assert mapping["code"] == "Código"
        assert mapping["gremio"] == "Gremio"
        assert mapping["email"] == "Correo"
        assert mapping["descripcion"] == "Observaciones"

    def test_detect_unmapped_when_no_match(self):
        from app.services.import_service import detect_columns

        df = pd.DataFrame(columns=["Foo", "Bar", "Baz"])
        mapping = detect_columns(df, "obras")

        assert mapping["nombre"] is None
        assert mapping["fecha_inicio"] is None
