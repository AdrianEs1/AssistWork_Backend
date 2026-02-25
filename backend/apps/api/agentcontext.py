from fastapi import APIRouter, Depends, HTTPException, UploadFile, status,Form, File
from sqlalchemy.orm import Session
from typing import List
from apps.core.dependencies import get_db, get_current_user
from apps.models.user import User
from apps.models.conversation import Conversation
from apps.models.context_file import ContextFile
from apps.services.storage.gcs_service import upload_file, validate_pdf, generate_signed_url, delete_file
from apps.schemas.agent_context import FilesDetail
import uuid
import os
import hashlib
from apps.middleware.subscription_middleware import (
    check_file_upload_limit,
    record_file_usage,
    SubscriptionLimitError
)

router = APIRouter(prefix="/agent/context", tags=["Agent Context"])


@router.post("/files")
async def set_conversation_files(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Verificación de límites de suscripción (Tal cual lo tenías)
    try:
        check_file_upload_limit(current_user.id, len(files), db)
    except SubscriptionLimitError as e:
        raise HTTPException(status_code=403, detail={"message": e.message})

    # Configuraciones
    MAX_FILE_SIZE_MB = 10
    ALLOWED_MIME_TYPES = ["application/pdf"]
    saved_files = []
    skipped_duplicates = 0

    for file in files:
        # A. Validación rápida de MIME Type
        if file.content_type not in ALLOWED_MIME_TYPES:
            continue # O lanza error si prefieres ser estricto

        # B. Leer contenido y generar HASH
        file_content = await file.read() # Importante usar await
        file_hash = hashlib.sha256(file_content).hexdigest()
        file_size = len(file_content)

        # C. Verificar DUPLICADO en Base de Datos
        existing_in_db = db.query(ContextFile).filter(
            ContextFile.user_id == current_user.id,
            ContextFile.file_hash == file_hash
        ).first()

        if existing_in_db:
            skipped_duplicates += 1
            continue # Saltamos a la siguiente iteración

        # D. Validaciones de integridad (PDF real y tamaño)
        if not validate_pdf(file_content):
            raise HTTPException(status_code=400, detail=f"Archivo {file.filename} no es un PDF válido")

        if file_size > (MAX_FILE_SIZE_MB * 1024 * 1024):
            raise HTTPException(status_code=400, detail=f"Archivo {file.filename} excede los {MAX_FILE_SIZE_MB}MB")

        # E. Subida a GCS (Ahora enviamos el file_hash)
        upload_result = upload_file(
            file_content=file_content,
            user_id=str(current_user.id),
            original_filename=file.filename,
            file_hash=file_hash # <--- Pasamos el hash al service
        )

        if not upload_result["success"]:
            continue # O manejar el error de GCS

        # F. Registro en BD
        new_file = ContextFile(
            user_id=current_user.id,
            name=file.filename,
            mime_type=file.content_type,
            file_size=file_size,
            file_hash=file_hash, # <--- Guardamos el hash
            gcs_path=upload_result["gcs_path"]
        )
        db.add(new_file)
        saved_files.append(new_file)

    # G. Finalización
    if saved_files:
        db.commit()
        # Refrescar para obtener los IDs generados
        for f in saved_files: db.refresh(f)
        record_file_usage(current_user.id, len(saved_files), db)

    return {
        "success": True,
        "message": f"Procesados: {len(saved_files)} subidos, {skipped_duplicates} duplicados omitidos.",
        "files": [
            {
                "id": str(f.id),
                "name": f.name,
                "gcs_path": f.gcs_path
            } for f in saved_files
        ]
    }

@router.get("/uploaded-files", response_model=FilesDetail)
async def get_files_uploaded(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)

):
    "Permite obtener los archivos subidos por el usuario"
    

    files= db.query(ContextFile).filter(
        ContextFile.user_id == current_user.id
    ).all()

    return{
        "file":files
    }

@router.delete("/delete-file/{file_id}")
async def delete_files(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Elimina un archivo definitivamente del contexto
    """

    file = db.query(ContextFile).filter(
        ContextFile.id == file_id,
        ContextFile.user_id == current_user.id

    ).first()

    if not file:
        raise HTTPException(
            status_code= status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado"

        )
    
    # Seguridad extra: validar ownership en path
    expected_prefix = f"users/{current_user.id}/"

    if not file.gcs_path.startswith(expected_prefix):
        raise HTTPException(
            status_code=403,
            detail="Acceso no autorizado al archivo"
        )

    delete_file(file.gcs_path)
    
    # ⚠️ Eliminación definitiva
    db.delete(file)
    db.commit()

    return {
        "success": True,
        "message": "Archivo eliminado permanentemente"
    }