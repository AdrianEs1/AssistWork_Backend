"""
gcs_service.py
Servicio para gestionar archivos en Google Cloud Storega
"""

from google.cloud import storage
from google.oauth2 import service_account
from google.cloud.exceptions import NotFound
from io import BytesIO
from datetime import timedelta
import os
import base64
import json
import uuid
import re
from config import GCS_BUCKET_NAME, GOOGLE_APPLICATION_CREDENTIALS

# Configuración
BUCKET_NAME = GCS_BUCKET_NAME
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
CREDENTIALS_BASE64 = GOOGLE_APPLICATION_CREDENTIALS



def sanitize_filename(name: str) -> str:
    """
    Limpia nombre de archivo para evitar caracteres peligrosos
    """
    name = os.path.basename(name)
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name

def validate_pdf(file_content: bytes) -> bool:
    """
    Verifica que el archivo sea realmente un PDF usando magic bytes
    """
    return file_content.startswith(b"%PDF")

# Inicializar cliente GCS
def get_storage_client():
    """
    Inicializa cliente de GCS con credenciales desde:
    1. Variable de entorno GCS_CREDENTIALS_BASE64 (producción)
    2. Archivo JSON en GOOGLE_APPLICATION_CREDENTIALS (desarrollo)
    3. Application Default Credentials (si corre en GCP)
    """
    if CREDENTIALS_BASE64:
        # Decodificar base64 y crear credenciales
        try:
            credentials_json = base64.b64decode(CREDENTIALS_BASE64).decode('utf-8')
            credentials_dict = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_dict)
            client = storage.Client(credentials=credentials, project=credentials_dict['project_id'])
            print("✅ GCS inicializado con credenciales base64")
            return client
        except Exception as e:
            print(f"❌ Error decodificando credenciales base64: {e}")
            raise
    
    elif CREDENTIALS_PATH and os.path.exists(CREDENTIALS_PATH):
        # Usar archivo JSON
        client = storage.Client.from_service_account_json(CREDENTIALS_PATH)
        print(f"✅ GCS inicializado con archivo JSON: {CREDENTIALS_PATH}")
        return client
    
    else:
        # Usar Application Default Credentials (si corres en GCP)
        client = storage.Client()
        print("✅ GCS inicializado con Application Default Credentials")
        return client

# Cliente y bucket
storage_client = get_storage_client()
bucket = storage_client.bucket(BUCKET_NAME)


def upload_file(file_content: bytes, user_id: str, original_filename: str, file_hash: str = None) -> dict:
    """
    Sube un archivo a GCS usando un hash para evitar duplicados físicos.
    """
    try:
        safe_name = sanitize_filename(original_filename)
        file_extension = os.path.splitext(safe_name)[1].lower()
        
        # Si no hay hash, usamos UUID (comportamiento anterior)
        # Si hay hash, el nombre es único por contenido
        unique_name = file_hash if file_hash else str(uuid.uuid4())
        filename = f"{unique_name}{file_extension}"
        
        gcs_path = f"users/{user_id}/documents/{filename}"
        blob = bucket.blob(gcs_path)

        # OPTIMIZACIÓN: Si el archivo ya existe físicamente en GCS, no lo resubas
        if blob.exists():
            print(f"ℹ️ Archivo ya existe en GCS, omitiendo subida: {gcs_path}")
            return {
                "success": True,
                "gcs_path": gcs_path,
                "file_size": len(file_content),
                "already_existed": True
            }

        # Subir archivo
        blob.upload_from_string(file_content, content_type="application/pdf")
        
        print(f"✅ Nuevo archivo subido a GCS: {gcs_path}")
        return {
            "success": True,
            "gcs_path": gcs_path,
            "file_size": len(file_content),
            "already_existed": False
        }
    
    except Exception as e:
        print(f"❌ Error subiendo a GCS: {e}")
        return {"success": False, "error": str(e)}
    

def download_to_memory(gcs_path: str) -> BytesIO:
    """
    Descarga archivo de GCS a memoria (BytesIO)
    
    Args:
        gcs_path: Ruta en GCS (ej: "users/123/documents/file.pdf")
    
    Returns:
        BytesIO con el contenido del archivo
    """
    try:
        blob = bucket.blob(gcs_path)
        file_bytes = BytesIO()
        blob.download_to_file(file_bytes)
        file_bytes.seek(0)  # Resetear puntero al inicio
        
        print(f"✅ Archivo descargado de GCS: {gcs_path}")
        return file_bytes
    
    except NotFound:
        print(f"❌ Archivo no encontrado en GCS: {gcs_path}")
        raise FileNotFoundError(f"Archivo no existe: {gcs_path}")
    
    except Exception as e:
        print(f"❌ Error descargando de GCS: {e}")
        raise


def generate_signed_url(gcs_path: str, expiration_minutes: int = 60) -> str:
    """
    Genera URL firmada temporal para acceso directo
    
    Args:
        gcs_path: Ruta en GCS
        expiration_minutes: Tiempo de validez en minutos
    
    Returns:
        URL firmada (válida por X minutos)
    """
    try:
        blob = bucket.blob(gcs_path)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET"
        )
        
        print(f"✅ URL firmada generada: {gcs_path} (válida {expiration_minutes}min)")
        return url
    
    except Exception as e:
        print(f"❌ Error generando URL firmada: {e}")
        raise


def delete_file(gcs_path: str) -> bool:
    """
    Elimina archivo de GCS
    
    Args:
        gcs_path: Ruta en GCS
    
    Returns:
        True si se eliminó correctamente
    """
    try:
        blob = bucket.blob(gcs_path)
        blob.delete()
        
        print(f"✅ Archivo eliminado de GCS: {gcs_path}")
        return True
    
    except NotFound:
        print(f"⚠️ Archivo ya no existe: {gcs_path}")
        return True
    
    except Exception as e:
        print(f"❌ Error eliminando de GCS: {e}")
        return False


def file_exists(gcs_path: str) -> bool:
    """
    Verifica si un archivo existe en GCS
    """
    try:
        blob = bucket.blob(gcs_path)
        return blob.exists()
    except Exception:
        return False