# Logos SignaPlan

Source of truth for SignaPlan brand PNG assets.

## Canonical filenames

Place these files in this directory (exact names):

| Source file                      | Synced to `app/static/img/brand/`   |
|----------------------------------|-------------------------------------|
| `Logo.png`                       | `logo-mark.png`                     |
| `Logo + Nombre.png`              | `logo-horizontal.png` (transparente)|
| `Logo + Nombre_con_fondo.png`    | `logo-horizontal-on-dark.png` (hero)|
| `Nombre.png`                     | `logo-wordmark.png`                 |
| `Wallpaper.png`                  | `wallpaper.png`                     |

## Archived assets

Other `*_con_fondo.png` files (mark/wordmark) are kept for reference.
`Logo + Nombre_con_fondo.png` **is** synced: used on the dark hero.

## Transparency

Exports that still have an opaque white canvas (common with some AI tools)
are cleaned automatically during sync via `scripts/knockout_brand_white.py`
(near-white pixels → alpha). `Logo.png` / `Nombre.png` usually already have
real transparency; `Logo + Nombre.png` often needs this step.

## Syncing into the app

`make dev` and `make prod-deploy` (via `scripts/deploy.sh`) automatically copy
the canonical PNGs into `app/static/img/brand/` before the Docker image build.

Manual sync only:

```bash
make sync-brand
# or
bash scripts/sync_brand_assets.sh
```

If this directory is missing or empty of the expected files, the sync script
prints a warning and exits 0 so deploys are not blocked.

