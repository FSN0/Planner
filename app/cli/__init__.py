# app/cli/__init__.py
from app.cli.fichajes import fichajes_cli


def register_cli(app):
    app.cli.add_command(fichajes_cli)
