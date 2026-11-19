#!/usr/bin/env python3
"""CyberSyn — the gate every AI prompt passes through.

This module builds the application and nothing else: configuration, schema,
blueprints, error handling. Every route lives in `src/routes/`, every piece
of domain logic in its own module, so this file stays readable top to bottom.

Run:    ./setup.sh, then cybersyn -p 8000
Seed:   cybersyn seed
Docker: docker compose up --build
"""

import os
import sys
import threading

from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.serving import is_running_from_reloader

import admin_session
import db
import scanners
from config import (BACKEND_DIR, DEBUG, HOST, PORT, TEMPLATES_DIR, DB_FILE,
                    WARM_MODELS, STATIC_DIR, ROUTES)
from errors import ApiError
from secret_store import migrate_api_keys


def create_app():
    app = Flask(__name__, static_folder=str(STATIC_DIR),
                template_folder=str(TEMPLATES_DIR))
    app.jinja_env.globals["api_routes"] = ROUTES
    app.json.ensure_ascii = False
    default_max_body = int(os.environ.get("CYBERSYN_MAX_BODY_BYTES", 256 * 1024))
    max_photo_body = int(os.environ.get("CYBERSYN_MAX_PHOTO_BODY_BYTES", 12 * 1024 * 1024))
    app.config["MAX_CONTENT_LENGTH"] = max(default_max_body, max_photo_body)

    @app.before_request
    def _enforce_body_limit():
        limit = max_photo_body if request.path == ROUTES["CHAT_PHOTO"] else default_max_body
        if request.content_length is not None and request.content_length > limit:
            abort(413)
        if request.content_length is None and request.path != ROUTES["CHAT_PHOTO"]:
            if len(request.get_data(cache=True)) > limit:
                abort(413)

    # ---- schema ----
    db.init_db()
    admin_session.init_table(DB_FILE)
    _import("auth").init_tables(DB_FILE)
    db.check_schema()
    migrate_api_keys(DB_FILE)
    _import("chat_store").init_tables(DB_FILE)

    # ---- routes ----
    from routes import pages
    app.register_blueprint(pages.pages)
    register_api(app)

    admin_session.register(app)

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if response.is_json:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.teardown_appcontext
    def close_db(_exc):
        db.close_db()

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = {"error": True, "error_message": exc.message}
        body.update(exc.payload)
        return jsonify(body), exc.status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return jsonify({
            "error": True,
            "error_message": f"{exc.code} {exc.name}: {exc.description}",
        }), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # A JSON answer, never an HTML traceback: this app is an API first.
        # Scanner, provider and parser exceptions can carry private input.
        # This remains metadata-only even with framework debugging enabled.
        app.logger.error("Unhandled request error (%s)", type(exc).__name__)
        return jsonify({
            "error": True,
            "error_message": "Internal server error.",
        }), 500

    return app


def register_api(app):
    """Register every API blueprint."""
    from routes import admin_api, assets, chat_api, chat_history, member_api, openai_proxy
    from models_route import register as register_models
    from team_stats import register as register_team_stats
    from shadow_ai import shadow_api

    app.register_blueprint(assets.assets)
    app.register_blueprint(admin_api.admin_api)
    app.register_blueprint(member_api.member_api)
    app.register_blueprint(chat_api.chat_api)
    app.register_blueprint(chat_history.chat_history)
    app.register_blueprint(openai_proxy.openai_proxy)
    register_models(app)
    register_team_stats(app)
    app.register_blueprint(shadow_api)


def _import(name):
    import importlib

    return importlib.import_module(name)


def warm_models(app=None):
    """Load the scanner models on a background thread.

    The first prompt would otherwise wait for torch and spaCy to start.
    Doing it while the app is already serving means nobody notices.
    """
    def run():
        try:
            loaded = scanners.preload()
            sys.path.insert(0, str(scanners.ML_DIR))
            from model_cache import warm

            warmed = warm()
            # LiteLLM is imported here too, so its import cost lands on
            # start-up rather than on whoever sends the first message.
            _import("ai_client").preload()
            print(f"Warmed scanners: {loaded}, models: {warmed['loaded']}")
            if warmed["skipped"]:
                print("Local models unavailable: " + ", ".join(warmed["skipped"])
                      + ". Run ./setup.sh (native) or rebuild the image.")
        except Exception as exc:
            print(f"Model warm-up skipped: {type(exc).__name__}: {exc}")

    threading.Thread(target=run, daemon=True).start()


app = create_app()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        return db.seed(*sys.argv[2:4])

    print("Data directory:", BACKEND_DIR)
    print("Database file :", DB_FILE)
    print("Routes:")
    for rule in app.url_map.iter_rules():
        if rule.endpoint != "static":
            print(f"  {sorted(rule.methods - {'HEAD', 'OPTIONS'})}  {rule.rule}")

    # With the debug reloader, only the serving child needs the models.
    if WARM_MODELS and (not DEBUG or is_running_from_reloader()):
        warm_models(app)

    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
