from pathlib import Path

p = Path("/opt/soltec/planner/_diag_estado_odoo.sh")
t = p.read_text(encoding="utf-8")
start = t.find('echo "=== ODOO FIELD PROBE (web container) ==="')
end = t.find('echo "=== DONE ==="')
if start < 0 or end < 0:
    raise SystemExit(f"markers missing start={start} end={end}")
new = """echo \"=== ODOO FIELD PROBE (web container) ===\"
docker compose exec -T web python /app/_diag_odoo_probe.py
docker compose exec -T web python /app/_diag_odoo_probe2.py
docker compose exec -T web python /app/_diag_odoo_probe3.py

"""
p.write_text(t[:start] + new + t[end:], encoding="utf-8")
print("patched")
