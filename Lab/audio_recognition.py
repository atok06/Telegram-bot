import subprocess
from pathlib import Path

import imageio_ffmpeg
import speech_recognition as sr


SPEECH_LANGUAGE_MAP = {
    "ru": "ru-RU",
    "rus": "ru-RU",
    "en": "en-US",
    "eng": "en-US",
    "tr": "tr-TR",
    "tur": "tr-TR",
    "kk": "kk-KZ",
    "kaz": "kk-KZ",
}


class AudioRecognitionError(RuntimeError):
    ...


def resolve_speech_language(language: str | None) -> str:
    return SPEECH_LANGUAGE_MAP.get(language.strip(), language.strip()) if language else "ru-RU"


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]
    if subprocess.run(command, capture_output=True, text=True).returncode != 0:
        raise AudioRecognitionError("Аудио форматын WAV-қа айналдыру мүмкін болмады.")


def transcribe_audio_file(file_path: str, language: str | None = None) -> str:
    input_path = Path(file_path)
    if not input_path.exists():
        raise AudioRecognitionError("Аудио файл табылмады.")

    wav_path = input_path.with_suffix(".wav")
    try:
        _convert_to_wav(input_path, wav_path)
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(wav_path)) as source:
            transcript = recognizer.recognize_google(
                recognizer.record(source),
                language=resolve_speech_language(language),
            ).strip()
        if not transcript:
            raise AudioRecognitionError("Аудиодан мәтін алынбады.")
        return transcript
    except sr.UnknownValueError as exc:
        raise AudioRecognitionError("Аудиодағы сөз анық естілмеді.") from exc
    except sr.RequestError as exc:
        raise AudioRecognitionError("Дыбысты тану сервисіне қосылу мүмкін болмады.") from exc
    finally:
        if wav_path.exists():
            wav_path.unlink()
