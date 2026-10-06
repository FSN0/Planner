#!/usr/bin/env bash
cat >> /opt/soltec/planner/_diag_estado_odoo_out.txt <<'EOF'

=== SUMMARY (generated) ===
Containers: all up (web/celery/db/redis/caddy)
Schemas: public + 9 tenants (NO tenant_paco)
Column registros_fichajes.estado_odoo: EXISTS on all tenant_* schemas; NOT on public
Alembic: c7d8e9f0a1b2 on public + all tenants (b6c7d8e9f0a1 applied; d8e9f0a1b2c3 NOT applied)
registros_fichajes.estado_odoo: 100% NULL across all tenants with data
  tenant_soltec: 16158 total / 16158 null / 0 not-null
  tenant_s2gp: 199/199/0
  tenant_le_bras_amenagement: 190/190/0
  tenant_gaboni...: 200/200/0
  tenant_fresneda: 173/173/0
  tenant_elorn..._29470: 152/152/0
  tenant_elorn...: 1/1/0
certificacion_lineas.estado_fichaje: only tenant_soltec has rows: 3788/3788 null
Odoo probe (tenant soltec, Adapter(tenant_id)):
  hr.attendance: FOUND_FIELD=None (no state/estado field; selections: in_mode,out_mode,tipo_desplazamiento_*)
  partner.attendance: FOUND_FIELD=state selection=[draft/Borrador, validated/Validado, invoiced/Facturado]
  get_fichajes_diarios today: 97 rows -> estado_odoo NULL=82 (hr), borrador=15 (partner)
Logs: warning "Odoo hr.attendance: no se encontró campo estado draft/validated/invoiced"
Root cause hypothesis: Odoo hr.attendance (majority of fichajes) has no draft/validated/invoiced field,
so adapter cannot populate estado_odoo; certificacion_lineas.estado_fichaje stays null.
partner.attendance.state works, but is minority of volume and DB still all-null historically.
EOF
echo appended
