from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from apps.models.conversation import Conversation
from apps.database import SessionLocal
from apps.models.context_file import ContextFile
import os
import mimetypes
import fitz  # PyMuPDF
import docx
import re

# -------------------------------------------------
# 🔎 Utilidades
# -------------------------------------------------

def normalize_name(name: str) -> str:
    return re.sub(r"[\s_\-]", "", name.lower())



def sanitize_query(query: str) -> str:
    """
    Normaliza cualquier query generada por el LLM y retorna
    únicamente el nombre del archivo esperado.
    """
    if not query:
        return query

    q = query.lower().strip()

    # 🔥 Eliminar patrones tipo Drive / SQL
    patterns = [
        r"name\s*=\s*",
        r"name\s+contains\s*",
        r"name\s+like\s*",
    ]

    for pattern in patterns:
        q = re.sub(pattern, "", q)

    # 🔥 Eliminar comillas simples y dobles
    q = q.strip("'\"")

    # 🔥 Eliminar espacios sobrantes
    q = q.strip()

    return q



# -------------------------------------------------
# 📂 Listar archivos locales asociados al usuario
# -------------------------------------------------


def list_files(
    user_id: str,
    query: Optional[str] = None,
    max_results: int = 10,
    auto_select: bool = True,
    **kwargs
):
    """
    Lista archivos previamente adjuntados por el usuario.

    🔑 Fuente de verdad: tabla ContextFile
    """

    print(f"Este es el query que le llega a listfiles: {query}")

    db: Session = SessionLocal()
    try:
        # Consulta todos los archivos del usuario
        files_query = db.query(ContextFile).filter(ContextFile.user_id == user_id)

        # Traer todos los archivos
        all_files: List[ContextFile] = files_query.all()

        # Mapear a dicts para compatibilidad con el frontend
        all_files_dict = [
            {
                "path": f.path,
                "name": f.name,
                "mimeType": f.mine_type,
                "source": "local"
            }
            for f in all_files
        ]

        print(f"Estos son los files obtenidos en listfiles: {all_files_dict}")

        # No hay archivos
        if not all_files_dict:
            return {
                "success": True,
                "files": [],
                "auto_selected": False,
                "needs_user_choice": False,
                "message": (
                    "📎 **No hay archivos locales disponibles**\n\n"
                    "Adjunta archivos desde tu equipo para poder usarlos."
                )
            }

        # Sin query → mostrar disponibles
        if not query:
            return {
                "success": True,
                "files": all_files_dict[:max_results],
                "auto_selected": False,
                "needs_user_choice": True,
                "message": (
                    f"📂 **Archivos disponibles ({len(all_files_dict)})**\n\n"
                    "Indica el nombre del archivo que deseas usar."
                )
            }

        # Filtrado por query
        query = sanitize_query(query)
        normalized_query = normalize_name(query)
        matched_files = []

        for f in all_files_dict:
            normalized_name = normalize_name(f["name"])
            if normalized_query == normalized_name or normalized_query in normalized_name:
                matched_files.append(f)

        # Sin coincidencias
        if not matched_files:
            return {
                "success": True,
                "files": [],
                "auto_selected": False,
                "needs_user_choice": False,
                "message": (
                    "📂 **Archivo no disponible**\n\n"
                    f"No encontré un archivo llamado **{query}**."
                )
            }

        matched_files = matched_files[:max_results]

        # Auto selección
        if len(matched_files) == 1 and auto_select:
            file = matched_files[0]
            return {
                "success": True,
                "files": matched_files,
                "auto_selected": True,
                "selected_file": file,
                "needs_user_choice": False,
                "message": (
                    "✅ **Archivo seleccionado automáticamente**\n\n"
                    f"📄 **{file['name']}**\n"
                    f"📍 `{file['path']}`"
                )
            }

        # Múltiples opciones
        user_message = f"🤔 **Encontré {len(matched_files)} archivos. ¿Cuál deseas usar?**\n\n"

        for i, f in enumerate(matched_files, 1):
            user_message += (
                f"**{i}. {f['name']}**\n"
                f"📍 `{f['path']}`\n\n"
            )

        user_message += "💬 Responde con el número del archivo."

        return {
            "success": True,
            "files": matched_files,
            "auto_selected": False,
            "needs_user_choice": True,
            "message": user_message
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "auto_selected": False,
            "needs_user_choice": False,
            "message": f"❌ **Error resolviendo archivos**\n\n{str(e)}"
        }
    finally:
        db.close()



# -------------------------------------------------
# 📖 Leer archivo local
# -------------------------------------------------

def read_file(
    user_id: str,
    path: str = None,
    file_id: str = None,
    **kwargs
):
    """
    Lee el contenido de un archivo local.
    Compatible con orquestador que envía `file_id`.
    """

    file_path = path or file_id

    try:
        if not file_path or not os.path.exists(file_path):
            return {
                "success": False,
                "message": "❌ El archivo no existe o no es accesible en el sistema local."
            }

        mime_type, _ = mimetypes.guess_type(file_path)
        content = ""

        if mime_type == "application/pdf":
            with fitz.open(file_path) as doc:
                content = "\n".join(page.get_text("text") for page in doc)

        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            document = docx.Document(file_path)
            content = "\n".join(p.text for p in document.paragraphs if p.text.strip())

        else:
            with open(file_path, "r", errors="ignore") as f:
                content = f.read()

        preview_length = kwargs.get("preview_length", 500)
        show_full = kwargs.get("show_full", False)

        user_message = (
            "📄 **Archivo local leído exitosamente**\n\n"
            f"📝 **Nombre:** {os.path.basename(file_path)}\n"
            f"📋 **Tipo:** {mime_type}\n"
            f"📊 **Tamaño:** {len(content)} caracteres\n"
            f"📍 **Ruta:** `{file_path}`\n\n"
        )

        if show_full or len(content) <= preview_length:
            user_message += f"📄 **Contenido:**\n```\n{content}\n```"
        else:
            user_message += f"📄 **Contenido:**\n```\n{content[:preview_length]}...\n```\n\n*(Vista previa truncada)*"

        return {
            "success": True,
            "file_name": os.path.basename(file_path),
            "mime_type": mime_type,
            "content": content,
            "content_length": len(content),
            "content_preview": content[:preview_length],
            "message": user_message
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ **Error leyendo archivo local**\n\n🚫 {str(e)}"
        }


# -------------------------------------------------
# 📚 Registro para el agente
# -------------------------------------------------

LOCAL_FILES_TOOL_METHODS = {
    "list_files": {
        "func": list_files,
        "description": "Listar archivos locales asociados al usuario."
    },
    "read_file": {
        "func": read_file,
        "description": "Leer y devolver el contenido textual de un archivo local (PDF, DOCX, TXT, etc.)."
    }
}
