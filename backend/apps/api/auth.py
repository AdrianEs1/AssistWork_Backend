from fastapi import APIRouter, Request, Depends, HTTPException, status, Response, Cookie
from sqlalchemy.orm import Session
from apps.core.dependencies import get_db, get_current_user, create_secure_token
from apps.core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token, 
    create_refresh_token,
    decode_token, hash_code, COOKIE_SECURE, 
)
from apps.core.email_verification_service import create_email_verification, verify_email_code
from apps.schemas.auth import UserRegister, UserLogin, Token, TokenRefresh, UserResponse, ForgotPasswordRequest, ResetPasswordRequest, DeleteAccountRequest, VerifyEmailRequest, ResendVerificationRequest, MessageResponse
from apps.models.user import User
from datetime import datetime, timedelta
from apps.core.send_email import send_reset_email, send_delete_account_email, send_verification_email
from apps.services.payments.subscription_service import create_trial_subscription
from config import FRONTEND_URL
MIN_WAIT = timedelta(minutes=2)
MAX_ATTEMPTS = 5
RESET_WINDOW = timedelta(hours=1)

from apps.core.limiter import limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request:Request, 
    user_data: UserRegister, 
    db: Session = Depends(get_db)):
    """
    Registrar nuevo usuario
    """
    # Verificar si el email ya existe
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado"
        )
    
    # Crear usuario
    new_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        name=user_data.name,
        is_active=True,
        is_verified=False
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # ← NUEVO: Crear suscripción trial de 7 días
    create_trial_subscription(new_user.id, db)

    # 2️⃣ crear verificación
    code = create_email_verification(new_user.id, db)

    # 3️⃣ enviar email
    send_verification_email(new_user.email, code)
    
    return {
        "message": "Cuenta creada. Revisa tu correo para activar tu cuenta."
    }


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request:Request, 
    credentials: UserLogin, 
    response: Response, db: 
    Session = Depends(get_db)):
    """Login de usuario"""
    user = db.query(User).filter(User.email == credentials.email).first()
    
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )

    #FIX integrado solucionando problema de seguridad
    if not user.is_verified:
        raise HTTPException(
           status_code=status.HTTP_403_FORBIDDEN,
           detail="Cuenta no verificada" 
        )
    
    user.last_login = datetime.utcnow()
    
    
    # Crear tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    user.refresh_token_hash = hash_code(refresh_token)
    db.commit()
    
    # ✅ Guardar refresh_token en HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,  # No accesible desde JavaScript
        secure=True,    # Solo HTTPS en producción
        samesite="none",   # Protección CSRF
        # partitioned=True, Activar en futuras versiones
        max_age=7 * 24 * 60 * 60  # 7 días en segundos
    )
    
    # Solo devolver access_token en el body
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh_token(
    request:Request,
    response: Response,
    refresh_token: str = Cookie(None),  # Leer desde cookie
    db: Session = Depends(get_db)
):
    """Refrescar access token"""
    
    
    payload = decode_token(refresh_token)
    
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido"
        )
    
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo"
        )
    
    if not user.refresh_token_hash or user.refresh_token_hash != hash_code(refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido"
        )

    # Crear nuevos tokens
    new_access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    # Actualizar cookie
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        # partitioned=True,  Activar en futuras versiones
        max_age=7 * 24 * 60 * 60
    )

    user.refresh_token_hash=hash_code(new_refresh_token)
    db.commit()
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }


@router.post("/verify-email")
@limiter.limit("3/minute")
async def verify_email(
    request:Request,
    payload: VerifyEmailRequest,
    db: Session = Depends(get_db)
):
    print(f"Este es el correo que llega a verify-email: {payload.email}")
    verify_email_code(payload.email, payload.code, db)

    return {
        "message": "Cuenta verificada correctamente. Ya puedes iniciar sesión."
    }


