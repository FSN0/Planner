"""
Notas por voz: subida, transcripción (Whisper, español), resumen y vínculo obras/personas.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Optional

from flask import current_app
from werkzeug.utils import secure_filename

from app import db
from app.models import Nota, NotaAudioJob, Obra, User

# Formatos habituales en móvil y escritorio (ffmpeg normaliza el resto).
ALLOWED_AUDIO_EXTENSIONS = {
    '3gp', 'aac', 'aif', 'aiff', 'amr', 'caf', 'flac', 'm4a', 'mkv', 'mov',
    'mp3', 'mp4', 'oga', 'ogg', 'opus', 'wav', 'webm', 'wma',
}

WHISPER_MAX_BYTES = 24 * 1024 * 1024
SEGMENT_SECONDS = 600
MATCH_THRESHOLD = 0.72
OBRA_LINK_THRESHOLD = 0.88
GENERIC_OBRA_NAMES = {
    'varios', 'oficina', 'oficinas', 'obra', 'obras', 'general',
    'almacen', 'sede', 'central', 'na', 'n/a', 'sin obra',
}
# Tokens de lugar muy comunes: solos no identifican una obra concreta.
WEAK_LOCATION_TOKENS = {
    'catarroja', 'valencia', 'madrid', 'barcelona', 'teruel', 'alicante',
    'castellon', 'sevilla', 'zaragoza', 'murcia', 'bilbao',
}

# Preferencia de usuario (sidebar_prefs) para el prompt de resumen.
USER_PREF_SUMMARY_PROMPT = 'nota_audio_summary_prompt'
USER_PREF_INCLUDE_TRANSCRIPT = 'nota_audio_include_transcript'
AUDIO_JOB_STALE_HOURS = 12

DEFAULT_SUMMARY_PROMPT = (
    'Eres un asistente de bitácora de obra. Redactas un ACTA / RESUMEN COMPLETO '
    'en español a partir de la transcripción.\n'
    'Reglas:\n'
    '- NO inventes hechos, cifras ni nombres que no aparezcan.\n'
    '- Marca con [inaudible] lo que no se entienda.\n'
    '- El resumen debe ser AMPLIO y útil para quien no estuvo: no te limites a 3-4 frases.\n'
    '- Extiende el detalle según la longitud de la transcripción '
    '(reunión corta: 8–15 viñetas; reunión larga: más secciones y más puntos).\n'
    '- Estructura el campo "resumen" con estos apartados (omite solo si no hay contenido):\n'
    '  ## Contexto\n'
    '  ## Temas tratados\n'
    '  ## Acuerdos\n'
    '  ## Acciones / pendientes (quién / qué / cuándo si se menciona)\n'
    '  ## Incidencias o riesgos\n'
    '  ## Otras menciones relevantes\n'
    '- Usa viñetas claras dentro de cada apartado.'
)

SUMMARY_JSON_FOOTER = (
    '\n\nIMPORTANTE (formato de respuesta):\n'
    '- Cumple PRIORITARIAMENTE las instrucciones del usuario de arriba.\n'
    '- Si piden un informe amplio o con apartados, NO lo reduzcas a unas pocas líneas.\n'
    '- Responde SOLO con JSON válido: {"titulo": "...", "resumen": "..."}\n'
    '- "titulo": descriptivo, máx. 120 caracteres.\n'
    '- "resumen": el informe completo pedido (markdown permitido).\n'
    '- No inventes hechos que no estén en la transcripción.'
)


class NotaAudioCancelled(Exception):
    """El usuario canceló el job mientras se procesaba."""


def get_default_summary_prompt() -> str:
    return DEFAULT_SUMMARY_PROMPT


def get_user_summary_prompt(user: Optional[User]) -> str:
    """Prompt efectivo: último guardado del usuario o el del sistema."""
    if user is not None:
        prefs = getattr(user, 'sidebar_prefs', None) or {}
        if isinstance(prefs, dict):
            custom = (prefs.get(USER_PREF_SUMMARY_PROMPT) or '').strip()
            if custom:
                return custom
    return DEFAULT_SUMMARY_PROMPT


def get_user_include_transcript(user: Optional[User]) -> bool:
    if user is None:
        return True
    prefs = getattr(user, 'sidebar_prefs', None) or {}
    if not isinstance(prefs, dict):
        return True
    if USER_PREF_INCLUDE_TRANSCRIPT not in prefs:
        return True
    return bool(prefs.get(USER_PREF_INCLUDE_TRANSCRIPT))


def set_user_summary_prompt(user: User, prompt: Optional[str]) -> str:
    """Guarda o restablece el prompt del usuario. Devuelve el prompt efectivo."""
    from sqlalchemy.orm.attributes import flag_modified

    prefs = dict(getattr(user, 'sidebar_prefs', None) or {})
    text = (prompt or '').strip()
    if not text or text == DEFAULT_SUMMARY_PROMPT.strip():
        prefs.pop(USER_PREF_SUMMARY_PROMPT, None)
        user.sidebar_prefs = prefs
        flag_modified(user, 'sidebar_prefs')
        db.session.commit()
        return DEFAULT_SUMMARY_PROMPT
    if len(text) > 12000:
        raise ValueError('El prompt es demasiado largo (máx. 12.000 caracteres).')
    prefs[USER_PREF_SUMMARY_PROMPT] = text
    user.sidebar_prefs = prefs
    flag_modified(user, 'sidebar_prefs')
    db.session.commit()
    return text


def set_user_include_transcript(user: User, include: bool) -> bool:
    from sqlalchemy.orm.attributes import flag_modified

    prefs = dict(getattr(user, 'sidebar_prefs', None) or {})
    prefs[USER_PREF_INCLUDE_TRANSCRIPT] = bool(include)
    user.sidebar_prefs = prefs
    flag_modified(user, 'sidebar_prefs')
    db.session.commit()
    return bool(include)


def _compose_summary_system_prompt(custom: Optional[str] = None) -> str:
    """El prompt del usuario manda; solo añadimos marco + formato JSON obligatorio."""
    user_instr = (custom or DEFAULT_SUMMARY_PROMPT).strip() or DEFAULT_SUMMARY_PROMPT
    lower = user_instr.lower()
    has_json_shape = '"titulo"' in lower and '"resumen"' in lower
    header = (
        'Eres un asistente que redacta informes a partir de transcripciones de reuniones laborales.\n'
        'Debes cumplir PRIORITARIAMENTE las instrucciones del usuario.\n'
        'Si piden estructura, apartados o un informe amplio, NO lo comprimas en 3–5 líneas.\n'
        'No inventes hechos, cifras ni nombres ausentes en la transcripción.\n\n'
        '=== INSTRUCCIONES DEL USUARIO (obligatorias) ===\n'
        f'{user_instr}\n'
        '=== FIN INSTRUCCIONES DEL USUARIO ==='
    )
    if has_json_shape:
        return header
    return header + SUMMARY_JSON_FOOTER


@dataclass
class PersonMatch:
    query: str
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    ambiguous: bool = False
    candidates: list[dict] = field(default_factory=list)


@dataclass
class ObraMatch:
    query: str
    obra_id: Optional[int] = None
    obra_nombre: Optional[str] = None
    score: float = 0.0
    ambiguous: bool = False
    candidates: list[dict] = field(default_factory=list)


def _normalize_text(value: str) -> str:
    text = (value or '').strip().lower()
    for src, dst in (
        ('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u'),
        ('ü', 'u'), ('ñ', 'n'),
    ):
        text = text.replace(src, dst)
    text = re.sub(r'[_\-./\\()"“”\'`,;:]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _tokens(value: str) -> list[str]:
    return [t for t in _normalize_text(value).split() if t]


def _has_word(haystack: str, needle: str) -> bool:
    """Coincide palabra completa, no subcadena (evita elena ⊂ helena)."""
    n = _normalize_text(needle)
    h = _normalize_text(haystack)
    if not n or not h:
        return False
    return bool(re.search(rf'(?:^|\s){re.escape(n)}(?:\s|$)', h))


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Solo bonus de contención si la cadena corta es suficientemente larga
    # (evita que "catarroja" dispare todas las obras de Catarroja).
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 12 and shorter in longer:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def _is_generic_obra_query(query: str) -> bool:
    norm = _normalize_text(query)
    if not norm or norm in GENERIC_OBRA_NAMES:
        return True
    toks = _tokens(query)
    if len(toks) == 1 and toks[0] in WEAK_LOCATION_TOKENS:
        return True
    if len(toks) <= 1 and len(norm) < 6:
        return True
    return False


def _score_obra_against_query(query: str, obra: Obra) -> float:
    """Puntuación estricta query→obra. Lugar genérico no basta."""
    q = _normalize_text(query)
    name = _normalize_text(obra.nombre or '')
    codigo = _normalize_text(getattr(obra, 'codigo', '') or '')
    if not q or not name:
        return 0.0
    if _is_generic_obra_query(q):
        return 0.0

    if q == name:
        return 1.0
    if codigo and (q == codigo or q == f'obra {codigo}'):
        return 0.98

    q_toks = _tokens(q)
    n_toks = _tokens(name)
    if not q_toks or not n_toks:
        return 0.0

    if len(q_toks) == 1 and q_toks[0] in WEAK_LOCATION_TOKENS:
        return 0.0

    overlap = [t for t in q_toks if t in n_toks]
    coverage = len(overlap) / len(q_toks)
    if coverage < 0.8:
        sim = _similarity(q, name)
        return sim if sim >= 0.9 and len(q) >= 12 else 0.0

    strong = [t for t in overlap if t not in WEAK_LOCATION_TOKENS and len(t) > 2]
    if not strong and len(q_toks) <= 2:
        return 0.0

    base = 0.75 + 0.2 * coverage
    sim = _similarity(q, name)
    return max(base, sim)


def get_audio_uploads_dir() -> str:
    base = os.path.join(current_app.root_path, '..', 'uploads', 'notas_audio')
    base = os.path.abspath(base)
    os.makedirs(base, exist_ok=True)
    return base


def get_max_audio_bytes() -> int:
    return int(current_app.config.get('NOTA_AUDIO_MAX_BYTES', 512 * 1024 * 1024))


def get_max_audio_seconds() -> int:
    return int(current_app.config.get('NOTA_AUDIO_MAX_SECONDS', 3 * 3600))


def allowed_audio_file(filename: str) -> bool:
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[-1].lower()
    return ext in ALLOWED_AUDIO_EXTENSIONS


def _run_cmd(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def probe_duration_seconds(path: str, *, timeout: int = 60) -> float:
    proc = _run_cmd([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', path,
    ], timeout=timeout)
    if proc.returncode != 0:
        raise ValueError('No se pudo leer la duración del audio.')
    try:
        return float(proc.stdout.strip())
    except (TypeError, ValueError):
        raise ValueError('Duración de audio inválida.')


def save_audio_upload(
    file_storage,
    autor_id: int,
    *,
    summary_prompt: Optional[str] = None,
    include_transcript: Optional[bool] = None,
) -> NotaAudioJob:
    """Guarda el archivo y encola el job. La duración se valida en Celery."""
    original = secure_filename(file_storage.filename or 'audio.webm')
    if not allowed_audio_file(original):
        exts = ', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))
        raise ValueError(f'Formato no soportado. Use: {exts}')

    token = uuid.uuid4().hex
    ext = original.rsplit('.', 1)[-1].lower()
    dest = os.path.join(get_audio_uploads_dir(), f'{token}.{ext}')
    file_storage.save(dest)

    size = os.path.getsize(dest)
    if size > get_max_audio_bytes():
        os.remove(dest)
        raise ValueError('El archivo supera el tamaño máximo permitido (512 MB).')

    prompt_text = (summary_prompt or '').strip()
    if prompt_text and len(prompt_text) > 12000:
        os.remove(dest)
        raise ValueError('El prompt es demasiado largo (máx. 12.000 caracteres).')

    # No ffprobe aquí: la subida HTTP debe terminar al escribir a disco.
    # Duración + rechazo por max se hacen en process_nota_audio_job.
    meta: dict[str, Any] = {
        'fase': 'pendiente',
        'progreso': 5,
        'mensaje': 'Audio recibido. En cola de procesamiento…',
        'include_transcript': True if include_transcript is None else bool(include_transcript),
    }
    if prompt_text:
        meta['summary_prompt'] = prompt_text
        meta['summary_prompt_chars'] = len(prompt_text)
        meta['summary_prompt_preview'] = prompt_text[:180]

    job = NotaAudioJob(
        autor_id=autor_id,
        estado=NotaAudioJob.ESTADO_PENDIENTE,
        archivo_path=dest,
        archivo_nombre=original,
        duracion_segundos=None,
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.session.add(job)
    db.session.commit()
    return job


def attach_celery_task_id(job_id: int, task_id: str) -> None:
    job = NotaAudioJob.query.get(job_id)
    if not job:
        return
    meta: dict[str, Any] = {}
    if job.meta_json:
        try:
            parsed = json.loads(job.meta_json)
            if isinstance(parsed, dict):
                meta = parsed
        except json.JSONDecodeError:
            pass
    meta['celery_task_id'] = task_id
    job.meta_json = json.dumps(meta, ensure_ascii=False)
    job.updated_at = datetime.utcnow()
    db.session.commit()


def _job_meta(job: NotaAudioJob) -> dict[str, Any]:
    if not job.meta_json:
        return {}
    try:
        data = json.loads(job.meta_json)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _ensure_not_cancelled(job_id: int) -> None:
    job = NotaAudioJob.query.get(job_id)
    if job and job.estado == NotaAudioJob.ESTADO_CANCELADO:
        raise NotaAudioCancelled('Procesamiento cancelado por el usuario.')


def cancel_audio_job(job: NotaAudioJob) -> NotaAudioJob:
    """Marca el job como cancelado, revoca Celery si hay task_id y limpia el archivo."""
    if job.estado in (
        NotaAudioJob.ESTADO_COMPLETADO,
        NotaAudioJob.ESTADO_ERROR,
        NotaAudioJob.ESTADO_CANCELADO,
    ):
        return job

    meta = _job_meta(job)
    task_id = meta.get('celery_task_id')
    if task_id:
        try:
            from app.celery_worker import celery
            celery.control.revoke(task_id, terminate=True, signal='SIGTERM')
        except Exception as exc:
            current_app.logger.warning(
                'No se pudo revocar Celery task %s del job %s: %s',
                task_id, job.id, exc,
            )

    audio_path = job.archivo_path
    job.estado = NotaAudioJob.ESTADO_CANCELADO
    job.error_message = 'Cancelado por el usuario.'
    job.updated_at = datetime.utcnow()
    job.completed_at = datetime.utcnow()
    meta.update({
        'fase': 'cancelado',
        'progreso': 0,
        'mensaje': 'Procesamiento cancelado.',
    })
    job.meta_json = json.dumps(meta, ensure_ascii=False)
    if audio_path and os.path.isfile(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass
        job.archivo_path = None
    db.session.commit()
    return job


def sweep_stale_audio_jobs(autor_id: Optional[int] = None) -> int:
    """Marca como error jobs pendientes/procesando sin actividad reciente."""
    cutoff = datetime.utcnow() - timedelta(hours=AUDIO_JOB_STALE_HOURS)
    q = NotaAudioJob.query.filter(
        NotaAudioJob.estado.in_([
            NotaAudioJob.ESTADO_PENDIENTE,
            NotaAudioJob.ESTADO_PROCESANDO,
        ]),
        NotaAudioJob.updated_at < cutoff,
    )
    if autor_id is not None:
        q = q.filter(NotaAudioJob.autor_id == autor_id)
    stale = q.limit(50).all()
    count = 0
    for job in stale:
        meta = _job_meta(job)
        msg = (
            f'Proceso abandonado (sin progreso en más de {AUDIO_JOB_STALE_HOURS} h). '
            'Puedes volver a subir el audio.'
        )
        job.estado = NotaAudioJob.ESTADO_ERROR
        job.error_message = msg
        job.updated_at = datetime.utcnow()
        meta.update({'fase': 'error', 'mensaje': msg[:500], 'stale': True})
        job.meta_json = json.dumps(meta, ensure_ascii=False)
        if job.archivo_path and os.path.isfile(job.archivo_path):
            try:
                os.remove(job.archivo_path)
            except OSError:
                pass
            job.archivo_path = None
        count += 1
    if count:
        db.session.commit()
    return count


def _normalize_for_whisper(input_path: str, output_path: str) -> None:
    proc = _run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'libmp3lame', '-b:a', '64k',
        output_path,
    ], timeout=max(600, int(get_max_audio_seconds())))
    if proc.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError('No se pudo convertir el audio para transcripción.')


def _list_chunk_files(out_dir: str) -> list[str]:
    chunks = sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.startswith('chunk_') and name.endswith('.mp3')
    )
    if not chunks:
        raise RuntimeError('No se generaron trozos de audio.')
    return chunks


def _split_audio(input_path: str, out_dir: str) -> list[str]:
    """Trocea audio ya normalizado (copy primero; re-encode si falla)."""
    pattern = os.path.join(out_dir, 'chunk_%03d.mp3')
    proc = _run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-f', 'segment', '-segment_time', str(SEGMENT_SECONDS),
        '-c', 'copy', pattern,
    ], timeout=max(600, int(get_max_audio_seconds())))
    if proc.returncode != 0:
        proc = _run_cmd([
            'ffmpeg', '-y', '-i', input_path,
            '-f', 'segment', '-segment_time', str(SEGMENT_SECONDS),
            '-ac', '1', '-ar', '16000', '-c:a', 'libmp3lame', '-b:a', '64k',
            pattern,
        ], timeout=max(600, int(get_max_audio_seconds())))
    if proc.returncode != 0:
        raise RuntimeError('No se pudo trocear el audio para transcripción.')
    return _list_chunk_files(out_dir)


def _split_normalize_from_original(input_path: str, out_dir: str) -> list[str]:
    """
    Trocea el original en ~10 min y normaliza cada trozo (mono 16k 64k mp3).
    Evita normalizar el archivo entero (caro en ~1h y puede matar el worker).
    """
    pattern = os.path.join(out_dir, 'chunk_%03d.mp3')
    proc = _run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-vn', '-f', 'segment', '-segment_time', str(SEGMENT_SECONDS),
        '-reset_timestamps', '1',
        '-ac', '1', '-ar', '16000', '-c:a', 'libmp3lame', '-b:a', '64k',
        pattern,
    ], timeout=max(900, int(get_max_audio_seconds())))
    if proc.returncode != 0:
        raise RuntimeError('No se pudo trocear/normalizar el audio para transcripción.')
    return _list_chunk_files(out_dir)


def _should_chunk_long_audio(input_path: str, duration: Optional[float]) -> bool:
    """True si conviene trocear desde el original en vez de normalizar entero."""
    if duration is not None and duration > SEGMENT_SECONDS:
        return True
    # Sin duración: ficheros grandes (~> Whisper limit) suelen ser largos.
    try:
        return os.path.getsize(input_path) > WHISPER_MAX_BYTES
    except OSError:
        return False


def _update_job_progress(
    job_id: int,
    *,
    fase: str,
    progreso: int,
    mensaje: str,
    extra: Optional[dict] = None,
) -> None:
    """Persiste progreso intermedio para que el frontend pueda hacer polling."""
    job = NotaAudioJob.query.get(job_id)
    if not job:
        return
    if job.estado == NotaAudioJob.ESTADO_CANCELADO:
        raise NotaAudioCancelled('Procesamiento cancelado por el usuario.')
    payload = {
        'fase': fase,
        'progreso': max(0, min(100, int(progreso))),
        'mensaje': mensaje,
    }
    if extra:
        payload.update(extra)
    if job.meta_json:
        try:
            previous = json.loads(job.meta_json)
            if isinstance(previous, dict):
                # Conserva datos finales / config entre updates de progreso
                for key in (
                    'obras', 'personas', 'summary_prompt', 'summary_prompt_chars',
                    'summary_prompt_preview', 'celery_task_id', 'include_transcript',
                ):
                    if key in previous and key not in payload:
                        payload[key] = previous[key]
        except json.JSONDecodeError:
            pass
    job.meta_json = json.dumps(payload, ensure_ascii=False)
    job.updated_at = datetime.utcnow()
    db.session.commit()


def _openai_client(timeout: float = 90.0):
    from openai import OpenAI

    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY no configurada.')
    # timeout duro: si GPT/Whisper se queda colgado, no bloqueamos el job eternamente
    return OpenAI(api_key=api_key, timeout=timeout, max_retries=1)


def _whisper_chunks(paths: list[str], on_chunk=None) -> str:
    client = _openai_client(timeout=180.0)
    parts: list[str] = []
    total = len(paths)

    for idx, chunk_path in enumerate(paths):
        size = os.path.getsize(chunk_path)
        if size > WHISPER_MAX_BYTES:
            raise RuntimeError(
                f'Un trozo de audio ({size // (1024 * 1024)} MB) supera el límite de Whisper.'
            )
        if on_chunk:
            on_chunk(idx, total)
        with open(chunk_path, 'rb') as fh:
            result = client.audio.transcriptions.create(
                model='whisper-1',
                file=fh,
                language='es',
                response_format='text',
            )
        text = (result if isinstance(result, str) else getattr(result, 'text', '') or '').strip()
        if text:
            parts.append(text)
        current_app.logger.info('Whisper trozo %s/%s: %s chars', idx + 1, total, len(text))

    return '\n\n'.join(parts).strip()


def transcribe_audio_file(
    input_path: str,
    on_progress=None,
    *,
    duration: Optional[float] = None,
) -> str:
    work_dir = tempfile.mkdtemp(prefix='nota_audio_')
    try:
        def _on_chunk(idx, total):
            if not on_progress:
                return
            # Transcripción ocupa ~15% → 75%
            pct = 15 + int((idx / max(total, 1)) * 60)
            on_progress(
                'transcribiendo',
                pct,
                f'Transcribiendo trozo {idx + 1} de {total}…',
                {'trozo_actual': idx + 1, 'trozos_total': total},
            )

        # Audio largo: trocear+normalizar por chunk desde el original (no ffmpeg del archivo entero).
        if _should_chunk_long_audio(input_path, duration):
            if on_progress:
                on_progress('preparando', 12, 'Troceando audio largo…')
            chunk_dir = os.path.join(work_dir, 'chunks')
            os.makedirs(chunk_dir, exist_ok=True)
            chunks = _split_normalize_from_original(input_path, chunk_dir)
            if on_progress:
                on_progress('transcribiendo', 15, f'Transcribiendo {len(chunks)} trozos…', {
                    'trozo_actual': 0, 'trozos_total': len(chunks),
                })
            return _whisper_chunks(chunks, on_chunk=_on_chunk)

        # Corto: normalizar entero y Whisper (o trocear si el mp3 resultante > 24MB).
        if on_progress:
            on_progress('preparando', 12, 'Normalizando audio…')
        normalized = os.path.join(work_dir, 'normalized.mp3')
        _normalize_for_whisper(input_path, normalized)

        if os.path.getsize(normalized) <= WHISPER_MAX_BYTES:
            if on_progress:
                on_progress('transcribiendo', 20, 'Transcribiendo audio…', {
                    'trozo_actual': 1, 'trozos_total': 1,
                })
            return _whisper_chunks([normalized], on_chunk=_on_chunk)

        if on_progress:
            on_progress('preparando', 14, 'Troceando audio largo…')
        chunk_dir = os.path.join(work_dir, 'chunks')
        os.makedirs(chunk_dir, exist_ok=True)
        chunks = _split_audio(normalized, chunk_dir)
        return _whisper_chunks(chunks, on_chunk=_on_chunk)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def match_obras_from_queries(queries: list[str], obras: list[Obra]) -> list[ObraMatch]:
    """
    Vincula menciones de obra a fichas del catálogo de forma conservadora.
    - 1 candidata clara → vincular
    - varias cercanas → sugerencia para que el admin valide
    - lugar genérico (Catarroja, Oficina…) → ignorar
    """
    results: list[ObraMatch] = []
    seen_ids: set[int] = set()

    for raw in queries:
        query = (raw or '').strip()
        if not query or _is_generic_obra_query(query):
            continue

        scored: list[tuple[float, Obra]] = []
        for obra in obras:
            score = _score_obra_against_query(query, obra)
            if score >= 0.75:
                scored.append((score, obra))

        if not scored:
            results.append(ObraMatch(query=query, score=0.0))
            continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score, top_obra = scored[0]
        close = [(s, o) for s, o in scored if s >= top_score - 0.05]

        if len(close) == 1 and top_score >= OBRA_LINK_THRESHOLD:
            if top_obra.id in seen_ids:
                continue
            seen_ids.add(top_obra.id)
            results.append(ObraMatch(
                query=query,
                obra_id=top_obra.id,
                obra_nombre=top_obra.nombre,
                score=top_score,
            ))
            continue

        # Varias candidatas o score medio: dejar sugerencia para validar
        results.append(ObraMatch(
            query=query,
            score=top_score,
            ambiguous=True,
            candidates=[
                {'id': o.id, 'nombre': o.nombre, 'score': round(s, 2)}
                for s, o in close[:5]
            ],
        ))

    return _dedupe_obra_matches(results)


def match_obras_from_text(text: str, obras: list[Obra]) -> list[ObraMatch]:
    """
    Solo enlaza si el NOMBRE COMPLETO o el CÓDIGO aparecen literalmente.
    No usa lugares sueltos (Catarroja, Valencia…).
    """
    norm_text = _normalize_text(text)
    results: list[ObraMatch] = []
    seen_ids: set[int] = set()

    for obra in obras:
        name = (obra.nombre or '').strip()
        if not name or _is_generic_obra_query(name):
            continue
        norm_name = _normalize_text(name)
        name_toks = _tokens(name)
        distinctive = [t for t in name_toks if t not in WEAK_LOCATION_TOKENS]
        if len(distinctive) < 2 and len(norm_name) < 16:
            continue

        score = 0.0
        if len(norm_name) >= 10 and norm_name in norm_text:
            score = 0.96
        codigo = _normalize_text(getattr(obra, 'codigo', '') or '')
        if codigo and len(codigo) >= 4 and _has_word(norm_text, codigo):
            score = max(score, 0.95)
        if score >= OBRA_LINK_THRESHOLD and obra.id not in seen_ids:
            seen_ids.add(obra.id)
            results.append(ObraMatch(query=name, obra_id=obra.id, obra_nombre=name, score=score))

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:10]


def _is_internal_user(user) -> bool:
    company = getattr(user, 'company_rel', None)
    if company is not None:
        return bool(getattr(company, 'is_internal', False))
    return False


def _user_display_name(user) -> str:
    return f'{user.name or ""} {user.lastname or ""}'.strip()


def _user_name_tokens(user) -> list[str]:
    return _tokens(_user_display_name(user))


def _likely_given_names(user) -> set[str]:
    """
    Posibles nombres de pila de la ficha.
    Cubre:
    - name=Jairo lastname=Cano → {jairo}
    - name=CARO ORTEGA lastname=JAIRO (import Odoo) → {caro, jairo}
    - name=Juan Vicente lastname=Ruiz → {juan, ruiz}
      (no mete «vicente» como pila principal; evita falsos únicos)
    """
    name_toks = _tokens(user.name or '')
    last_toks = _tokens(user.lastname or '')
    out: set[str] = set()
    if len(name_toks) == 1:
        out.add(name_toks[0])
    elif name_toks:
        out.add(name_toks[0])
    if len(last_toks) == 1 and len(name_toks) >= 2:
        # Posible nombre de pila en lastname (ficha invertida)
        out.add(last_toks[0])
    elif not name_toks and last_toks:
        out.add(last_toks[0])
    return out


def _primary_given_name(user) -> str:
    """Nombre de pila más probable (para mostrar / desempates)."""
    name_toks = _tokens(user.name or '')
    last_toks = _tokens(user.lastname or '')
    if len(name_toks) == 1:
        return name_toks[0]
    # Ficha invertida típica: apellidos en name + nombre en lastname
    if len(last_toks) == 1 and len(name_toks) >= 2:
        return last_toks[0]
    if name_toks:
        return name_toks[0]
    if last_toks:
        return last_toks[0]
    return ''


def _candidate_dict(user, score: float) -> dict:
    return {
        'id': user.id,
        'name': _user_display_name(user),
        'score': round(score, 2),
        'interno': _is_internal_user(user),
    }


def match_persons_from_names(names: list[str], users: list[User]) -> list[PersonMatch]:
    """
    Matching práctico para bitácora:
    - nombre+apellido claros → vincular
    - nombre de pila único (sobre todo entre internos) → vincular
    - varios posibles → sugerencia para que el admin valide y añada
    """
    matches: list[PersonMatch] = []
    seen_queries: set[str] = set()

    for raw in names:
        query = (raw or '').strip()
        if not query or len(query) < 2:
            continue
        q_toks = _tokens(query)
        if not q_toks:
            continue
        norm_query = _normalize_text(query)
        if norm_query in seen_queries:
            continue
        # Preferir la mención más específica (Jairo Cano > Jairo)
        if any(norm_query != sq and (norm_query in sq or sq in norm_query) for sq in seen_queries):
            shorter = [sq for sq in seen_queries if sq in norm_query and sq != norm_query]
            if shorter and len(norm_query) > max(len(s) for s in shorter):
                matches = [m for m in matches if _normalize_text(m.query) not in shorter]
                seen_queries -= set(shorter)
            else:
                continue
        seen_queries.add(norm_query)

        scored: list[tuple[float, object]] = []
        for user in users:
            full = _user_display_name(user)
            norm_full = _normalize_text(full)
            given = _likely_given_names(user)
            toks = _user_name_tokens(user)
            score = 0.0

            if norm_query == norm_full:
                score = 1.0
            elif len(q_toks) >= 2:
                if _similarity(norm_query, norm_full) >= 0.9:
                    score = 0.94
                elif all(t in toks for t in q_toks if len(t) > 1):
                    score = 0.93
            elif len(q_toks) == 1:
                token = q_toks[0]
                if token in given:
                    score = 0.95
                elif token in toks and len(token) >= 3:
                    # Aparece en el nombre completo pero no es nombre de pila principal
                    score = 0.8

            if score >= 0.8:
                if _is_internal_user(user):
                    score = min(1.0, score + 0.02)
                scored.append((score, user))

        if not scored:
            matches.append(PersonMatch(query=query))
            continue

        scored.sort(key=lambda x: x[0], reverse=True)

        # --- Nombre compuesto ---
        if len(q_toks) >= 2:
            top_score, top_user = scored[0]
            close = [(s, u) for s, u in scored if s >= top_score - 0.03]
            if len(close) == 1 and top_score >= 0.9:
                matches.append(PersonMatch(
                    query=query,
                    user_id=top_user.id,
                    user_name=_user_display_name(top_user),
                    ambiguous=False,
                ))
            else:
                matches.append(PersonMatch(
                    query=query,
                    ambiguous=True,
                    candidates=[_candidate_dict(u, s) for s, u in close[:5]],
                ))
            continue

        # --- Solo nombre de pila ---
        token = q_toks[0]
        primary_hits = [(s, u) for s, u in scored if token in _likely_given_names(u)]
        internal_primary = [(s, u) for s, u in primary_hits if _is_internal_user(u)]

        # 1) Un solo interno con ese nombre de pila → vincular
        if len(internal_primary) == 1:
            u = internal_primary[0][1]
            matches.append(PersonMatch(
                query=query,
                user_id=u.id,
                user_name=_user_display_name(u),
                ambiguous=False,
            ))
            continue

        # 2) Un solo hit por nombre de pila en toda la plantilla → vincular
        if len(primary_hits) == 1 and primary_hits[0][0] >= 0.9:
            u = primary_hits[0][1]
            matches.append(PersonMatch(
                query=query,
                user_id=u.id,
                user_name=_user_display_name(u),
                ambiguous=False,
            ))
            continue

        # 3) Varios: sugerir (prioriza internos) para que el admin valide
        pool = internal_primary or primary_hits or scored[:5]
        matches.append(PersonMatch(
            query=query,
            ambiguous=True,
            candidates=[_candidate_dict(u, s) for s, u in pool[:5]],
        ))

    return matches


def _extract_entities_gpt(transcript: str) -> dict[str, list[str]]:
    try:
        client = _openai_client()
    except RuntimeError:
        return {'obras': [], 'personas': []}

    sample = transcript
    if len(sample) > 120000:
        sample = transcript[:60000] + '\n...\n' + transcript[-60000:]

    prompt = (
        'Analiza esta transcripción en español de una reunión laboral / de obra.\n'
        'Devuelve SOLO JSON válido con:\n'
        '{\n'
        '  "obras": [],\n'
        '  "personas": []\n'
        '}\n\n'
        'Reglas OBRAS:\n'
        '- Incluye SOLO nombres de proyectos/obras concretas (p.ej. "Centro Salud Catarroja Fase 2").\n'
        '- NO pongas ciudades, pueblos ni lugares sueltos (Catarroja, Valencia…).\n'
        '- NO pongas genéricos (Oficina, Varios, Obra).\n'
        '- Si solo se habla del sitio en general sin identificar la obra, deja obras vacío.\n\n'
        'Reglas PERSONAS:\n'
        '- Personas reales de las que se habla de forma relevante (participantes o citados).\n'
        '- Prefiere "Nombre Apellido" cuando salga en el audio.\n'
        '- NO inventes apellidos.\n'
        '- NO incluyas apelativos ficticios o dichos (p.ej. "Pepe Botijo").\n'
        '- Cada persona UNA vez (sin duplicar Jairo / Jairo Cano).\n'
        '- No inventes nombres.\n\n'
        f'Transcripción:\n{sample}'
    )
    try:
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': 'Respondes únicamente JSON. Idioma español.'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
        raw = (resp.choices[0].message.content or '').strip()
        raw = re.sub(r'^```json\s*|\s*```$', '', raw, flags=re.I).strip()
        data = json.loads(raw)
        return {
            'obras': [str(x).strip() for x in data.get('obras', []) if str(x).strip()][:20],
            'personas': [str(x).strip() for x in data.get('personas', []) if str(x).strip()][:25],
        }
    except Exception as exc:
        current_app.logger.warning('Extracción GPT entidades falló: %s', exc)
        return {'obras': [], 'personas': []}


def _summarize_gpt(
    transcript: str,
    summary_prompt: Optional[str] = None,
) -> tuple[str, str]:
    fallback_titulo = f'Nota de voz {date.today().strftime("%d/%m/%Y")}'
    fallback_resumen = (
        'No se pudo generar el resumen automático. Se adjunta la transcripción completa.'
    )
    try:
        client = _openai_client(timeout=120.0)
    except RuntimeError:
        return fallback_titulo, 'Resumen no disponible (falta OPENAI_API_KEY).'

    sample = transcript
    truncated = False
    if len(sample) > 100000:
        sample = transcript[:50000] + '\n[...]\n' + transcript[-50000:]
        truncated = True

    instr = _compose_summary_system_prompt(summary_prompt)
    if truncated:
        instr += (
            '\nLa transcripción está truncada por longitud; indícalo al final del resumen.'
        )

    user_payload = (
        'Usa exclusivamente esta transcripción como fuente de hechos.\n'
        'Redacta el informe según las instrucciones del sistema.\n\n'
        '--- TRANSCRIPCIÓN ---\n'
        f'{sample}\n'
        '--- FIN TRANSCRIPCIÓN ---'
    )

    def _parse_response(raw_text: str) -> tuple[str, str]:
        cleaned = re.sub(r'^```json\s*|\s*```$', '', (raw_text or '').strip(), flags=re.I).strip()
        try:
            data = json.loads(cleaned)
            titulo = (data.get('titulo') or '').strip()[:200]
            resumen = (data.get('resumen') or '').strip()
        except json.JSONDecodeError:
            titulo = fallback_titulo
            resumen = cleaned[:20000] or fallback_resumen
        if not titulo:
            titulo = fallback_titulo
        if not resumen:
            resumen = fallback_resumen
        return titulo, resumen

    try:
        current_app.logger.info(
            'Resumen GPT: prompt_chars=%s preview=%r',
            len(summary_prompt or ''),
            (summary_prompt or '')[:120],
        )
        try:
            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[
                    {'role': 'system', 'content': instr},
                    {'role': 'user', 'content': user_payload},
                ],
                temperature=0.2,
                max_tokens=6000,
                response_format={'type': 'json_object'},
            )
        except Exception as fmt_exc:
            current_app.logger.info(
                'Resumen GPT sin response_format (%s); reintento clásico', fmt_exc,
            )
            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[
                    {'role': 'system', 'content': instr},
                    {'role': 'user', 'content': user_payload},
                ],
                temperature=0.2,
                max_tokens=6000,
            )
        raw = (resp.choices[0].message.content or '').strip()
        return _parse_response(raw)
    except Exception as exc:
        current_app.logger.warning('Resumen GPT falló: %s', exc)
        return fallback_titulo, fallback_resumen


def _dedupe_obra_matches(matches: list[ObraMatch]) -> list[ObraMatch]:
    """Una sola entrada por obra_id (o por nombre normalizado si no hay id)."""
    by_id: dict[int, ObraMatch] = {}
    by_name: dict[str, ObraMatch] = {}
    ordered: list[ObraMatch] = []
    for m in matches:
        if m.obra_id:
            prev = by_id.get(m.obra_id)
            if prev is None:
                by_id[m.obra_id] = m
                ordered.append(m)
            elif m.score > prev.score:
                idx = ordered.index(prev)
                ordered[idx] = m
                by_id[m.obra_id] = m
            continue
        key = _normalize_text(m.obra_nombre or m.query or '')
        if not key or key in by_name:
            continue
        by_name[key] = m
        ordered.append(m)
    return ordered


def _dedupe_person_matches(matches: list[PersonMatch]) -> list[PersonMatch]:
    seen_ids: set[int] = set()
    seen_queries: set[str] = set()
    out: list[PersonMatch] = []
    for pm in matches:
        if pm.user_id:
            if pm.user_id in seen_ids:
                continue
            seen_ids.add(pm.user_id)
            out.append(pm)
            continue
        key = _normalize_text(pm.query)
        if not key or key in seen_queries:
            continue
        seen_queries.add(key)
        out.append(pm)
    return out


def _build_nota_content(
    resumen: str,
    transcript: str,
    obra_matches: list[ObraMatch],
    person_matches: list[PersonMatch],
    *,
    include_transcript: bool = True,
) -> str:
    obra_matches = _dedupe_obra_matches(obra_matches)
    person_matches = _dedupe_person_matches(person_matches)
    lines = [resumen or '']
    if include_transcript:
        lines.extend([
            '', '---', '', 'Transcripción:', '',
            transcript or '[Sin transcripción]',
        ])
    lines.extend(['', '---', ''])

    linked_obras = [m for m in obra_matches if m.obra_id]
    suggest_obras = [m for m in obra_matches if not m.obra_id]
    if linked_obras:
        lines.append(
            'Obras vinculadas: '
            + ', '.join(dict.fromkeys(m.obra_nombre or m.query for m in linked_obras))
        )
    if suggest_obras:
        bits = []
        for m in suggest_obras:
            if m.candidates:
                opts = ' | '.join(
                    f"{c.get('nombre') or c.get('name')} (#{c['id']})"
                    for c in m.candidates[:3]
                )
                bits.append(f'{m.query} → ¿{opts}?')
            else:
                bits.append(f'{m.query} (sin ficha clara)')
        lines.append(
            'Obras pendientes de validar (ábrela y añádelas en «Obras implicadas»): '
            + '; '.join(bits)
        )
    if not linked_obras and not suggest_obras:
        lines.append('Obras detectadas: —')

    linked_people = [pm for pm in person_matches if pm.user_id and not pm.ambiguous]
    suggest_people = [pm for pm in person_matches if not (pm.user_id and not pm.ambiguous)]
    if linked_people:
        lines.append(
            'Personas vinculadas: '
            + ', '.join(dict.fromkeys(pm.user_name or pm.query for pm in linked_people))
        )
    if suggest_people:
        bits = []
        for pm in suggest_people:
            if pm.candidates:
                opts = ' | '.join(
                    f"{c['name']} (#{c['id']})" for c in pm.candidates[:3]
                )
                bits.append(f'{pm.query} → ¿{opts}?')
            else:
                bits.append(f'{pm.query} (sin ficha)')
        lines.append(
            'Personas pendientes de validar (ábrela y añádelas en «Usuarios implicados»): '
            + '; '.join(bits)
        )
    if not linked_people and not suggest_people:
        lines.append('Personas: —')

    return '\n'.join(lines)


def process_nota_audio_job(job_id: int) -> None:
    job = NotaAudioJob.query.get(job_id)
    if not job:
        current_app.logger.error('NotaAudioJob %s no encontrado', job_id)
        return
    if job.estado == NotaAudioJob.ESTADO_CANCELADO:
        return
    if job.estado not in (NotaAudioJob.ESTADO_PENDIENTE, NotaAudioJob.ESTADO_PROCESANDO):
        return

    # Snapshot antes de commits intermedios (evita DetachedInstanceError)
    autor_id = job.autor_id
    audio_path = job.archivo_path
    job_meta = _job_meta(job)
    summary_prompt = (job_meta.get('summary_prompt') or '').strip() or None
    include_transcript = job_meta.get('include_transcript')
    if include_transcript is None:
        include_transcript = True
    else:
        include_transcript = bool(include_transcript)
    if not summary_prompt:
        autor = User.query.get(autor_id)
        summary_prompt = get_user_summary_prompt(autor)
        if 'include_transcript' not in job_meta:
            include_transcript = get_user_include_transcript(autor)

    current_app.logger.info(
        'NotaAudioJob %s: prompt_chars=%s include_transcript=%s preview=%r',
        job_id,
        len(summary_prompt or ''),
        include_transcript,
        (summary_prompt or '')[:120],
    )

    job.estado = NotaAudioJob.ESTADO_PROCESANDO
    job.updated_at = datetime.utcnow()
    db.session.commit()
    _update_job_progress(
        job_id,
        fase='encola',
        progreso=8,
        mensaje='Audio recibido. Preparando procesamiento…',
        extra={
            'summary_prompt': summary_prompt,
            'summary_prompt_chars': len(summary_prompt or ''),
            'summary_prompt_preview': (summary_prompt or '')[:180],
            'include_transcript': include_transcript,
        },
    )

    def _fail_job(message: str) -> None:
        db.session.rollback()
        failed = NotaAudioJob.query.get(job_id)
        if not failed or failed.estado == NotaAudioJob.ESTADO_CANCELADO:
            return
        failed.estado = NotaAudioJob.ESTADO_ERROR
        failed.error_message = message[:2000]
        failed.meta_json = json.dumps({
            'fase': 'error',
            'progreso': 8,
            'mensaje': message[:500],
        }, ensure_ascii=False)
        failed.updated_at = datetime.utcnow()
        db.session.commit()

    try:
        _ensure_not_cancelled(job_id)
        if not audio_path or not os.path.isfile(audio_path):
            raise FileNotFoundError('Archivo de audio no encontrado.')

        # Duración aquí (no en la subida HTTP) para devolver el upload cuanto antes.
        try:
            duration = probe_duration_seconds(audio_path, timeout=60)
        except ValueError as probe_exc:
            _fail_job(str(probe_exc) or 'No se pudo leer la duración del audio.')
            return

        if duration > get_max_audio_seconds():
            _fail_job('El audio supera el máximo de 3 horas.')
            return

        job = NotaAudioJob.query.get(job_id)
        if job:
            if job.estado == NotaAudioJob.ESTADO_CANCELADO:
                return
            job.duracion_segundos = duration
            job.updated_at = datetime.utcnow()
            db.session.commit()

        def on_progress(fase, progreso, mensaje, extra=None):
            _update_job_progress(
                job_id, fase=fase, progreso=progreso, mensaje=mensaje, extra=extra,
            )

        current_app.logger.info(
            'NotaAudioJob %s: iniciando transcripción (%.1fs)', job_id, duration,
        )
        transcript = transcribe_audio_file(
            audio_path, on_progress=on_progress, duration=duration,
        )
        if not transcript:
            transcript = '[inaudible — no se obtuvo texto del audio]'
        current_app.logger.info(
            'NotaAudioJob %s: transcripción OK (%s chars)', job_id, len(transcript),
        )

        _ensure_not_cancelled(job_id)
        _update_job_progress(
            job_id, fase='resumiendo', progreso=78, mensaje='Generando resumen de la nota…',
        )
        titulo, resumen = _summarize_gpt(transcript, summary_prompt=summary_prompt)
        current_app.logger.info('NotaAudioJob %s: resumen OK (%s)', job_id, titulo[:80])

        _ensure_not_cancelled(job_id)
        _update_job_progress(
            job_id, fase='vinculando', progreso=88,
            mensaje='Detectando obras y personas mencionadas…',
        )

        obra_matches: list[ObraMatch] = []
        person_matches: list[PersonMatch] = []
        try:
            from sqlalchemy.orm import joinedload

            obras = Obra.query.filter_by(is_deleted=False).all()
            users = (
                User.query
                .options(joinedload(User.company_rel))
                .filter(User.is_deleted.is_(False), User.active.is_(True))
                .all()
            )
            entities = _extract_entities_gpt(transcript)

            # 1) Mencione explícita del nombre completo / código en el texto
            obra_matches = match_obras_from_text(transcript, obras)
            # 2) Candidatos que GPT identifica como obras concretas (no ciudades)
            obra_matches.extend(match_obras_from_queries(entities.get('obras', []), obras))

            # Personas: solo las que GPT marca como relevantes (nada de barrer toda la plantilla)
            person_matches = match_persons_from_names(entities.get('personas', []), users)

            # Refuerzo suave: nombre+apellido completo literal en la transcripción
            norm_transcript = _normalize_text(transcript)
            for user in users:
                full = f'{user.name or ""} {user.lastname or ""}'.strip()
                norm_full = _normalize_text(full)
                toks = _tokens(full)
                if len(toks) < 2 or len(norm_full) < 8:
                    continue
                if norm_full in norm_transcript:
                    if not any(pm.user_id == user.id for pm in person_matches):
                        person_matches.append(PersonMatch(
                            query=full, user_id=user.id, user_name=full, ambiguous=False,
                        ))
        except Exception as link_exc:
            current_app.logger.warning(
                'NotaAudioJob %s: vínculo obras/personas falló (se guarda igual): %s',
                job_id, link_exc,
            )

        obra_matches = _dedupe_obra_matches(obra_matches)
        person_matches = _dedupe_person_matches(person_matches)

        _ensure_not_cancelled(job_id)
        _update_job_progress(
            job_id, fase='guardando', progreso=95, mensaje='Guardando nota privada…',
        )
        contenido = _build_nota_content(
            resumen,
            transcript,
            obra_matches,
            person_matches,
            include_transcript=include_transcript,
        )

        nota = Nota(
            titulo=titulo[:200],
            contenido=contenido,
            fecha=date.today(),
            es_privada=True,
            autor_id=autor_id,
        )
        # Solo fichas con vínculo claro (obra_id + score alto implícito al estar linkeadas)
        if obra_matches:
            ids = list(dict.fromkeys(m.obra_id for m in obra_matches if m.obra_id))
            if ids:
                nota.obras = Obra.query.filter(Obra.id.in_(ids)).all()
        linked_user_ids = list(dict.fromkeys(
            pm.user_id for pm in person_matches if pm.user_id and not pm.ambiguous
        ))
        if linked_user_ids:
            nota.usuarios_implicados = User.query.filter(User.id.in_(linked_user_ids)).all()

        db.session.add(nota)
        db.session.flush()

        job = NotaAudioJob.query.get(job_id)
        if not job:
            raise RuntimeError(f'Job {job_id} desapareció al guardar la nota')
        if job.estado == NotaAudioJob.ESTADO_CANCELADO:
            db.session.rollback()
            return
        job.nota_id = nota.id
        job.estado = NotaAudioJob.ESTADO_COMPLETADO
        job.completed_at = datetime.utcnow()
        job.meta_json = json.dumps({
            'fase': 'completado',
            'progreso': 100,
            'mensaje': 'Nota creada correctamente.',
            'obras': [
                {
                    'query': m.query,
                    'obra_id': m.obra_id,
                    'nombre': m.obra_nombre,
                    'ambiguous': m.ambiguous,
                    'candidates': m.candidates,
                }
                for m in obra_matches
            ],
            'personas': [
                {
                    'query': pm.query,
                    'user_id': pm.user_id,
                    'user_name': pm.user_name,
                    'ambiguous': pm.ambiguous,
                    'candidates': pm.candidates,
                }
                for pm in person_matches
            ],
            'sugerencias': {
                'obras': [
                    {
                        'query': m.query,
                        'candidates': m.candidates,
                    }
                    for m in obra_matches
                    if not m.obra_id and m.candidates
                ],
                'personas': [
                    {
                        'query': pm.query,
                        'candidates': pm.candidates,
                    }
                    for pm in person_matches
                    if (not pm.user_id or pm.ambiguous) and pm.candidates
                ],
            },
        }, ensure_ascii=False)
        job.error_message = None
        job.updated_at = datetime.utcnow()
        db.session.commit()
        current_app.logger.info(
            'NotaAudioJob %s: COMPLETADO → nota_id=%s', job_id, nota.id,
        )

    except NotaAudioCancelled:
        current_app.logger.info('NotaAudioJob %s: cancelado durante el proceso', job_id)
        db.session.rollback()
        return
    except Exception as exc:
        current_app.logger.exception('NotaAudioJob %s: ERROR %s', job_id, exc)
        db.session.rollback()
        job = NotaAudioJob.query.get(job_id)
        if job and job.estado != NotaAudioJob.ESTADO_CANCELADO:
            job.estado = NotaAudioJob.ESTADO_ERROR
            job.error_message = str(exc)[:2000]
            try:
                meta = json.loads(job.meta_json) if job.meta_json else {}
            except json.JSONDecodeError:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            meta.update({
                'fase': 'error',
                'progreso': meta.get('progreso') or 0,
                'mensaje': str(exc)[:500],
            })
            job.meta_json = json.dumps(meta, ensure_ascii=False)
            job.updated_at = datetime.utcnow()
            db.session.commit()
        raise
    finally:
        # No borrar archivo si sigue pendiente/procesando (no debería ocurrir aquí).
        # Si está cancelado/error/completado, limpiar disco.
        try:
            job = NotaAudioJob.query.get(job_id)
            path_to_clear = audio_path
            if job and job.archivo_path:
                path_to_clear = job.archivo_path
            if path_to_clear and os.path.isfile(path_to_clear):
                if not job or job.estado in (
                    NotaAudioJob.ESTADO_COMPLETADO,
                    NotaAudioJob.ESTADO_ERROR,
                    NotaAudioJob.ESTADO_CANCELADO,
                ):
                    try:
                        os.remove(path_to_clear)
                    except OSError:
                        pass
                    if job and job.archivo_path:
                        job.archivo_path = None
                        db.session.commit()
        except Exception:
            db.session.rollback()


def job_to_status_dict(job: NotaAudioJob) -> dict[str, Any]:
    meta = None
    if job.meta_json:
        try:
            meta = json.loads(job.meta_json)
        except json.JSONDecodeError:
            meta = None

    progreso = 0
    fase = job.estado
    mensaje = ''
    if isinstance(meta, dict):
        progreso = int(meta.get('progreso') or 0)
        fase = meta.get('fase') or job.estado
        mensaje = meta.get('mensaje') or ''

    if job.estado == NotaAudioJob.ESTADO_PENDIENTE and progreso < 5:
        progreso = 5
        fase = 'pendiente'
        mensaje = mensaje or 'En cola…'
    elif job.estado == NotaAudioJob.ESTADO_COMPLETADO:
        progreso = 100
        fase = 'completado'
        mensaje = mensaje or 'Nota creada correctamente.'
    elif job.estado == NotaAudioJob.ESTADO_ERROR:
        fase = 'error'
        mensaje = job.error_message or mensaje or 'Error al procesar el audio'
    elif job.estado == NotaAudioJob.ESTADO_CANCELADO:
        fase = 'cancelado'
        progreso = 0
        mensaje = job.error_message or mensaje or 'Procesamiento cancelado.'

    data: dict[str, Any] = {
        'job_id': job.id,
        'estado': job.estado,
        'nota_id': job.nota_id,
        'error': job.error_message,
        'duracion_segundos': job.duracion_segundos,
        'archivo_nombre': job.archivo_nombre,
        'progreso': progreso,
        'fase': fase,
        'mensaje': mensaje,
        'meta': meta,
    }
    return data
