from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from apps.models.email_verification import EmailVerification
from apps.core.security import generate_otp
from apps.core.security import hash_code
from apps.models.user import User

VERIFICATION_EXP_MINUTES = 10
MAX_ATTEMPTS = 5


def create_email_verification(user_id, db: Session) -> str:
    # ❌ invalidar códigos previos
    db.query(EmailVerification).filter(
        EmailVerification.user_id == user_id,
        EmailVerification.used == False
    ).update({ "used": True })

    # 🔢 generar código
    code = generate_otp()

    record = EmailVerification(
        user_id=user_id,
        code_hash=hash_code(code),
        expires_at=datetime.utcnow() + timedelta(minutes=VERIFICATION_EXP_MINUTES),
        attempts=0,
        used=False
    )

    db.add(record)
    db.commit()

    return code  # ⚠️ solo se retorna para enviar por email


def verify_email_code(email: str, code: str, db: Session):
    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=400,
            detail="Código inválido o expirado"
        )

    verification = db.query(EmailVerification).filter(
        EmailVerification.user_id == user.id,
        EmailVerification.used == False
    ).order_by(
        EmailVerification.created_at.desc()
    ).first()

    if not verification:
        raise HTTPException(
            status_code=400,
            detail="Código inválido o expirado"
        )

    if verification.expires_at < datetime.utcnow():
        verification.used = True
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Código inválido o expirado"
        )

    if verification.attempts >= MAX_ATTEMPTS:
        verification.used = True
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Código inválido o expirado"
        )

    verification.attempts += 1

    if verification.code_hash != hash_code(code):
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Código inválido o expirado"
        )

    # ✅ éxito
    verification.used = True
    user.is_verified = True

    db.commit()

    return True

