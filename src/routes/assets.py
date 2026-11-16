"""Serve the repository's `assets/` folder.

Icon artwork lives in the repository's own assets directory rather than
inside src/static, because it is design source, not application code. This
exposes it at /assets/... so templates can use an ordinary URL.
"""

from flask import Blueprint, abort, send_from_directory

from config import ASSETS_DIR

assets = Blueprint("assets", __name__)


@assets.get("/assets/<path:filename>")
def serve(filename):
    if not ASSETS_DIR.is_dir():
        abort(404)
    # send_from_directory resolves the path safely, so ../ cannot escape.
    return send_from_directory(ASSETS_DIR, filename)
