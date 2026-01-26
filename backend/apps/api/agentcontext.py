from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form, File
from sqlalchemy.orm import Session
from typing import List
from apps.core.dependencies import get_db, get_current_user
from apps.models.user import User
from apps.models.conversation import Conversation
from apps.models.context_file import ContextFile
import uuid
import os

router = APIRouter(prefix="/agent/context", tags=["Agent Context"])

@router.post("/files")
def set_conversation_files(
    conversation_id: uuid.UUID = Form(...),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    print(f"📎 Conversación: {conversation_id}")

    # Verificar que la conversación existe y pertenece al usuario
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    # Directorio para almacenar los archivos
    base_path = f"storage/conversations/{conversation_id}"
    os.makedirs(base_path, exist_ok=True)

    saved_files = []

    for file in files:
        file_path = os.path.join(base_path, file.filename)

        # Guardar archivo en disco
        with open(file_path, "wb") as f:
            f.write(file.file.read())

        # Guardar registro en la tabla ContextFile
        context_file = ContextFile(
            user_id=current_user.id,
            name=file.filename,
            mine_type=file.content_type,
            path=file_path
        )
        db.add(context_file)
        saved_files.append(context_file)

    # Guardar cambios en la DB
    db.commit()

    return {
        "success": True,
        "message": "📎 Archivos locales asociados al usuario",
        "files_count": len(saved_files),
        "files": [{"id": f.id, "name": f.name, "mime_type": f.mine_type, "path": f.path} for f in saved_files]
    }
