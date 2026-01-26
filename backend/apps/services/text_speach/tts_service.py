from gtts import gTTS
import tempfile

def text_to_speech(text, lang="es"):
    """
    Convierte texto a voz usando gTTS.
    Retorna la ruta del archivo MP3.
    """
    tts = gTTS(text=text, lang=lang)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tts.save(tmp_file.name)
    return tmp_file.name