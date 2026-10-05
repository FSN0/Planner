from pathlib import Path
import re

heads = set()
parents = set()
for p in Path('migrations/versions').glob('*.py'):
    t = p.read_text(encoding='utf-8', errors='ignore')
    m = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", t, re.M)
    d = re.search(r"^down_revision\s*=\s*([^\n]+)", t, re.M)
    if not m:
        continue
    rev = m.group(1)
    heads.add(rev)
    if d:
        raw = d.group(1).strip()
        if raw not in ('None', 'none'):
            for x in re.findall(r"['\"]([^'\"]+)['\"]", raw):
                parents.add(x)
print('heads:', sorted(heads - parents))
