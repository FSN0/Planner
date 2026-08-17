#!/usr/bin/env python3
"""
Read _missing_report.json, skip false positives, generate EN/PT/FR
translations, and merge into extra/{en,pt,fr}.json.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(ROOT, 'app', 'i18n')
EXTRA = os.path.join(I18N, 'extra')
REPORT = os.path.join(I18N, '_missing_report.json')
TRANS_DIR = os.path.join(ROOT, 'scripts', '_translations')

def load(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

def main():
    for lang in ('en', 'pt', 'fr'):
        trans_path = os.path.join(TRANS_DIR, f'{lang}.json')
        trans = load(trans_path)
        if not trans:
            print(f'No translations at {trans_path}')
            continue

        extra_path = os.path.join(EXTRA, f'{lang}.json')
        existing = load(extra_path)

        added = 0
        for k, v in trans.items():
            if k not in existing:
                existing[k] = v
                added += 1

        save(extra_path, existing)
        print(f'{lang}: +{added} keys (total {len(existing)})')

if __name__ == '__main__':
    main()
