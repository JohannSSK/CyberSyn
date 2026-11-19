"""Local OCR helper for extracting text from uploaded photos.

Every uploaded image is decoded and OCR-scanned on this machine before any
extracted text enters CyberSyn's local screening pipeline. Images are processed
in memory without writing temporary image files to disk.
"""

import io
import os
import shutil
import subprocess
import threading

MAX_PHOTO_BYTES = int(os.environ.get("CYBERSYN_MAX_PHOTO_BYTES", 10 * 1024 * 1024))
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF"}
NO_TEXT_ERROR = "There's no text to parse in this prompt."

_TESSERACT_TIMEOUT = int(os.environ.get("CYBERSYN_OCR_TIMEOUT", 25))
_tesseract_lang_lock = threading.Lock()
_tesseract_lang = None
_rapidocr_lock = threading.Lock()
_rapidocr_engine = None


class OcrError(Exception):
    """Base error for photo parsing failures."""

    status = 400
    error_code = "ocr_error"


class OcrTooLargeError(OcrError):
    status = 413
    error_code = "photo_too_large"


class OcrInvalidImageError(OcrError):
    status = 400
    error_code = "invalid_photo"


class OcrNoTextError(OcrError):
    status = 400
    error_code = "no_photo_text"


class OcrUnavailableError(OcrError):
    status = 503
    error_code = "ocr_unavailable"


def _normalise_text(raw):
    if not raw:
        return ""
    lines = [line.strip() for line in str(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned = []
    blank = False
    for line in lines:
        if not line:
            if cleaned and not blank:
                cleaned.append("")
            blank = True
        else:
            cleaned.append(line)
            blank = False
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned).strip()


def _decode_png_bytes(raw_bytes):
    if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
        raise OcrInvalidImageError("Please upload a valid PNG, JPEG, WEBP, GIF, BMP, or TIFF photo.")
    if len(raw_bytes) > MAX_PHOTO_BYTES:
        raise OcrTooLargeError(f"Photo exceeds the {MAX_PHOTO_BYTES // (1024 * 1024)} MiB upload limit.")

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise OcrUnavailableError(
            "Photo text parsing is not available on this server. Install the OCR dependencies and try again."
        ) from exc

    prev_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(raw_bytes)) as probe:
            fmt = (probe.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise OcrInvalidImageError("Please upload a valid PNG, JPEG, WEBP, GIF, BMP, or TIFF photo.")
            probe.verify()

        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[3])
                rgb = background
            else:
                rgb = img.convert("RGB")

            out = io.BytesIO()
            rgb.save(out, format="PNG")
            return out.getvalue()
    except OcrError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise OcrInvalidImageError("Please upload a valid PNG, JPEG, WEBP, GIF, BMP, or TIFF photo.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = prev_limit


def _get_tesseract_lang(binary):
    global _tesseract_lang
    with _tesseract_lang_lock:
        if _tesseract_lang is not None:
            return _tesseract_lang
        try:
            proc = subprocess.run(
                [binary, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            langs = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
            if "eng" in langs and "ell" in langs:
                _tesseract_lang = "eng+ell"
            elif "ell" in langs:
                _tesseract_lang = "ell"
            else:
                _tesseract_lang = "eng"
        except Exception:
            _tesseract_lang = "eng"
        return _tesseract_lang


def _tesseract_extract(png_bytes):
    binary = shutil.which("tesseract")
    if not binary:
        return None
    lang = _get_tesseract_lang(binary)
    try:
        proc = subprocess.run(
            [binary, "stdin", "stdout", "-l", lang, "--psm", "6"],
            input=png_bytes,
            capture_output=True,
            timeout=_TESSERACT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return _normalise_text((proc.stdout or b"").decode("utf-8", errors="replace"))


def _get_rapidocr():
    global _rapidocr_engine
    with _rapidocr_lock:
        if _rapidocr_engine is not None:
            return _rapidocr_engine
        try:
            from rapidocr import RapidOCR
            _rapidocr_engine = RapidOCR()
            return _rapidocr_engine
        except ImportError:
            pass
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapidocr_engine = RapidOCR()
            return _rapidocr_engine
        except ImportError:
            return None


def _rapidocr_extract(png_bytes):
    engine = _get_rapidocr()
    if engine is None:
        return None
    with _rapidocr_lock:
        result = engine(png_bytes)
    if result is None:
        return ""
    if hasattr(result, "txts"):
        lines = result.txts or ()
        return _normalise_text("\n".join(str(line) for line in lines if line))
    # rapidocr_onnxruntime returns (items, elapse) where each item is (box, text, score)
    items = result[0] if isinstance(result, tuple) else result
    if not items:
        return ""
    lines = []
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
            lines.append(str(item[1]))
    return _normalise_text("\n".join(lines))


def extract_text(raw_bytes):
    """Extract readable text from image bytes, or raise OcrError."""
    png_bytes = _decode_png_bytes(raw_bytes)

    had_engine = False
    text = _tesseract_extract(png_bytes)
    if text is not None:
        had_engine = True
        if text:
            return text

    rapid = _rapidocr_extract(png_bytes)
    if rapid is not None:
        had_engine = True
        if rapid:
            return rapid

    if not had_engine:
        raise OcrUnavailableError(
            "Photo text parsing is not available on this server. Install the OCR dependencies and try again."
        )
    raise OcrNoTextError(NO_TEXT_ERROR)
