# Integración Odoo → SignaPlan (avisos en tiempo real)

Documento para el equipo de Odoo (humano o IA).  
SignaPlan **ya tiene el receptor implementado**. En Odoo solo hay que **avisar** cuando cambie un registro; **no hay que enviar la ficha completa**.

---

## Idea (importante)

1. En Odoo ocurre un `create` / `write` / `unlink` / archivo de un modelo.
2. Odoo hace un `POST` JSON corto a SignaPlan: `{ model, id, action }`.
3. SignaPlan responde **HTTP 202** al instante.
4. SignaPlan, en segundo plano, tira por **XML-RPC** los mismos datos que ya sincroniza hoy (mismos campos, mismas reglas).
5. La sync nocturna de SignaPlan sigue como red de seguridad.

**No envíes el registro completo.** Con `model`, `id` y `action` basta.  
Si mandáis el payload entero, SignaPlan **lo ignora**: solo usa el aviso para despertar el sync.

---

## Endpoint

| Campo | Valor |
|--------|--------|
| Método | `POST` |
| URL | `https://planner.soltechgrupo.es/api/v6/odoo/hooks/changed` |
| Content-Type | `application/json` |
| Auth | Header `X-Odoo-Sync-Key: <clave>` |

Alternativa de auth (también válida):

```http
Authorization: Bearer <clave>
```

### Clave

La clave la genera SignaPlan por espacio/empresa.  
Un admin la ve (y puede regenerarla) en:

**SignaPlan → Integraciones → Centro de sincronización Odoo → “Avisos en tiempo real”.**

Si regeneran la clave en SignaPlan, hay que actualizarla en Odoo: la anterior deja de valer.

---

## Cuerpo JSON

### Campos

| Campo | Obligatorio | Tipo | Descripción |
|--------|-------------|------|-------------|
| `model` | Sí* | string | Modelo técnico Odoo (`res.partner`, `hr.employee`, …). |
| `id` | Sí** | int | ID del registro en Odoo. |
| `action` | Recomendado | string | `create`, `write`, `unlink`, `archive`, `unarchive` o `refresh`. Por defecto se asume `write`. |
| `event_id` | Recomendado | string | UUID u otro id único del aviso (trazas / deduplicación en Odoo). |
| `write_date` | Opcional | string | Timestamp ISO o texto Odoo; solo informativo. |
| `parent_id` | Opcional | int | Útil en contactos (`res.partner` hijo → empresa padre). |

\* También se acepta `resource` / `module` con alias (`empleados`, `obras`, …), pero lo preferido es `model`.  
\*\* Obligatorio salvo `action=refresh` (refresco de todo un módulo).

### Ejemplo mínimo

```http
POST /api/v6/odoo/hooks/changed HTTP/1.1
Host: planner.soltechgrupo.es
Content-Type: application/json
X-Odoo-Sync-Key: PEGA_AQUI_LA_CLAVE_DEL_PANEL
```

```json
{
  "event_id": "00000000-0000-0000-0000-000000000001",
  "action": "create",
  "model": "res.partner",
  "id": 12345,
  "write_date": "2026-09-07T09:00:00+02:00",
  "parent_id": 998
}
```

### Ejemplo curl (prueba manual)

```bash
curl -sS -X POST 'https://planner.soltechgrupo.es/api/v6/odoo/hooks/changed' \
  -H 'Content-Type: application/json' \
  -H 'X-Odoo-Sync-Key: PEGA_AQUI_LA_CLAVE_DEL_PANEL' \
  -d '{
    "event_id": "test-manual-001",
    "action": "write",
    "model": "hr.employee",
    "id": 42
  }'
```

Respuesta esperada si todo va bien: **HTTP 202** y JSON con `"accepted": true`.

---

## Modelos a enganchar

Disparar el aviso en **create**, **write**, **unlink** y **archive/unarchive** de:

| Modelo Odoo | Qué sincroniza SignaPlan | Prioridad |
|-------------|---------------------------|-----------|
| `res.partner` | Subcontratas y contactos | Obligatoria |
| `hr.employee` | Personal interno | Obligatoria |
| `bim.project` | Obras / proyectos BIM | Obligatoria |
| `hr.leave` | Ausencias / time off | Obligatoria |
| `fleet.vehicle` | Vehículos / flota | Obligatoria |
| `fleet.vehicle.odometer` | Odómetros (mismo módulo vehículos) | Recomendada |
| `hr.attendance` | Fichajes | **Opcional** (SignaPlan ya tiene cron cada ~30 min) |

Cualquier otro `fleet.*` también se trata como vehículos.  
Modelos que SignaPlan no conoce → responde **202** con `"ignored": true` (no reintentar).

---

## Respuestas HTTP

| Código | Significado | Qué hacer en Odoo |
|--------|-------------|-------------------|
| **202** | Aviso aceptado (o ignorado si el modelo no aplica) | Éxito. No reintentar. |
| **401** | Clave incorrecta o ausente | Parar. Revisar `X-Odoo-Sync-Key`. |
| **403** | Espacio sin módulo Odoo activo | Parar. Avisar a SignaPlan. |
| **404** | Host / espacio incorrecto | Parar. Debe ser `planner.soltechgrupo.es`. |
| **422** | Falta `id` (salvo `refresh`) o `id` no es entero | Corregir payload. No reintentar ciego. |
| **400** | JSON vacío/inválido | Corregir payload. |
| **5xx** | Error de servidor / cola | Reintentar con backoff (p. ej. 1s, 5s, 30s, 2min). |

