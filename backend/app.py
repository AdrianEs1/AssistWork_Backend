from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import lifespan, logger
from apps.api import auth, conversations, agentcontext, oauth, payments, mercadopago_webhook, sse_chat
from config import FRONTEND_URL
import os



app = FastAPI(
    title="Agente IA API",
    description="API para Agente de IA con soporte REST y SSE",
    version="2.0.0",
    lifespan=lifespan
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




