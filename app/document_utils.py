# app/document_utils.py

import os
import io
import zipfile
from flask import send_file, flash, redirect, url_for
from app.models import Document
#ss
def get_document_for_user(user_id):
    """
    Obtiene el registro de documentos para un usuario.
    Se asume que existe máximo un registro por usuario.
    """
    return Document.query.filter_by(user_id=user_id).first()

def download_document_file(user_id, doc_type, redirect_endpoint):
    """
    Descarga un solo documento (doc1, doc2 o doc3) de un usuario.
    Si no se encuentra el registro o el archivo, redirige al endpoint indicado.
    """
    document = get_document_for_user(user_id)
    if not document:
        flash("No se encontraron documentos para este usuario", "danger")
        return redirect(url_for(redirect_endpoint))
    file_path = getattr(document, doc_type, None)
    if not file_path or not os.path.exists(file_path):
        flash("Documento no encontrado", "danger")
        return redirect(url_for(redirect_endpoint))
    return send_file(file_path, as_attachment=True)

def download_documents_zip(user_id, redirect_endpoint):
    """
    Genera y descarga un archivo ZIP que contenga los tres documentos
    (doc1, doc2 y doc3) del usuario.
    """
    document = get_document_for_user(user_id)
    if not document:
        flash("No se encontraron documentos para este usuario", "danger")
        return redirect(url_for(redirect_endpoint))
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for doc_attr in ['doc1', 'doc2', 'doc3']:
            file_path = getattr(document, doc_attr, None)
            if file_path and os.path.exists(file_path):
                zf.write(file_path, os.path.basename(file_path))
    memory_file.seek(0)
    return send_file(memory_file,
                     attachment_filename=f'user_{user_id}_documents.zip',
                     as_attachment=True)
