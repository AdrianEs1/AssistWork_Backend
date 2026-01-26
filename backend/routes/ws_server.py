import json 
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from config import DEEPGRAM_API_KEY

# Servicios
from apps.services.text_speach.stt_service import connect_deepgram_stream
from apps.services.text_speach.tts_service import text_to_speech
from apps.services.memory.qdrant_service import store_message, search_context
from apps.services.orchestrator.orchestrator_service import orchestrator

router = APIRouter()

@router.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket):
    await websocket.accept()
    print("🔌 Cliente conectado")

    async def process_final_transcript(transcript: str):
        print(f"📝 Final recibido: {transcript}")
        try:
            # 1. Buscar contexto en memoria
            context_list = search_context(transcript)
            context_text = "\n".join(context_list)

            # 2. Pasar al orquestador
            result = await orchestrator(transcript, context=context_text)

            # 3. Guardar en memoria
            store_message(transcript, metadata={"role": "user"})
            store_message(str(result), metadata={"role": "assistant"})

            # 4. Generar voz con TTS
            audio_path = await text_to_speech(str(result), lang="es")

            # 5. Enviar JSON con transcripción y respuesta
            await websocket.send_text(json.dumps({
                "transcript": transcript,
                "response": str(result)
            }))

            # 6. Mandar audio generado (bytes)
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
                await websocket.send_bytes(audio_bytes)

        except RuntimeError:
            print("⚠️ Cliente desconectado antes de enviar la transcripción")

    try:
        await connect_deepgram_stream(websocket, DEEPGRAM_API_KEY, process_final_transcript)
    except WebSocketDisconnect:
        print("⚠️ Cliente desconectado")
    except Exception as e:
        print(f"❌ Error en conexión con Deepgram: {e}")
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
        except:
            pass
