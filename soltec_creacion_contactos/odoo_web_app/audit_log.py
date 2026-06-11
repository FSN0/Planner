"""Registro de auditoría local (SQLite) para la app de altas."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'audit.db')

ACTION_LABELS = {
    'login_signaplan': 'Inicio de sesión (email)',
    'login_bim': 'Inicio de sesión (BIM)',
    'login_sso': 'Inicio de sesión (SignaPlan SSO)',
    'logout': 'Cierre de sesión',
    'login_failed': 'Intento de acceso fallido',
    'alta_trabajador': 'Alta de trabajador',
    'alta_contrato': 'Alta de contrato',
}


def _ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_id TEXT,
                user_name TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                auth_method TEXT
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)')
        conn.commit()


@contextmanager
def _conn():
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_event(user_id, user_name, action, details=None, ip_address=None, auth_method=None):
    payload = None
    if details is not None:
        payload = json.dumps(details, ensure_ascii=False)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO audit_logs (created_at, user_id, user_name, action, details, ip_address, auth_method)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (now, str(user_id) if user_id is not None else None, user_name or '—', action, payload, ip_address, auth_method),
        )


def list_logs(limit=200, action=None, q=None):
    query = 'SELECT * FROM audit_logs WHERE 1=1'
    params = []
    if action:
        query += ' AND action = ?'
        params.append(action)
    if q:
        query += ' AND (user_name LIKE ? OR details LIKE ?)'
        params.extend([f'%{q}%', f'%{q}%'])
    query += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def action_label(action):
    return ACTION_LABELS.get(action, action)
