import tempfile
import os
from config import DEEPGRAM_API_KEY
from deepgram import DeepgramClient, PrerecordedOptions
from urllib.parse import quote_plus
import aiohttp, json, asyncio

dg_client = DeepgramClient(DEEPGRAM_API_KEY)


def build_deepgram_url(language="es", sample_rate=16000, keywords=None):
    base = (
        "wss://api.deepgram.com/v1/listen"
        f"?language={language}"
        "&model=nova-2"                   # modelo más preciso en es
        "&punctuate=true&smart_format=true"
        "&encoding=linear16"
        f"&sample_rate={sample_rate}"
        "&interim_results=false"          # solo finales (evita cortes intermedios)
        "&vad_turnoff=2"                  # espera ~2s de silencio antes de cerrar frase
    )
    if keywords:  # lista de (palabra, boost)
        for kw, boost in keywords:
            base += "&keywords=" + quote_plus(f"{kw}:{boost}")
    return base


async def connect_deepgram_stream(client_ws, api_key, on_final_callback, *, sample_rate=16000, keywords=None):
    url = build_deepgram_url(language="es", sample_rate=sample_rate, keywords=keywords)
    headers = {"Authorization": f"Token {api_key}"}

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, headers=headers, heartbeat=20) as dg_ws:
            print("🎙️ Conectado a Deepgram")

            async def send_audio():
                try:
                    while True:
                        msg = await client_ws.receive()  # recibe datos del cliente FastAPI
                        if msg["type"] == "websocket.disconnect":
                            print("⚠️ Cliente desconectado")
                            break

                        if "bytes" in msg and msg["bytes"] is not None:
                            await dg_ws.send_bytes(msg["bytes"])

                finally:
                    # ➕ pequeño “colchón” de silencio para no cortar la última palabra
                    pad_ms = 400
                    await dg_ws.send_bytes(b"\x00" * int(sample_rate * 2 * (pad_ms/1000)))
                    # Cierre “limpio” del stream
                    await dg_ws.send_str(json.dumps({"type": "CloseStream"}))

            async def receive_transcripts():
                async for msg in dg_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if (
                            data.get("type") == "Results"
                            and "channel" in data
                            and "alternatives" in data["channel"]
                            and data["channel"]["alternatives"]
                        ):
                            transcript = data["channel"]["alternatives"][0].get("transcript", "")
                            if transcript and data.get("is_final", False):
                                await on_final_callback(transcript)

            await asyncio.gather(send_audio(), receive_transcripts())



def speech_to_text(file, mimetype="audio/wav", language="es"):
    temp_file_path = None
    
    try:
        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            temp_file_path = tmp.name
            file.seek(0)
            tmp.write(file.read())
        
        print(f"📊 Procesando archivo de {os.path.getsize(temp_file_path)} bytes")
        
        # Opciones mejoradas para Deepgram
        options = PrerecordedOptions(
            model="nova-2",
            language=language,
            punctuate=True,
            smart_format=True,
            # Opciones adicionales para mejor reconocimiento
            diarize=False,  # No necesitamos separar speakers
            utterances=False,  # No necesitamos segmentación
            paragraphs=False,  # No necesitamos párrafos
            # Ajustes de sensibilidad
            profanity_filter=False,
            redact=False,
            # Configuración de encoding
            encoding="linear16",  # Específico para WAV
            sample_rate=16000,  # Frecuencia de muestreo
            channels=1  # Mono
        )
        
        # Transcripción
        with open(temp_file_path, 'rb') as audio_file:
            payload = {"buffer": audio_file}
            response = dg_client.listen.rest.v("1").transcribe_file(
                payload, options, timeout=60
            )
        
        print("DEBUG - Respuesta completa:", response)
        
        # Extraer transcripción
        transcription = response["results"]["channels"][0]["alternatives"][0]["transcript"]
        confidence = response["results"]["channels"][0]["alternatives"][0]["confidence"]
        
        print(f"✅ Transcripción: '{transcription}' (confidence: {confidence})")
        
        # Si la confianza es muy baja, considerar como falla
        if confidence < 0.1:
            print(f"⚠️ Confianza muy baja: {confidence}")
            return ""
        
        return transcription.strip()
    
    except Exception as e:
        print(f"❌ Error en STT: {str(e)}")
        import traceback
        traceback.print_exc()
        return ""
    
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)