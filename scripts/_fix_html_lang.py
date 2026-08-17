from pathlib import Path

root = Path("app/templates")
old = '<html lang="es">'
new = '<html lang="{{ current_locale|default(\'es\') }}">'
n = 0
for p in root.rglob("*.html"):
    t = p.read_text(encoding="utf-8")
    if old not in t:
        continue
    p.write_text(t.replace(old, new), encoding="utf-8")
    n += 1
    print(p)
print("changed", n)