**Regla:** reintentar solo ante **5xx** (y timeouts de red).  
Ante **4xx**, no spamear: el payload o la clave están mal.

---

## Debounce (recomendado en Odoo)

SignaPlan agrupa avisos del mismo módulo ~**8 segundos** antes de sincronizar.  
Aun así, en Odoo conviene:

- Tras un `write` masivo, no disparar un POST por cada campo si podéis.
- Opcional: debounce de ~5 s por `(model, id)` o por `model` antes de llamar.
- En imports masivos, preferid un único aviso por modelo con `action: "refresh"` al final, o unos pocos POSTs, no miles.

---

## Implementación sugerida en Odoo

Lo habitual es un módulo pequeño + `ir.actions.server` / `base.automation` / override de `create`/`write`/`unlink` / mixin, según versión.

### Pseudocódigo

```python
import json
import uuid
import logging
import requests  # o urllib si no hay requests

_logger = logging.getLogger(__name__)

SIGNAPLAN_HOOK_URL = "https://planner.soltechgrupo.es/api/v6/odoo/hooks/changed"
SIGNAPLAN_HOOK_KEY = "PEGA_AQUI_LA_CLAVE"  # mejor en ir.config_parameter

WATCHED_MODELS = {
    "res.partner",
    "hr.employee",
    "bim.project",
    "hr.leave",
    "fleet.vehicle",
    "fleet.vehicle.odometer",
    # "hr.attendance",  # opcional
}

def notify_signaplan(model, res_id, action, parent_id=None, write_date=None):
    if model not in WATCHED_MODELS and not str(model).startswith("fleet."):
        return
    payload = {
        "event_id": str(uuid.uuid4()),
        "action": action,          # create | write | unlink | archive | unarchive
        "model": model,
        "id": int(res_id),
    }
    if parent_id:
        payload["parent_id"] = int(parent_id)
    if write_date:
        payload["write_date"] = str(write_date)

    headers = {
        "Content-Type": "application/json",
        "X-Odoo-Sync-Key": SIGNAPLAN_HOOK_KEY,
    }
    try:
        # timeout corto: SignaPlan responde 202 sin esperar al sync
        r = requests.post(
            SIGNAPLAN_HOOK_URL,
            data=json.dumps(payload),
            headers=headers,
            timeout=5,
        )
        if r.status_code >= 500:
            # encolar reintento; no bloquear el save de Odoo
            _logger.warning("SignaPlan hook 5xx: %s %s", r.status_code, r.text)
        elif r.status_code >= 400:
            _logger.error("SignaPlan hook 4xx (no reintentar): %s %s", r.status_code, r.text)
        else:
            _logger.info("SignaPlan hook OK: %s", r.text)
    except Exception as exc:
        _logger.exception("SignaPlan hook red: %s", exc)
        # encolar reintento en job queue de Odoo
```

### Momentos en los que llamar

| Evento Odoo | `action` a enviar |
|-------------|-------------------|
| `create` | `create` |
| `write` | `write` |
| `unlink` | `unlink` |
| archivo (`active=False`) | `archive` |
| desarchivo (`active=True`) | `unarchive` |

Haced el POST **después** de confirmar el commit (post-commit / cola), para no avisar de un registro que luego hace rollback.

---

## Qué NO hay que hacer

- No enviar el diccionario completo del registro (`name`, `vat`, líneas, etc.).
- No llamar a XML-RPC desde Odoo hacia SignaPlan para “empujar” datos: el pull lo hace SignaPlan.
- No usar la URL sin el host del espacio (`planner.soltechgrupo.es`).
- No reintentar en bucle si la respuesta es 401/403/422.
- No bloquear la UI de Odoo esperando al sync de SignaPlan: el hook es fire-and-forget + cola.

---

## Checklist para la reunión / puesta en marcha

1. [ ] Admin SignaPlan abre el panel Odoo y copia **URL** + **clave**.
2. [ ] En Odoo: parámetro de sistema / config con URL y clave.
3. [ ] Hooks en `res.partner`, `hr.employee`, `bim.project`, `hr.leave`, `fleet.vehicle` (+ odómetro si aplica).
4. [ ] `hr.attendance` solo si queréis aviso inmediato de fichajes (opcional).
5. [ ] Prueba con `curl` o creando un contacto de prueba → HTTP **202**.
6. [ ] En SignaPlan, el log de sync aparece con modo **“Hook Odoo”** tras unos segundos.
7. [ ] Reintentos solo ante 5xx / timeout; debounce en Odoo si hay writes masivos.

---

## Contacto técnico SignaPlan (contexto)

- Receptor: `POST /api/v6/odoo/hooks/changed`
- Auth: `X-Odoo-Sync-Key` (o Bearer)
- Host de Soltec: `https://planner.soltechgrupo.es`
- Debounce en SignaPlan: ~8 s por módulo
- Datos: los mismos que el sync XML-RPC actual (no cambia el contrato de campos)

Si algo falla con 401/403, primero revisad clave y que el módulo Odoo esté activo en ese espacio SignaPlan.
