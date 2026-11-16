#!/usr/bin/env python3
"""CyberSyn — the gate every AI prompt passes through.

This module builds the application and nothing else: configuration, schema,
blueprints, error handling. Every route lives in `src/routes/`, every piece
of domain logic in its own module, so this file stays readable top to bottom.

Run:    python3 src/app.py
Seed:   python3 src/app.py seed
Docker: docker compose up --build
"""

import sys
import threading

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import admin_session
import db
import scanners
from config import (DEBUG, HOST, PORT, TEMPLATES_DIR, DB_FILE, WARM_MODELS,
                    STATIC_DIR)
from errors import ApiError
from secret_store import migrate_api_keys


def create_app():
    app = Flask(__name__, static_folder=str(STATIC_DIR),
                template_folder=str(TEMPLATES_DIR))
    app.json.ensure_ascii = False

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
        app.logger.exception("Unhandled error: %s", exc)
        return jsonify({
            "error": True,
            "error_message": f"Server error: {type(exc).__name__}: {exc}",
        }), 500

    return app


def register_api(app):
    """Register every API blueprint."""
    from routes import admin_api, assets, chat_api, chat_history, member_api
    from models_route import register as register_models
    from team_stats import register as register_team_stats

    app.register_blueprint(assets.assets)
    app.register_blueprint(admin_api.admin_api)
    app.register_blueprint(member_api.member_api)
    app.register_blueprint(chat_api.chat_api)
    app.register_blueprint(chat_history.chat_history)
    register_models(app)
    register_team_stats(app)


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
                # Not an error -- the models are simply not on this machine
                # yet, and fetching them at start-up would hold the scanner
                # lock. Say so, because otherwise the first prompt is slow
                # with no explanation why.
                print("Models not loaded (will load on first use): "
                      + ", ".join(warmed["skipped"]))
        except Exception as exc:
            print(f"Model warm-up skipped: {type(exc).__name__}: {exc}")

    threading.Thread(target=run, daemon=True).start()


app = create_app()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        return db.seed(*sys.argv[2:4])

    print("Database file :", DB_FILE)
    print("Routes:")
    for rule in app.url_map.iter_rules():
        if rule.endpoint != "static":
            print(f"  {sorted(rule.methods - {'HEAD', 'OPTIONS'})}  {rule.rule}")

    if WARM_MODELS:
        warm_models(app)

    # 0.0.0.0 so the container is reachable from outside it.
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
