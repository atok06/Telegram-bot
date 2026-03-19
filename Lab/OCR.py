"""OCR and text-to-speech utilities used by the Telegram handlers."""

import importlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytesseract
from gtts import gTTS
from PIL import Image, ImageFilter, ImageOps
from pytesseract import Output


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OCR_LANGUAGE = "rus"
DEFAULT_TTS_LANGUAGE = "ru"

EASYOCR_LANGUAGE_MAP = {
    "eng": (("en",),),
    "en": (("en",),),
    "rus": (("ru", "en"), ("en",)),
    "ru": (("ru", "en"), ("en",)),
    "tur": (("tr", "en"), ("en",)),
    "tr": (("tr", "en"), ("en",)),
}

TESSERACT_LANGUAGE_MAP = {
    "eng": ("eng",),
    "en": ("eng",),
    "rus": ("rus+eng", "eng", "rus"),
    "ru": ("rus+eng", "eng", "rus"),
    "tur": ("tur+eng", "eng", "tur"),
    "tr": ("tur+eng", "eng", "tur"),
}

_EASYOCR_IMPORT_ATTEMPTED = False
_EASYOCR_MODULE: Any | None = None
_EASYOCR_READERS: dict[tuple[str, ...], Any | None] = {}


class OCRSetupError(RuntimeError):
    """Raised when the local Tesseract runtime is missing or misconfigured."""


class OCRLanguageError(RuntimeError):
    """Raised when the requested OCR language pack is not installed."""


@dataclass(slots=True)
class OCRCandidate:
    """One OCR result candidate from a specific engine."""

    engine: str
    text: str
    confidence: float
    language_hint: str = ""


def _find_tesseract() -> str:
    """Locate the Tesseract executable from env vars, PATH, or common install paths."""
    env_path = os.getenv("TESSERACT_CMD", "").strip()
    candidates = [
        env_path,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)

    raise OCRSetupError(
        "Tesseract OCR табылмады. Tesseract орнатып, PATH-қа қосыңыз "
        "немесе TESSERACT_CMD айнымалысын көрсетіңіз."
    )


def _configure_tesseract() -> str:
    """Tell pytesseract which executable should be launched."""
    tesseract_cmd = _find_tesseract()
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    return tesseract_cmd


def _find_tessdata_dir(tesseract_cmd: str) -> Path:
    """Find the tessdata directory that contains trained language files."""
    env_dir = os.getenv("TESSDATA_DIR", "").strip()
    candidates = [
        Path(env_dir) if env_dir else None,
        BASE_DIR / "tessdata",
        Path(tesseract_cmd).parent / "tessdata",
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
    ]

    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate

    raise OCRSetupError(
        "tessdata папкасы табылмады. Lab/tessdata ішіне traineddata файлдарын қосыңыз "
        "немесе TESSDATA_DIR айнымалысын көрсетіңіз."
    )


def _ensure_language_installed(tessdata_dir: Path, language: str) -> None:
    """Check that the requested OCR language is actually available."""
    os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    available_languages = set(pytesseract.get_languages(config=""))
    if language not in available_languages:
        installed = ", ".join(sorted(available_languages)) or "жоқ"
        raise OCRLanguageError(
            f"'{language}' тілі Tesseract ішінде жоқ. Орнатылған тілдер: {installed}"
        )


def _prepare_image_variants(filepath: str) -> list[Image.Image]:
    """Build several image variants and let OCR pick the best result."""
    with Image.open(filepath) as source_image:
        image = ImageOps.exif_transpose(source_image).convert("RGB")

    grayscale = ImageOps.autocontrast(ImageOps.grayscale(image))
    scaled = grayscale.resize(
        (max(1, grayscale.width * 2), max(1, grayscale.height * 2)),
        Image.LANCZOS,
    )
    sharpened = scaled.filter(ImageFilter.SHARPEN)
    denoised = sharpened.filter(ImageFilter.MedianFilter(size=3))
    threshold_light = denoised.point(lambda pixel: 255 if pixel > 170 else 0, mode="L")
    threshold_dark = denoised.point(lambda pixel: 255 if pixel > 130 else 0, mode="L")
    inverted = ImageOps.invert(denoised)

    return [
        grayscale,
        scaled,
        sharpened,
        denoised,
        threshold_light,
        threshold_dark,
        inverted,
    ]


