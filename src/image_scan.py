"""Photo screening: find personal data inside an image and cover it.

The text gate screens prompts; this module screens pictures. A photo of an
ID card, a contract or a whiteboard can carry the same data the text gate
stops — faces, tax numbers, phones, IBANs — so it gets the same treatment
before anyone pastes it into an AI tool.

Pipeline, all in memory, all on this machine:

    decode bytes -> find faces -> OCR with word boxes -> PII rules over the
    recognised text -> map every hit back to its pixels -> blur those pixels

The uploaded bytes are never written to disk and the scan result carries a
redacted copy, so what the user keeps is already safe.

Engines are loaded lazily and each is optional: if EasyOCR or the face
detector cannot start (a missing wheel, a model that never downloaded), the
other still runs and the verdict says what was not covered. If nothing can
run at all the scan is refused outright — a broken gate is never an open
gate.
"""

import base64
import io
import re
import sys
import threading
import time

import cv2
import numpy as np

# --------------------------------------------------------------------------
# Limits. Photos from phones are a few MB; anything larger is almost always
# a mistake or an attempt to exhaust the scanner, and OCR would be slow on
# it anyway. Images are downscaled to MAX_DIM on the long edge: plenty for
# OCR, kind to the 2-core box this runs on.
# --------------------------------------------------------------------------
MAX_BYTES = 12 * 1024 * 1024
MAX_DIM = 1600
MIN_FACE_CONFIDENCE = 0.80

_lock = threading.Lock()  # one scan at a time: OCR is RAM-hungry
_ocr_engine = None        # ("easyocr" | "rapidocr" | "none", reader)
_ocr_error = None
_face_detectors = None


# --------------------------------------------------------------------------
# PII rules. The patterns mirror the text gate (MLscripts/greek_pii.py) and
# extend it with what actually appears inside photos of documents: IBANs,
# payment cards, ID-card numbers, plates, and the labelled fields Greek
# documents carry ("ΕΠΩΝΥΜΟ", "ΟΝΟΜΑ", ...). OCR misreads are expected, so
# every rule tolerates the classic 0/O, 1/I swaps inside numeric spans.
# --------------------------------------------------------------------------

def _digit_class(pattern_digits):
    """A regex fragment matching a digit or its usual OCR lookalikes."""
    return r"[0-9OIlZS]"


GREEK_LETTERS = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
LATIN_LETTERS = "ABGDEZHIKLMNOPRSTYX"  # visual homoglyphs of the Greek set

LINE_PATTERNS = [
    # Digits-only neighbours: OCR frequently glues words together, so the
    # numeric rules anchor on "not a digit" instead of \b.
    ("EMAIL", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.95),
    ("CREDIT_CARD", re.compile(
        r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), 0.90),
    ("GREEK_AMKA", re.compile(
        r"(?<!\d)(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])\d{7}(?!\d)"), 0.95),
    ("GREEK_AFM", re.compile(
        r"(?<!\d)\d{9}(?!\d)"), 0.90),
    ("GREEK_PHONE", re.compile(
        r"(?<!\d)(?:\+30[\s.-]?)?(?:69\d{8}|2\d{9})(?!\d)"), 0.90),
    ("GREEK_PHONE", re.compile(
        r"(?<!\d)(?:69\d|2\d\d)[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"), 0.85),
    ("GREEK_ID", re.compile(
        r"(?<![A-ZΑ-Ω])[Α-ΩA-Z]{2}[\s.-]?\d{6}(?!\d)"), 0.80),
    ("LICENSE_PLATE", re.compile(
        r"(?<![A-ZΑ-Ω0-9])[A-ZΑΒΕΖΗΙΚΜΝΟΡΤΥΧ]{3}[\s.-]?\d{4}(?!\d)"), 0.70),
]

