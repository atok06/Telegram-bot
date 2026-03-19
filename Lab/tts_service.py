from gtts import gTTS


DEFAULT_TTS_LANGUAGE = "ru"


def generate_speech(text: str, out_file: str, language: str = DEFAULT_TTS_LANGUAGE) -> None:
    if not text.strip():
        return

    gTTS(text=text, lang=language).save(out_file)