def _clean_ocr_text(parts: list[str]) -> str:
    """Join OCR tokens into a readable text block."""
    return " ".join(part.strip() for part in parts if part and part.strip()).strip()


def _run_tesseract_candidate(
    image: Image.Image,
    language: str,
    tessdata_dir: Path,
    psm: int,
) -> OCRCandidate | None:
    """Run one Tesseract OCR attempt and return a scored candidate."""
    os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    config = f"--oem 3 --psm {psm}"
    data = pytesseract.image_to_data(image, lang=language, config=config, output_type=Output.DICT)

    parts: list[str] = []
    confidences: list[float] = []

    for token, confidence in zip(data.get("text", []), data.get("conf", [])):
        token = (token or "").strip()
        if not token:
            continue

        parts.append(token)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            continue

        if confidence_value >= 0:
            confidences.append(confidence_value)

    text = _clean_ocr_text(parts)
    if not text:
        return None

    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return OCRCandidate(
        engine="tesseract",
        text=text,
        confidence=average_confidence,
        language_hint=language,
    )


def _get_easyocr_module() -> Any | None:
    """Lazy-load EasyOCR so the bot still works without the extra dependency."""
    global _EASYOCR_IMPORT_ATTEMPTED, _EASYOCR_MODULE

    if _EASYOCR_IMPORT_ATTEMPTED:
        return _EASYOCR_MODULE

    _EASYOCR_IMPORT_ATTEMPTED = True
    try:
        _EASYOCR_MODULE = importlib.import_module("easyocr")
    except ImportError:
        _EASYOCR_MODULE = None

    return _EASYOCR_MODULE


def _resolve_tesseract_languages(language: str) -> tuple[str, ...]:
    """Map the bot's OCR language code to one or more Tesseract language specs."""
    normalized = (language or "").strip().lower()
    return TESSERACT_LANGUAGE_MAP.get(normalized, (language,))


def _resolve_easyocr_languages(language: str) -> tuple[tuple[str, ...], ...]:
    """Map the bot's OCR language code to one or more EasyOCR language combos."""
    normalized = (language or "").strip().lower()
    return EASYOCR_LANGUAGE_MAP.get(normalized, ())


def _get_easyocr_reader(languages: tuple[str, ...]) -> Any | None:
    """Create and cache one EasyOCR reader per language combination."""
    if not languages:
        return None

    if languages in _EASYOCR_READERS:
        return _EASYOCR_READERS[languages]

    easyocr_module = _get_easyocr_module()
    if easyocr_module is None:
        _EASYOCR_READERS[languages] = None
        return None

    try:
        reader = easyocr_module.Reader(list(languages), gpu=False)
    except Exception as exc:
        logger.warning("EasyOCR reader init failed for %s: %s", languages, exc)
        reader = None

    _EASYOCR_READERS[languages] = reader
    return reader


def _run_easyocr_candidates(filepath: str, language: str) -> list[OCRCandidate]:
    """Run one or more EasyOCR readers as handwriting-oriented fallback candidates."""
    candidates: list[OCRCandidate] = []
    for languages in _resolve_easyocr_languages(language):
        reader = _get_easyocr_reader(languages)
        if reader is None:
            continue

        try:
            results = reader.readtext(
                filepath,
                detail=1,
                paragraph=True,
                decoder="greedy",
                min_size=5,
                contrast_ths=0.05,
                adjust_contrast=0.7,
                rotation_info=[90, 180, 270],
                canvas_size=2560,
                mag_ratio=1.5,
            )
        except Exception as exc:
            logger.warning("EasyOCR read failed for %s: %s", languages, exc)
            continue

        parts: list[str] = []
        confidences: list[float] = []
        for item in results:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue

            text = item[1]
            confidence = item[2]
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())

            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                continue

            if confidence_value >= 0:
                confidences.append(confidence_value * 100.0)

        text = "\n".join(parts).strip()
        if not text:
            continue

        average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        candidates.append(
            OCRCandidate(
                engine="easyocr",
                text=text,
                confidence=average_confidence,
                language_hint="+".join(languages),
            )
        )

    return candidates


