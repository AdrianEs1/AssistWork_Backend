from apps.api import oauth
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import lifespan, logger
from apps.api import auth, call_model, conversations, ws_chat, agentcontext

app = FastAPI(
    title="Agente IA API",
    description="API para Agente de IA con soporte REST y WebSocket",
    version="2.0.0",
    lifespan=lifespan
)

origins = [

    "http://localhost:5173",
    "https://assistwork.vercel.app/" #AQUI SE MODIFICA POR LA URL EN PRODUCCION


]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Cambiar en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(call_model.router)
#app.include_router(ws_server.router)
app.include_router(ws_chat.router)  # ✨ NUEVO
app.include_router(auth.router, prefix="/api")
app.include_router(oauth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(agentcontext.router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "2.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=5000)