# IBAN: found as a candidate, then proven with the ISO 13616 mod-97 check —
# the only reliable way once OCR has stripped the grouping spaces.
IBAN_CANDIDATE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
IBAN_SPACED = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[\s.\-][A-Z0-9]{4}){2,6}(?:[\s.\-][A-Z0-9]{1,4})?\b")
IBAN_LENGTHS = {  # country -> total length, the common European ones
    "GR": 27, "DE": 22, "FR": 27, "IT": 27, "ES": 24, "PT": 25, "NL": 18,
    "BE": 16, "AT": 20, "CY": 28, "MT": 31, "IE": 22, "LU": 20, "FI": 18,
    "GB": 22, "CH": 21, "PL": 28, "CZ": 24, "SK": 24, "HU": 28, "RO": 24,
    "BG": 22, "HR": 21, "SI": 19, "EE": 20, "LV": 21, "LT": 20, "SE": 24,
    "DK": 18, "NO": 15, "IS": 26,
}


def _iban_ok(compact):
    if len(compact) < 15 or len(compact) > 34:
        return False
    if IBAN_LENGTHS.get(compact[:2], len(compact)) != len(compact):
        return False
    rearranged = compact[4:] + compact[:4]
    try:
        digits = "".join(str(int(c, 36)) for c in rearranged)
    except ValueError:
        return False
    remainder = 0
    for ch in digits:
        remainder = (remainder * 10 + int(ch)) % 97
    return remainder == 1

# Labels whose value on the same line (or the next) is personal data even
# when no regex recognises it — names, addresses, birth places on Greek
# IDs, passports, contracts and forms. Values are redacted, not the label,
# so the document stays readable. Spaces inside a label are matched as
# "maybe there": OCR often glues words together ("DELIVERTO:").
SENSITIVE_LABELS = [
    "ΕΠΩΝΥΜΟ", "ΕΠΙΘΕΤΟ", "ΟΝΟΜΑ", "ΠΑΤΡΩΝΥΜΟ", "ΜΗΤΡΩΝΥΜΟ",
    "ΔΙΕΥΘΥΝΣΙΣ", "ΚΑΤΟΙΚΙΑ", "ΓΕΝΝΗΘΕΙΣ", "ΕΠΑΓΓΕΛΜΑ",
    "ΠΑΡΑΛΗΠΤΗΣ", "ΠΕΛΑΤΗΣ", "ΥΠΟΓΡΑΦΗ",
    "SURNAME", "GIVEN NAME", "NAME", "ADDRESS", "BIRTH", "FATHER",
    "MOTHER", "PROFESSION", "SIGNATURE", "DELIVER TO", "RECIPIENT",
    "ATTN", "CUSTOMER",
]

SENSITIVE_LABEL_RES = [
    (label, re.compile(re.escape(label).replace("\\ ", r"\s*") + r"\s*[:：.]?\s*",
                       re.IGNORECASE))
    for label in SENSITIVE_LABELS
]

KIND_LABELS = {
    "FACE": ("Face", "Πρόσωπο"),
    "GREEK_AFM": ("Tax number (ΑΦΜ)", "ΑΦΜ"),
    "GREEK_AMKA": ("Social security (ΑΜΚΑ)", "ΑΜΚΑ"),
    "GREEK_PHONE": ("Phone number", "Τηλέφωνο"),
    "EMAIL": ("Email address", "Email"),
    "IBAN": ("IBAN", "IBAN"),
    "CREDIT_CARD": ("Payment card", "Κάρτα πληρωμής"),
    "GREEK_ID": ("ID card number", "Αρ. ταυτότητας"),
    "LICENSE_PLATE": ("License plate", "Πινακίδα"),
    "DOC_FIELD": ("Document field", "Πεδίο εγγράφου"),
}


# --------------------------------------------------------------------------
# Image loading
# --------------------------------------------------------------------------

class ImageTooLarge(Exception):
    pass


class NotAnImage(Exception):
    pass


def decode(data_url_or_b64):
    """Turn the browser's data URL (or bare base64) into a BGR array."""
    text = data_url_or_b64.strip()
    if "," in text and text[:64].lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        raw = base64.b64decode(text, validate=False)
    except Exception:
        raise NotAnImage("The upload is not valid base64 image data.")
    if len(raw) > MAX_BYTES:
        raise ImageTooLarge(
            f"The image is {len(raw) // (1024 * 1024)} MB; the limit is "
            f"{MAX_BYTES // (1024 * 1024)} MB."
        )
    buf = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise NotAnImage("Only JPEG, PNG, WebP and BMP images can be scanned.")
    h, w = img.shape[:2]
    if max(h, w) > MAX_DIM:
        scale = MAX_DIM / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    return img


