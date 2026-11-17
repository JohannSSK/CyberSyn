"""Photo screening route.

The image twin of the chat gate: a member uploads a photo, the scanner
finds personal data in it (faces, tax numbers, phones, IBANs, labelled
document fields), and the answer carries the verdict plus a redacted copy.

Privacy shape, matching the rest of the product:

* the uploaded bytes live only for the request — never written to disk;
* what is found is logged as a category count, never the content itself;
* when something is found, the original is refused and the redacted copy
  is the only image that leaves the scanner.
"""

from flask import Blueprint

from auth import require_member
from block_log import record_activity, record_block
from config import DB_FILE, ROUTES
from web import get_json_dict, chat_response, ok

photo_api = Blueprint("photo_api", __name__)

# ~12 MB of base64 is ~9 MB of photograph — beyond that, OCR slows down for
# no detection gain and the request body itself becomes the attack.
MAX_BODY_CHARS = 12 * 1024 * 1024 * 4 // 3 + 1024


def _scanner():
    """Import the scanner on demand.

    The imaging stack (opencv, torch, the OCR engines) is heavier than the
    rest of the app and missing on some installs — like the text scanners,
    the feature degrades instead of taking the whole server down with it.
    The route still refuses the scan (fail closed); it just explains why.
    """
    try:
        import image_scan
        return image_scan, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


@photo_api.post(ROUTES["PHOTO_SCAN"])
def photo_scan():
    data = get_json_dict()
    if data is None:
        return chat_response(True, message="Request body must be a JSON object.",
                             status=400)

    parent_id, employee_id, _ = require_member(DB_FILE, data)
    if parent_id is None:
        return chat_response(True, message="Not signed in.", status=401)

    image = data.get("image")
    if not isinstance(image, str) or not image.strip():
        return chat_response(True, message="'image' must be a base64 string.",
                             status=400)
    if len(image) > MAX_BODY_CHARS:
        return chat_response(True, message="The image is too large (12 MB max).",
                             status=413)

    image_scan, unavailable = _scanner()
    if image_scan is None:
        return chat_response(
            True, status=503,
            message="Photo scanning is not installed on this server "
                    f"({unavailable}). See requirements.txt.")

    mode = str(data.get("mode", "blur")).lower()
    if mode not in ("blur", "black"):
        mode = "blur"

    try:
        result = image_scan.scan_photo(image, mode=mode)
    except image_scan.ImageTooLarge as exc:
        return chat_response(True, message=str(exc), status=413)
    except image_scan.NotAnImage as exc:
        return chat_response(True, message=str(exc), status=400)
    except Exception as exc:
        # Fail closed: a scanner that errored must not wave the photo
        # through, but the member still deserves a readable reason.
        return chat_response(
            True, message=f"The photo could not be scanned ({exc}). "
                          "Nothing was uploaded.", status=500)

    # The audit trail records that a photo was screened and what kind of
    # data stopped it — never the data itself.
    kinds = ",".join(sorted(result["counts"].keys())) or "none"
    record_activity(DB_FILE, parent_id, employee_id, "photo_scan",
                    f"kinds={kinds} n={len(result['findings'])}")
    if result["blocked"]:
        record_block(DB_FILE, parent_id, employee_id, "photo",
                     f"Photo blocked: {kinds}")

    result.pop("error", None)
    return ok(**result)
