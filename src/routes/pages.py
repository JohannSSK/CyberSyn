"""Pages.

Every screen is its own template. Shared chrome (head, icons, toasts, the
loading overlay) lives in `base.html`, so a page only contains what makes it
different.
"""

from math import ceil

from flask import Blueprint, render_template

from config import OPENAI_TIMEOUT
from scanning import MAX_SCREEN_BUDGET

pages = Blueprint("pages", __name__)


def _timeouts():
    """What the browser needs to know about how long a prompt may take.

    Use the same ceiling as the server: even the largest paste has time for
    screening and the completion that follows it.
    """
    screen = ceil(MAX_SCREEN_BUDGET)
    ai = int(OPENAI_TIMEOUT)
    return {
        "screen_budget": screen,
        "ai_timeout": ai,
        # 30s over the sum: request overhead, and a margin so the browser
        # never gives up while the server is still making progress.
        "request_timeout": screen + ai + 30,
    }


@pages.get("/")
def portal():
    """Sign-in portal — deliberately kept as the calmest screen in the app."""
    return render_template("index.html", **_timeouts())


# Creating or deleting an account is its own screen. It used to reuse the
# sign-in boxes, so the same two fields meant "sign in" or "create" or
# "delete" depending on which link you had clicked last.
@pages.get("/create-admin")
def create_admin():
    return render_template("create_admin.html", **_timeouts())


@pages.get("/delete-admin")
def delete_admin():
    return render_template("delete_admin.html", **_timeouts())


@pages.get("/create-member")
def create_member():
    return render_template("create_member.html", **_timeouts())


@pages.get("/delete-member")
def delete_member():
    return render_template("delete_member.html", **_timeouts())


@pages.get("/workspace")
def workspace():
    return render_template("workspace.html", **_timeouts())


@pages.get("/profile")
def profile():
    return render_template("profile.html", **_timeouts())


@pages.get("/settings")
def settings_page():
    return render_template("settings.html", **_timeouts())


@pages.get("/stats")
def stats():
    """Administrator statistics: the analyst's 'who did what, and when'."""
    return render_template("stats.html", **_timeouts())


@pages.get("/team")
def team():
    return render_template("team.html", **_timeouts())


@pages.get("/shadow-ai")
def shadow_ai():
    return render_template("shadow_ai.html", **_timeouts())


@pages.get("/help")
def help_page():
    return render_template("help.html", **_timeouts())

