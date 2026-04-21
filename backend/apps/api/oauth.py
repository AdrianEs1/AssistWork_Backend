from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import List

from apps.core.dependencies import get_db, get_current_user
from apps.services.oauth.oauth_service import oauth_service
from apps.schemas.oauth import (
    OAuthConnectResponse,
    OAuthConnectionResponse
)
from apps.models.user import User
from apps.models.oauth_connection import OAuthConnection
#from tools.App_Drive.dic_drive_tool import DriveService
from apps.services.oauth.utils import get_integration_config
from config import FRONTEND_URL


router = APIRouter(prefix="/oauth", tags=["OAuth"])


@router.get("/{integration}/connect", response_model=OAuthConnectResponse)
async def connect_service(
    integration: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)  # Ya lo tienes
):
    """
    Inicia el flujo OAuth para conectar cualquier servicio de Google
    (Gmail, Drive, Calendar, etc.)
    
    Si el usuario ya tiene otros servicios conectados, se solicitarán
    los scopes acumulados para mantener la compatibilidad.
    """

    # Verificar que el servicio sea soportado
    try:
        config = get_integration_config(integration)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"Integración '{integration}' no soportada"
        )

    # Primero intentar reconexión rápida
    result = oauth_service.reconnect_service(
        str(current_user.id),
        integration,
        db
    )
    
    if result["reconnected"]:
        # Reconectado sin OAuth
        return {"status": "reconnected", "message": result["message"]}

    

    # Generar URL de autorización con scopes acumulados
    authorization_url, state = oauth_service.generate_authorization_url(
        str(current_user.id),
        integration,
        db  # 🔥 Ahora necesita la sesión de BD
    )

    return {
        "authorization_url": authorization_url,
        "state": state
    }


@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Callback único para todas las integraciones Google OAuth.
    - No se extrae `service` aquí, el `handle_callback` es la única fuente de verdad.
    - El `state` puede tener formato: user_id:service:nonce
    """

    # 1) Extraer user_id de forma segura
    parts = state.split(":", 2)
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="State inválido")

    user_id = parts[0]

    try:
        # 2) handle_callback ahora extrae y valida service internamente
        oauth_conn = oauth_service.handle_callback(
            code=code,
            state=state,
            user_id=user_id,
            db=db
        )

        integration = oauth_conn.integration
        email = oauth_conn.meta_data.get("email", "")

        # HTML de cierre
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Autenticación exitosa</title></head>
        <body>
            <h2>✅ Autenticación exitosa en {integration.capitalize()}</h2>
            <p>Cerrando ventana...</p>
            <script>
                try {{
                    if (window.opener) {{
                        window.opener.postMessage({{
                            status: 'success',
                            app: '{integration}',
                            email: '{email}'
                        }}, '{FRONTEND_URL}');
                    }}
                }} catch(e) {{
                    console.log('No se pudo enviar mensaje al opener:', e);
                }} finally {{
                    setTimeout(() => window.close(), 500);
                }}
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)

    except Exception as e:
        return HTMLResponse(content=f"Error procesando OAuth: {str(e)}")


@router.get("/connections", response_model=List[OAuthConnectionResponse])
async def get_connections(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene todas las conexiones OAuth activas del usuario
    """
    connections = db.query(OAuthConnection).filter_by(
        user_id=current_user.id,
        is_active=True
    ).all()

    return connections


@router.get("/{integration}/status")
async def service_status(
    integration: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifica si un servicio está conectado
    """
    oauth_conn = oauth_service.get_user_connection(
        str(current_user.id),
        integration,
        db
    )


    if not oauth_conn:
        return {"connected": False, "message": f"{integration.capitalize()} no conectado"}

    return {
        "connected": True,
        "email": oauth_conn.meta_data.get('email') if oauth_conn.meta_data else None,
        "connected_at": oauth_conn.connected_at,
        "last_used_at": oauth_conn.last_used_at
    }


@router.delete("/{integration}/disconnect")
async def disconnect_service(
    integration: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Desconecta un servicio específico.
    
    Si es el último servicio activo, revoca el token en Google y elimina
    todos los registros para permitir un inicio limpio.
    """
    result = oauth_service.disconnect_service(
        str(current_user.id),
        integration,
        db
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{integration.capitalize()} no estaba conectado"
        )

    message = f"{integration.capitalize()} desconectado exitosamente"
    
    if result["revoked"] and result["cleaned"]:
        message += ". Token revocado en Google - puedes reconectar servicios en cualquier orden."
    elif result["remaining_services"] > 0:
        message += f". Aún tienes {result['remaining_services']} servicio(s) conectado(s)."

    return {
        "success": True,
        "message": message,
        "revoked_in_google": result["revoked"],
        "cleaned_database": result["cleaned"],
        "remaining_services": result["remaining_services"]
    }

#Endpoint para enviar token y permitir el uso de Google Picker y así poder acceder a Drive
@router.get("/drive/access-token")
async def get_drive_access_token(
    current_user: User = Depends(get_current_user),
):
    try:
        #drive = DriveService()
        #service = drive.get_service(str(current_user.id))
        """creds = service._http.credentials

        if not creds or not creds.token:
            raise HTTPException(
                status_code=401,
                detail="No se pudo obtener token válido de Drive"
            )

        return {
            "access_token": creds.token
        }"""

    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo access token de Drive"
        )

