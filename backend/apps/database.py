from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from config import DATABASE_URL



# Engine con configuración para Supabase
engine = create_engine(
    DATABASE_URL,
    pool_size=5,              # Supabase free tier: max 60 conexiones totales
    max_overflow=10,
    pool_pre_ping=True,       # Verifica conexión antes de usar
    pool_recycle=3600,         # Recicla cada 5 minutos (Supabase cierra inactivas)
    echo=False,
    connect_args={
        "sslmode": "require",  # SSL obligatorio en Supabase
        "connect_timeout": 10
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()