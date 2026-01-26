"""
dependencies.py
Funciones de autenticación reutilizables para HTTP y WebSocket
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from apps.core.security import decode_token
from apps.models.user import User


async def get_user_from_token(token: str, db: Session) -> User:
    """
    Valida un JWT token y retorna el usuario.
    Reutilizable para HTTP (via HTTPBearer) y WebSocket (via query params).
    
    Args:
        token: JWT access token
        db: Sesión de base de datos
        
    Returns:
        User: Usuario autenticado
        
    Raises:
        HTTPException: Si el token es inválido o el usuario no existe/inactivo
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Decodificar token
    payload = decode_token(token)
    
    if payload is None:
        raise credentials_exception
    
    user_id: str = payload.get("sub")
    token_type: str = payload.get("type")
    
    if user_id is None or token_type != "access":
        raise credentials_exception
    
    # Buscar usuario en BD
    user = db.query(User).filter(User.id == user_id).first()
    
    if user is None:
        raise credentials_exception
    
    # Validar que esté activo
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )
    
    return user