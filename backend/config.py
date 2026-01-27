import os
from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

load_dotenv()

# Logger global
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agente-ia")

# Ciclo de vida de la app (lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Servidor iniciado")
    yield
    logger.info("🛑 Servidor detenido")

FRONTEND_URL= os.getenv("FRONTEND_URL")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")
GROQ_URL = os.getenv("GROQ_URL")


GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
GOOGLE_TOKEN_JSON= os.getenv("GOOGLE_TOKEN_JSON")


DATABASE_URL= os.getenv("DATABASE_URL")



ENCRYPTION_KEY= os.getenv("ENCRYPTION_KEY")

JWT_SECRET_KEY= os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM= os.getenv("JWT_ALGORITHM")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES= os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
JWT_REFRESH_TOKEN_EXPIRE_DAYS= os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS")

COOKIE_SECURE= os.getenv("COOKIE_SECURE", "false").lower() == "true"

GMAIL_SENDER= os.getenv("GMAIL_SENDER")
GMAIL_TOKEN_SUPPORT=os.getenv("GMAIL_TOKEN_SUPPORT")