def encode_jpeg(img, quality=90):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Could not encode the redacted image.")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


# --------------------------------------------------------------------------
# Faces. Primary: MTCNN (facenet-pytorch, weights ship with the wheel).
# Fallback: OpenCV Haar cascades, which need no download at all. Either way
# boxes come back padded — a chin-to-forehead crop misses hair and ears.
# --------------------------------------------------------------------------

def _init_face_detectors():
    global _face_detectors
    detectors = []
    try:
        from facenet_pytorch import MTCNN
        detectors.append(("mtcnn", MTCNN(
            keep_all=True, post_process=False, min_face_size=40,
            thresholds=[0.6, 0.7, 0.8],
        )))
    except Exception as exc:
        print(f"image_scan: MTCNN unavailable ({exc}); falling back to Haar",
              file=sys.stderr)
    cascades = []
    base = cv2.data.haarcascades
    for name in ("haarcascade_frontalface_default.xml",
                 "haarcascade_frontalface_alt2.xml"):
        clf = cv2.CascadeClassifier(base + name)
        if not clf.empty():
            cascades.append(clf)
    if cascades:
        detectors.append(("haar", cascades))
    _face_detectors = detectors


def _pad_box(x, y, w, h, iw, ih, frac=0.25):
    px, py = int(w * frac), int(h * frac * 1.3)
    x0 = max(0, x - px)
    y0 = max(0, y - py)
    x1 = min(iw, x + w + px)
    y1 = min(ih, y + h + py)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def _merge_boxes(boxes, iou_gap=0.35):
    """Union-find merge of overlapping boxes so one face yields one box."""
    boxes = [list(b) for b in boxes]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ax, ay, aw, ah = boxes[i]
                bx, by, bw, bh = boxes[j]
                ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                iy = max(0, min(ay + ah, by + bh) - max(ay, by))
                inter = ix * iy
                smaller = min(aw * ah, bw * bh)
                if smaller and inter / smaller > iou_gap:
                    x0, y0 = min(ax, bx), min(ay, by)
                    x1 = max(ax + aw, bx + bw)
                    y1 = max(ay + ah, by + bh)
                    boxes[i] = [x0, y0, x1 - x0, y1 - y0]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


def detect_faces(img):
    """Return ([boxes], engine_name). Boxes are [x, y, w, h] padded."""
    if _face_detectors is None:
        _init_face_detectors()
    ih, iw = img.shape[:2]
    for name, engine in _face_detectors:
        try:
            if name == "mtcnn":
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                boxes, probs = engine.detect(rgb)
                if boxes is None:
                    continue
                out = []
                for (x0, y0, x1, y1), p in zip(boxes, probs):
                    if p is None or p < MIN_FACE_CONFIDENCE:
                        continue
                    out.append(_pad_box(int(x0), int(y0),
                                        int(x1 - x0), int(y1 - y0), iw, ih))
                if out or len(_face_detectors) == 1:
                    return _merge_boxes(out), name
            else:  # haar
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)
                found = []
                for clf in engine:
                    for (x, y, w, h) in clf.detectMultiScale(
                            gray, scaleFactor=1.1, minNeighbors=6,
                            minSize=(48, 48)):
                        found.append(_pad_box(int(x), int(y), int(w), int(h),
                                              iw, ih))
                return _merge_boxes(found), name
        except Exception:
            continue
    return [], "none"


# --------------------------------------------------------------------------
# OCR. Two engines, one job:
#
# * EasyOCR reads Latin text from photos well and can fetch extra language
#   models where the network allows it — preferred when it can start.
# * RapidOCR ships its detection/recognition models inside the wheel, so it
#   works on a fully offline machine — the guaranteed baseline.
#
# Either way the output is normalised to easyocr's (quad, text, conf) shape.
# Greek-script OCR needs a Greek model, which neither engine bundles; the
# structured identifiers this gate cares about (ΑΦΜ, ΑΜΚΑ, phones, IBANs,
# cards, plates) are digits and Latin letters, which both engines read.
# --------------------------------------------------------------------------