@router.post("/resend-verification-code")
@limiter.limit("2/minute")
async def resend_code(
    request:Request,
    payload: ResendVerificationRequest,
    db: Session = Depends(get_db)
):
    email = payload.email
    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario no encontrado"
        )

    if user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La cuenta ya está verificada"
        )

    # 🔒 Asegurar valor entero
    if user.verification_attempts is None:
        user.verification_attempts = 0

    now = datetime.utcnow()

    if user.last_verification_sent_at:
        if now - user.last_verification_sent_at < MIN_WAIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Debes esperar antes de solicitar otro código"
            )

        if now - user.last_verification_sent_at > RESET_WINDOW:
            user.verification_attempts = 0

    if user.verification_attempts >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Has alcanzado el límite de intentos"
        )

    code = create_email_verification(user.id, db)

    user.verification_attempts += 1
    user.last_verification_sent_at = now

    db.commit()

    send_verification_email(email, code)

    return {"message": "Código de verificación enviado"}



@router.post("/logout")
@limiter.limit("2/minute")
async def logout(
    request:Request,
    response: Response, 
    current_user: User = Depends(get_current_user),
    db: Session= Depends(get_db)):
    """Logout - eliminar refresh token"""
    current_user.refresh_token_hash = None
    db.commit()
    response.delete_cookie(key="refresh_token")
    return {"message": "Logout exitoso"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Obtener información del usuario actual
    """
    return current_user


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request:Request,
    payload: ForgotPasswordRequest, 
    db: Session = Depends(get_db)):

    email= payload.email
    user = db.query(User).filter(User.email == email).first()

    # Respuesta genérica por seguridad
    if not user:
        return {"message": "El email no esta registrado, verficar nuevamente"}

    token = create_secure_token(str(user.id))

    user.reset_password_token = hash_code(token)  
    user.reset_password_expires = datetime.utcnow() + timedelta(minutes=30)
    db.commit()

    # 🔥 AQUÍ envías el email
    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    send_reset_email(user.email, reset_link)

    return {"message": "Se ha enviado un correo electrónico para continuar con el proceso"}


from apps.schemas.auth import ResetPasswordRequest

@router.post("/reset-password")
@limiter.limit("3/minute")
async def reset_password(
    request:Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(
        User.reset_password_token == hash_code(payload.token),
        User.reset_password_expires > datetime.utcnow()
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este enlace es inválido o ha expirado"
        )

    user.password_hash = get_password_hash(payload.new_password)
    user.reset_password_token = None
    user.reset_password_expires = None

    db.commit()

    return {"message": "Contraseña actualizada correctamente"}



@router.post("/request-account-deletion")
@limiter.limit("3/minute")
async def request_account_deletion(
    request:Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    token = create_secure_token(str(current_user.id))

    current_user.delete_account_token = hash_code(token)  
    current_user.delete_account_expires = datetime.utcnow() + timedelta(minutes=30)

    db.commit()

    delete_link = f"{FRONTEND_URL}/delete-account?token={token}"

    send_delete_account_email(
        current_user.email,
        delete_link
    )

    return {
        "message": "Se envió un correo para confirmar la eliminación de tu cuenta"
    }


@router.post("/confirm-account-deletion")
@limiter.limit("3/minute")
async def confirm_account_deletion(
    request:Request,
    payload: DeleteAccountRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(
        User.delete_account_token == hash_code(payload.token),
        User.delete_account_expires > datetime.utcnow()
    ).first()

    if not user:
        raise HTTPException(
            status_code=400,
            detail="Enlace inválido o expirado"
        )

    try:
        # Defensa extra: invalidar token antes de borrar
        user.delete_account_token = None
        user.delete_account_expires = None
        #db.flush()

        # Eliminación total (CASCADE hace el resto)
        db.delete(user)
        db.commit()

    except Exception as e:
        db.rollback()
        print("🔥 ERROR REAL AL ELIMINAR CUENTA:", repr(e))
        raise

    # Limpieza de sesión
    response.delete_cookie("refresh_token")

    return {
        "message": "Tu cuenta ha sido eliminada correctamente"
    }
