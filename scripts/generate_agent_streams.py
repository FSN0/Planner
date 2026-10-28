#!/usr/bin/env python3
"""Genera streams_json: un flujo por cada tabla/vista de tenant_soltec."""
from __future__ import annotations

import json
import sys
from collections import defaultdict

# Columnas candidatas a cursor, en orden de preferencia.
_CURSOR_COLS = (
    "updated_at",
    "created_at",
    "timestamp",
    "registrado_en",
    "ocurrido_en",
    "fecha_auditoria",
    "check_in",
    "fecha_sincronizacion",
    "fecha_importacion",
    "visto_en",
    "resolved_at",
    "enviada_at",
    "aceptada_at",
    "completed_at",
    "validado_at",
    "acknowledged_at",
    "last_read_at",
    "deactivated_at",
    "flush_after",
    "fecha",
    "fecha_inicio",
)

_SKIP = {"alembic_version"}


def _cursor_expr(cols: set[str]) -> str:
    parts = []
    for name in _CURSOR_COLS:
        if name not in cols:
            continue
        if name in {"fecha", "fecha_inicio"}:
            parts.append(f"t.{name}::timestamp")
        else:
            parts.append(f"t.{name}")
    if "id" in cols:
        parts.append("to_timestamp(COALESCE(t.id::double precision, 0))")
    parts.append("TIMESTAMP '1970-01-01'")
    if len(parts) == 1:
        return parts[0]
    return "COALESCE(" + ", ".join(parts) + ")"


def _id_expr(cols: list[str], cols_set: set[str]) -> str:
    if "id" in cols_set:
        return "t.id::text"
    # Tablas puente sin id: concatenar columnas.
    keys = [c for c in cols if c.endswith("_id") or c in {"clave", "version_num"}]
    if not keys:
        keys = list(cols)[:3]
    inner = ", ".join(f"t.{k}::text" for k in keys)
    return f"concat_ws(':', {inner})"


def build_streams(rows: list[tuple[str, str]]) -> dict[str, str]:
    by_table: dict[str, list[str]] = defaultdict(list)
    for table, col in rows:
        by_table[table].append(col)

    streams: dict[str, str] = {}
    for table, cols in sorted(by_table.items()):
        if table in _SKIP:
            continue
        cols_set = set(cols)
        id_expr = _id_expr(cols, cols_set)
        cur = _cursor_expr(cols_set)
        # Schema cualificado: funciona aunque search_path falle.
        sql = (
            f"SELECT {id_expr} AS id, {cur} AS updated_at, t.* "
            f"FROM tenant_soltec.{table} t "
            f"WHERE {cur} > $1 "
            f"ORDER BY 2 ASC LIMIT 500"
        )
        streams[table] = sql
    return streams


def main() -> int:
    # stdin: "table|col" por línea (salida de psql -At -F '|')
    rows: list[tuple[str, str]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line or "|" not in line:
            continue
        table, col = line.split("|", 1)
        rows.append((table, col))
    streams = build_streams(rows)
    json.dump(streams, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
