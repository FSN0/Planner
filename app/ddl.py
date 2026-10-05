# app/ddl.py
#
# DDL que no se puede expresar con SQLAlchemy y que debe aplicarse igual en
# producción (vía migración) que en los tests. Vive aquí, y no duplicado en
# cada sitio, para que no puedan divergir: la protección que se prueba es
# literalmente la misma que se despliega.
#
# Si alguna vez hay que cambiar estas reglas, se añade una migración nueva que
# las vuelva a aplicar; no basta con editar este fichero.

# El disparador rechaza cualquier UPDATE, DELETE o TRUNCATE sobre el libro de
# fichajes, incluso desde una consola SQL. Un superusuario de PostgreSQL podría
# desactivarlo, pero como cada fila va encadenada por hash con la anterior, la
# manipulación seguiría saliendo en `flask fichajes verificar`.
FICHAJES_FUNCION_BLOQUEO = """
CREATE OR REPLACE FUNCTION {schema}.fichajes_eventos_solo_insercion()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'El libro de fichajes es inalterable: no se admite % sobre %.',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation',
              HINT = 'Para corregir un fichaje, registre un evento de anulación.';
END;
$$ LANGUAGE plpgsql;
"""

FICHAJES_TRIGGER_FILAS = """
DROP TRIGGER IF EXISTS trg_fichajes_eventos_no_update
    ON {schema}.fichajes_eventos;
CREATE TRIGGER trg_fichajes_eventos_no_update
    BEFORE UPDATE OR DELETE ON {schema}.fichajes_eventos
    FOR EACH ROW
    EXECUTE FUNCTION {schema}.fichajes_eventos_solo_insercion();
"""

FICHAJES_TRIGGER_TRUNCATE = """
DROP TRIGGER IF EXISTS trg_fichajes_eventos_no_truncate
    ON {schema}.fichajes_eventos;
CREATE TRIGGER trg_fichajes_eventos_no_truncate
    BEFORE TRUNCATE ON {schema}.fichajes_eventos
    FOR EACH STATEMENT
    EXECUTE FUNCTION {schema}.fichajes_eventos_solo_insercion();
"""

FICHAJES_SENTENCIAS_PROTECCION = (
    FICHAJES_FUNCION_BLOQUEO,
    FICHAJES_TRIGGER_FILAS,
    FICHAJES_TRIGGER_TRUNCATE,
)

FICHAJES_SENTENCIAS_RETIRADA = (
    "DROP TRIGGER IF EXISTS trg_fichajes_eventos_no_truncate "
    "ON {schema}.fichajes_eventos;",
    "DROP TRIGGER IF EXISTS trg_fichajes_eventos_no_update "
    "ON {schema}.fichajes_eventos;",
    "DROP FUNCTION IF EXISTS {schema}.fichajes_eventos_solo_insercion();",
)


def proteger_libro_fichajes(ejecutar, schema):
    """Aplica la protección de inmutabilidad sobre el esquema indicado."""
    for sentencia in FICHAJES_SENTENCIAS_PROTECCION:
        ejecutar(sentencia.format(schema=schema))


def desproteger_libro_fichajes(ejecutar, schema):
    """Retira la protección. Solo para downgrade de migración y limpieza de tests."""
    for sentencia in FICHAJES_SENTENCIAS_RETIRADA:
        ejecutar(sentencia.format(schema=schema))
