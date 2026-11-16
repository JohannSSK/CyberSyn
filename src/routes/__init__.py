"""Blueprints, one per concern.

Each module owns one slice of the API and is registered once by
:func:`app.create_app`. Keeping the split here rather than in app.py means a
route can be read, tested and reasoned about without the other forty.
"""

from flask import Blueprint


def blueprint(name):
    return Blueprint(name, __name__)
