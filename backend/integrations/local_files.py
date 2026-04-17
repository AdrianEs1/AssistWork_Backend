import os
import re
import fitz  # PyMuPDF
import docx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from apps.database import SessionLocal
from apps.models.context_file import ContextFile
from apps.services.storage.gcs_service import download_to_memory, file_exists
from apps.services.tool_registry import tool

# --- Utilidades ---
def normalize_name(name: str) -> str:
    return re.sub(r"[\s_\-]", "", name.lower())

def sanitize_query(query: str) -> str:
    if not query: return query
    q = query.lower().strip()
    patterns = [r"name\s*=\s*", r"name\s+contains\s*", r"name\s+like\s*"]
    for pattern in patterns:
        q = re.sub(pattern, "", q)
    return q.strip("'\"").strip()

# --- HERRAMIENTAS ---

@tool(group="localfiles")
async def list_local_files(user_id: str, query: Optional[str] = None, max_results: int = 10) -> str:
    """
    Lista archivos (como PDFs, DOCXs, TXTs) que el usuario ha adjuntado previamente al sistema.
    Si se provee 'query', filtrará los archivos por coincidencia en el nombre.
    """
    db: Session = SessionLocal()
    try:
        files_query = db.query(ContextFile).filter(ContextFile.user_id == user_id)
        all_files: List[ContextFile] = files_query.all()

        all_files_dict = [
            {"path": f.gcs_path, "name": f.name, "mimeType": f.mime_type}
            for f in all_files
        ]

        if not all_files_dict:
            return "No hay archivos locales/GCS disponibles para este usuario."

        if not query:
            res = f"Archivos disponibles ({len(all_files_dict)}). Especifica el 'path' de alguno para leerlo:\n"
            for f in all_files_dict[:max_results]:
                res += f"- {f['name']} (Path: {f['path']})\n"
            return res

        query = sanitize_query(query)
        normalized_query = normalize_name(query)
        matched_files = [f for f in all_files_dict if normalized_query in normalize_name(f["name"])]

        if not matched_files:
            return f"No se encontraron archivos que coincidan con '{query}'."

        res = f"Coincidencias encontradas ({len(matched_files)}):\n"
        for f in matched_files[:max_results]:
            res += f"- {f['name']} (Path: {f['path']})\n"
        return res
        
    except Exception as e:
        return f"Error listando archivos: {str(e)}"
    finally:
        db.close()

@tool(group="localfiles")
async def read_local_file(user_id: str, file_path: str) -> str:
    """
    Lee el contenido en texto plano de un archivo utilizando su 'file_path'.
    (El file_path normalmente viene de haber ejecutado list_local_files previamente).
    """
    db: Session = SessionLocal()
    try:
        context_file = db.query(ContextFile).filter(
            ContextFile.user_id == user_id,
            ContextFile.gcs_path == file_path
        ).first()

        if not context_file:
            return f"Error: No tienes acceso o no existe el archivo '{file_path}'."

        if not file_exists(file_path):
            return f"Error: El archivo '{file_path}' ya no está disponible en Cloud Storage."

        file_bytes = download_to_memory(file_path)
        content = ""
        mime_type = context_file.mime_type

        if mime_type == "application/pdf":
            with fitz.open(stream=file_bytes.read(), filetype="pdf") as doc:
                content = "\n".join(page.get_text("text") for page in doc)
        
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            document = docx.Document(file_bytes)
            content = "\n".join(p.text for p in document.paragraphs if p.text.strip())
        
        else:
            content = file_bytes.read().decode("utf-8", errors="ignore")

        return f"CONTENIDO DE {context_file.name} ({mime_type}):\n\n{content}"

    except Exception as e:
        return f"Error al intentar leer el archivo: {str(e)}"
    finally:
        db.close()
