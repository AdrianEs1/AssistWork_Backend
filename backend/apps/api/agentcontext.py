from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form, File
from sqlalchemy.orm import Session
from typing import List
from apps.core.dependencies import get_db, get_current_user
from apps.models.user import User
from apps.models.conversation import Conversation
from apps.models.context_file import ContextFile
from apps.services.storage.gcs_service import upload_file
import uuid
import os
from apps.middleware.subscription_middleware import (
    check_file_upload_limit,
    record_file_usage,
    SubscriptionLimitError
)

router = APIRouter(prefix="/agent/context", tags=["Agent Context"])

@router.post("/files")
def set_conversation_files(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sube archivos del usuario a Google Cloud Storage
    """

    # ← NUEVO: Verificar límites ANTES de procesar
    try:
        check_file_upload_limit(current_user.id, len(files), db)
    except SubscriptionLimitError as e:
        raise HTTPException(
            status_code=403,
            detail={
                "message": e.message,
                "upgrade_required": e.upgrade_required,
                "upgrade_url": "/pricing" if e.upgrade_required else None
            }
        )
    
    # Validaciones
    MAX_FILE_SIZE_MB = 10
    MAX_FILES_PER_USER = 50
    ALLOWED_MIME_TYPES = ["application/pdf"]
    
    # Verificar límite de archivos
    existing_count = db.query(ContextFile).filter(
        ContextFile.user_id == current_user.id
    ).count()
    
    if existing_count + len(files) > MAX_FILES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Límite de archivos alcanzado. Máximo {MAX_FILES_PER_USER} archivos por usuario."
        )
    
    saved_files = []
    
    for file in files:
        # Validar tipo MIME
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de archivo no permitido: {file.content_type}. Solo se permiten PDFs."
            )
        
        # Leer contenido
        file_content = file.file.read()
        file_size = len(file_content)
        
        # Validar tamaño
        max_size_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size > max_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Archivo {file.filename} excede el tamaño máximo de {MAX_FILE_SIZE_MB}MB"
            )
        
        # Subir a GCS
        upload_result = upload_file(
            file_content=file_content,
            user_id=str(current_user.id),
            original_filename=file.filename
        )
        
        if not upload_result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"Error subiendo archivo {file.filename}: {upload_result.get('error')}"
            )
        
        # Guardar en BD
        context_file = ContextFile(
            user_id=current_user.id,
            name=file.filename,
            mime_type=file.content_type,
            file_size=file_size,
            gcs_path=upload_result["gcs_path"]
        )
        db.add(context_file)
        saved_files.append(context_file)
    
    db.commit()
    # ← NUEVO: Registrar uso
    record_file_usage(current_user.id, len(saved_files), db)
    
    return {
        "success": True,
        "message": f"☁️ {len(saved_files)} archivo(s) subido(s) a Cloud Storage",
        "files_count": len(saved_files),
        "files": [
            {
                "id": str(f.id),
                "name": f.name,
                "mime_type": f.mime_type,
                "file_size": f.file_size,
                "gcs_path": f.gcs_path
            }
            for f in saved_files
        ]
    }