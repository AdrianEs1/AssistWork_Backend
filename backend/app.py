from fastapi.middleware.cors import CORSMiddleware

from config import lifespan, logger
from apps.api import auth, conversations, agentcontext, oauth, payments, mercadopago_webhook, sse_chat
from config import FRONTEND_URL
import os

from fastapi import FastAPI, Request
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

# Crear limiter
from apps.core.limiter import limiter

app = FastAPI(
    title="Agente IA API",
    description="API para Agente de IA con soporte REST y SSE",
    version="2.0.0",
    lifespan=lifespan
)

# Registrar limiter en app
app.state.limiter = limiter

# Middleware
app.add_middleware(SlowAPIMiddleware)

# 🔥 MUY IMPORTANTE: handler de error
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Demasiadas solicitudes. Intenta más tarde."},
    )


origins = [

    FRONTEND_URL,

]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Cambiar en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(auth.router, prefix="/api")
app.include_router(oauth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(agentcontext.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(mercadopago_webhook.router, prefix="/api")
app.include_router(sse_chat.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "2.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=5000)




