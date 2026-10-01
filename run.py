import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    # debug SOLO si se activa explícitamente FLASK_DEBUG=true (desarrollo local).
    # En producción se sirve con gunicorn (ver Dockerfile), no con este bloque.
    debug = os.environ.get('FLASK_DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
    app.run(host='0.0.0.0', port=5000, debug=debug)