def _init_ocr():
    global _ocr_engine, _ocr_error
    if _ocr_engine is not None:
        return
    try:
        import easyocr
        _ocr_engine = ("easyocr", easyocr.Reader(["en"], gpu=False,
                                                 verbose=False))
        return
    except Exception as exc:
        print(f"image_scan: EasyOCR unavailable ({type(exc).__name__}: {exc});"
              " trying RapidOCR", file=sys.stderr)
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = ("rapidocr", RapidOCR())
    except Exception as exc:
        _ocr_engine = ("none", None)
        _ocr_error = f"{type(exc).__name__}: {exc}"


def ocr_words(img):
    """Run OCR, returning (words, error). words = [{text, box, conf}]."""
    _init_ocr()
    name, engine = _ocr_engine
    if engine is None:
        return [], _ocr_error
    try:
        if name == "easyocr":
            raw = engine.readtext(img, detail=1, paragraph=False)
        else:
            result, _elapsed = engine(img)
            raw = result or []
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    words = []
    for quad, text, conf in raw:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        words.append({
            "text": text,
            "conf": float(conf),
            "box": [x0, y0, max(1, x1 - x0), max(1, y1 - y0)],
        })
    return words, None


# --------------------------------------------------------------------------
# Mapping text matches back to pixels. OCR gives words; the patterns work
# on lines (phones and IBANs span several words), so words are grouped into
# lines, each line becomes a string with a char-offset -> word index map,
# and a match redacts the union of the word boxes it touches.
# --------------------------------------------------------------------------

def _group_lines(words, y_tol=0.6):
    """Group word boxes into reading lines by vertical overlap."""
    items = sorted(words, key=lambda w: (w["box"][1], w["box"][0]))
    lines = []
    for w in items:
        cy = w["box"][1] + w["box"][3] / 2
        placed = False
        for line in lines:
            if abs(cy - line["cy"]) <= max(10, line["h"] * y_tol):
                line["words"].append(w)
                n = len(line["words"])
                line["cy"] = (line["cy"] * (n - 1) + cy) / n
                line["h"] = max(line["h"], w["box"][3])
                placed = True
                break
        if not placed:
            lines.append({"cy": cy, "h": w["box"][3], "words": [w]})
    for line in lines:
        line["words"].sort(key=lambda w: w["box"][0])
    lines.sort(key=lambda l: l["cy"])
    return lines


def _line_string(line):
    """Join a line's words, remembering which word covers each character."""
    parts, spans, cursor = [], [], 0
    for w in line["words"]:
        if parts:
            cursor += 1
        parts.append(w["text"])
        spans.append((cursor, cursor + len(w["text"])))
        cursor += len(w["text"])
    return " ".join(parts), spans


def _boxes_for_span(spans, start, end):
    """Boxes for the char range [start, end), clipped proportionally.

    OCR regularly glues a whole line into one "word", so containment alone
    is not enough: a match that starts mid-word still owns the right-hand
    slice of that word's box. Characters are treated as equal width — good
    enough for the digits and capitals these rules match.
    """
    out = []
    for (s, e, box) in spans:
        if e <= start or s >= end:
            continue
        x, y, w, h = box
        n = max(1, e - s)
        char_w = w / n
        # The box maps OCR's compact text; the printed original may carry
        # spaces the OCR dropped, so a clipped slice can land a character
        # off. One spare character each side absorbs that drift.
        x0 = x + int((max(s, start) - s) * char_w - char_w)
        x1 = x + int((min(e, end) - s) * char_w + char_w)
        out.append([x0, y, max(1, x1 - x0), h])
    return out


def _normalise_digits(text):
    """Map OCR lookalikes back to digits so checksums stand a chance."""
    return (text.replace("O", "0").replace("o", "0").replace("I", "1")
                .replace("l", "1").replace("S", "5").replace("Z", "2"))


def _luhn_ok(digits):
    if not (13 <= len(digits) <= 19):
        return False
    total, double = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d = d * 2 if d < 5 else d * 2 - 9
        total += d
        double = not double
    return total % 10 == 0