def _script_counts(text: str) -> tuple[int, int]:
    """Count Latin and Cyrillic letters in a string."""
    latin = 0
    cyrillic = 0
    for char in text:
        if ("A" <= char <= "Z") or ("a" <= char <= "z"):
            latin += 1
        elif "\u0400" <= char <= "\u04FF":
            cyrillic += 1
    return latin, cyrillic


def _is_short_latin_word(text: str) -> bool:
    """Detect short Latin-only words such as names or transliterated Kazakh words."""
    normalized = text.strip()
    if not normalized or len(normalized.split()) > 3:
        return False

    latin_count, cyrillic_count = _script_counts(normalized)
    return latin_count >= 3 and cyrillic_count == 0


def _score_candidate(candidate: OCRCandidate) -> float:
    """Score OCR candidates by confidence and text richness."""
    alnum_count = sum(character.isalnum() for character in candidate.text)
    word_count = len(candidate.text.split())
    looks_too_short = alnum_count <= 3
    engine_bonus = 6.0 if candidate.engine == "easyocr" else 0.0
    short_penalty = 10.0 if looks_too_short else 0.0
    latin_bonus = 8.0 if _is_short_latin_word(candidate.text) else 0.0

    return (
        candidate.confidence
        + min(alnum_count, 160) * 0.35
        + min(word_count, 32) * 1.5
        + engine_bonus
        + latin_bonus
        - short_penalty
    )


def _choose_best_candidate(candidates: list[OCRCandidate], requested_language: str) -> OCRCandidate:
    """Prefer Latin short words when they closely compete with Cyrillic guesses."""
    scored_candidates = [(candidate, _score_candidate(candidate)) for candidate in candidates]
    best_candidate, best_score = max(scored_candidates, key=lambda item: item[1])

    if (requested_language or "").strip().lower() in {"eng", "en"}:
        return best_candidate

    latin_candidates = [
        (candidate, score)
        for candidate, score in scored_candidates
        if _is_short_latin_word(candidate.text)
    ]
    if not latin_candidates:
        return best_candidate

    best_latin_candidate, best_latin_score = max(latin_candidates, key=lambda item: item[1])
    _, best_cyrillic_count = _script_counts(best_candidate.text)
    if best_cyrillic_count > 0 and best_latin_score >= best_score - 12.0:
        return best_latin_candidate

    return best_candidate


def text_find(filepath: str, language: str = DEFAULT_OCR_LANGUAGE) -> str:
    """Recognize text from an image file using Tesseract plus EasyOCR fallback."""
    tesseract_cmd = _configure_tesseract()
    tessdata_dir = _find_tessdata_dir(tesseract_cmd)
    _ensure_language_installed(tessdata_dir, language)

    candidates: list[OCRCandidate] = []
    image_variants = _prepare_image_variants(filepath)

    try:
        for image in image_variants:
            for language_spec in _resolve_tesseract_languages(language):
                for psm in (6, 11, 4, 7):
                    candidate = _run_tesseract_candidate(image, language_spec, tessdata_dir, psm)
                    if candidate is not None:
                        candidates.append(candidate)
    finally:
        for image in image_variants:
            image.close()

    candidates.extend(_run_easyocr_candidates(filepath, language))

    if not candidates:
        return ""

    best_candidate = _choose_best_candidate(candidates, language)
    logger.info(
        "OCR selected %s (%s) result with confidence %.2f",
        best_candidate.engine,
        best_candidate.language_hint or language,
        best_candidate.confidence,
    )
    return best_candidate.text.strip()


def generate(text: str, out_file: str, language: str = DEFAULT_TTS_LANGUAGE) -> None:
    """Generate an MP3 audio file from recognized or translated text."""
    if not text.strip():
        return

    tts = gTTS(text, lang=language)
    tts.save(out_file)
