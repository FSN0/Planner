#!/usr/bin/env python3
"""Añade la columna solicitudes.notas si aún no existe."""
from sqlalchemy import inspect, text

from app import create_app, db

app = create_app()

with app.app_context():
    inspector = inspect(db.engine)
    columns = {col["name"] for col in inspector.get_columns("solicitudes")}
    if "notas" in columns:
        print("La columna solicitudes.notas ya existe.")
    else:
        db.session.execute(text("ALTER TABLE solicitudes ADD COLUMN notas TEXT"))
        db.session.commit()
        print("Columna solicitudes.notas creada correctamente.")