def _afm_ok(digits):
    if digits == "0" * 9:
        return False
    total = sum(int(digits[i]) * (2 ** (8 - i)) for i in range(8))
    return (total % 11) % 10 == int(digits[8])


def _mask(text, keep=2):
    """'6981234567' -> '69*****67' — enough to recognise, never to reuse."""
    text = text.strip()
    if len(text) <= keep * 2:
        return "*" * len(text)
    return text[:keep] + "*" * (len(text) - keep * 2) + text[-keep:]


def scan_text(words, img_shape):
    """Run the PII rules over OCR output. Returns a list of findings."""
    ih, iw = img_shape[:2]
    lines = _group_lines(words)
    findings = []
    seen_boxes = []

    def add(kind, score, snippet, boxes):
        for b in boxes:
            b[0] = max(0, min(iw - 1, b[0]))
            b[1] = max(0, min(ih - 1, b[1]))
            b[2] = max(1, min(iw - b[0], b[2]))
            b[3] = max(1, min(ih - b[1], b[3]))
        key = (kind, tuple(boxes[0]))
        if any(kind == k and abs(boxes[0][0] - kb[0]) < 8
               and abs(boxes[0][1] - kb[1]) < 8 for k, kb in seen_boxes):
            return
        seen_boxes.append(key)
        findings.append({
            "kind": kind,
            "score": score,
            "detail": _mask(snippet),
            "boxes": boxes,
        })

    line_records = []
    for line in lines:
        text, spans = _line_string(line)
        spans = [(s, e, w["box"]) for (s, e), w in zip(spans, line["words"])]
        line_records.append((text, spans, line))

    for idx, (text, spans, line) in enumerate(line_records):
        upper = text.upper()
        normalised = _normalise_digits(text)

        for kind, pattern, score in LINE_PATTERNS:
            for m in pattern.finditer(normalised if kind in
                                      ("GREEK_AFM", "CREDIT_CARD") else text):
                val = m.group()
                digits = re.sub(r"\D", "", _normalise_digits(val))
                if kind == "GREEK_AFM" and not _afm_ok(digits):
                    if not re.search(r"αφμ|afm|vat|tax", upper.lower()):
                        continue
                if kind == "CREDIT_CARD" and not _luhn_ok(digits):
                    # 16 digits that fail Luhn are still likely a card when
                    # a label sits nearby; otherwise let AMKA/AFM claim them.
                    if len(digits) != 16:
                        continue
                if kind == "GREEK_ID" and not re.search(
                        r"[Α-ΩA-Z]{2}[\s.-]?\d{6}", val):
                    continue
                add(kind, score, val, _boxes_for_span(spans, m.start(), m.end()))

        # IBAN: candidates in spaced and glued form, checksum decides.
        for m in IBAN_CANDIDATE.finditer(text):
            compact = m.group()
            if _iban_ok(compact):
                add("IBAN", 0.95, compact,
                    _boxes_for_span(spans, m.start(), m.end()))
        for m in IBAN_SPACED.finditer(text):
            compact = re.sub(r"[\s.\-]", "", m.group())
            if _iban_ok(compact):
                add("IBAN", 0.95, compact,
                    _boxes_for_span(spans, m.start(), m.end()))

        # Labelled document fields: redact the value sitting after the label.
        for label, label_re in SENSITIVE_LABEL_RES:
            m = label_re.search(upper)
            if not m:
                continue
            value_start = m.end()
            tail = text[value_start:]
            # Bilingual documents print "SURNAME/ΕΠΩΝΥΜΟ": a tail starting
            # with "/" is the label's other-language half, not the value.
            # The value then sits after a colon ("NAME/ΟΝΟΜΑ: MARIA") or on
            # the next line.
            stripped = tail.lstrip(" ")
            if stripped.startswith("/"):
                colon = stripped.find(":")
                if colon >= 0:
                    value_start += len(tail) - len(stripped) + colon + 1
                    tail = text[value_start:]
                else:
                    tail = ""
            lead = len(tail) - len(tail.lstrip(" :.-—/"))
            start = value_start + lead
            boxes = _boxes_for_span(spans, start, len(text))
            if len(tail.strip()) >= 2 and boxes:
                add("DOC_FIELD", 0.85, tail.strip(), boxes)
            elif idx + 1 < len(line_records):
                # Label alone on the line: the value is the line below.
                ntext, nspans, _ = line_records[idx + 1]
                if len(ntext.strip()) >= 2:
                    add("DOC_FIELD", 0.75, ntext.strip(),
                        _boxes_for_span(nspans, 0, len(ntext)))

    return findings


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

