#!/usr/bin/env python3
"""Script simple para ejecutar pytest y mostrar resultados"""
import subprocess
import sys
import os

# Configurar variables de entorno
os.environ['TEST_DATABASE_URL'] = 'postgresql://postgres:postgres@localhost:5432/gestion_obra_test'
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = 'true'
os.environ['SECRET_KEY'] = 'test-secret-key-super-segura-para-tests'
os.environ['ENCRYPTION_KEY'] = 'hIQxMPbaYZ_WxJx4w3d9OaV8gQSNJFnKHQVfQPl7S1k='
os.environ['CELERY_TASK_ALWAYS_EAGER'] = 'true'
os.environ['MAIL_SUPPRESS_SEND'] = 'true'

print("="*80)
print("EJECUTANDO TESTS DE LA APLICACIÓN")
print("="*80)
print()

# Ejecutar pytest
cmd = [
    'pytest',
    'tests/',
    '-x',  # Parar al primer fallo
    '-v',  # Verbose
    '--tb=short',  # Traceback corto
]

result = subprocess.run(cmd, capture_output=False, text=True)
sys.exit(result.returncode)