def redact(img, findings, mode="blur"):
    """Return a copy of img with every finding covered.

    'blur'  — a heavy pixelate+gaussian mix; the document still reads as a
              document, which is nicer when sharing context.
    'black' — solid boxes; nothing survives, not even the shape of the text.
    """
    out = img.copy()
    for f in findings:
        for (x, y, w, h) in f["boxes"]:
            pad = 4
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1 = min(out.shape[1], x + w + pad)
            y1 = min(out.shape[0], y + h + pad)
            if x1 <= x0 or y1 <= y0:
                continue
            if mode == "black":
                cv2.rectangle(out, (x0, y0), (x1, y1), (12, 12, 14), -1)
            else:
                roi = out[y0:y1, x0:x1]
                # Coarse pixelation first, then blur: a 10-digit number has
                # to survive as ~7 featureless blocks, not soft-edged digits.
                small_w = max(3, (x1 - x0) // 22)
                small_h = max(3, (y1 - y0) // 22)
                roi = cv2.resize(roi, (small_w, small_h),
                                 interpolation=cv2.INTER_LINEAR)
                roi = cv2.resize(roi, (x1 - x0, y1 - y0),
                                 interpolation=cv2.INTER_NEAREST)
                roi = cv2.GaussianBlur(roi, (0, 0), 7)
                out[y0:y1, x0:x1] = roi
    return out


# --------------------------------------------------------------------------
# The scan itself
# --------------------------------------------------------------------------

def scan_photo(data_url_or_b64, mode="blur", want_faces=True, want_text=True):
    """Scan one image. Returns the verdict dict the API answers with.

    Serialised behind a lock: EasyOCR and MTCNN each want a slice of RAM the
    box cannot give twice at the same moment.
    """
    started = time.time()
    img = decode(data_url_or_b64)
    ih, iw = img.shape[:2]

    findings, warnings, engines = [], [], {}
    with _lock:
        if want_faces:
            boxes, face_engine = detect_faces(img)
            engines["faces"] = face_engine
            if face_engine == "none":
                warnings.append(
                    "Face detection unavailable on this server — faces were "
                    "not scanned.")
            for b in boxes:
                findings.append({
                    "kind": "FACE",
                    "score": 0.99,
                    "detail": "",
                    "boxes": [b],
                })
        if want_text:
            words, ocr_err = ocr_words(img)
            engines["ocr"] = _ocr_engine[0]
            if ocr_err:
                warnings.append(
                    "Text recognition unavailable — only faces were scanned. "
                    f"({ocr_err})")
            findings.extend(scan_text(words, img.shape))

    blocked = bool(findings)
    result = {
        "blocked": blocked,
        "width": iw,
        "height": ih,
        "scan_ms": int((time.time() - started) * 1000),
        "findings": [
            {
                "kind": f["kind"],
                "label_en": KIND_LABELS[f["kind"]][0],
                "label_el": KIND_LABELS[f["kind"]][1],
                "score": round(f["score"], 2),
                "detail": f["detail"],
                "boxes": f["boxes"],
            }
            for f in findings
        ],
        "counts": _count_by_kind(findings),
        "engines": engines,
        "warnings": warnings,
    }
    if blocked:
        result["redacted_image"] = encode_jpeg(redact(img, findings, mode))
    return result


def _count_by_kind(findings):
    counts = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    return counts


def engines_available():
    """True when at least one detector can run — else the route refuses."""
    if _face_detectors is None:
        _init_face_detectors()
    _init_ocr()
    return bool(_face_detectors) or _ocr_engine[1] is not None
