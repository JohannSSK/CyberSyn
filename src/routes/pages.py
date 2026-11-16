"""Pages.

Every screen is its own template. Shared chrome (head, icons, toasts, the
loading overlay) lives in `base.html`, so a page only contains what makes it
different.
"""

from flask import Blueprint, render_template

pages = Blueprint("pages", __name__)


@pages.get("/")
def portal():
    """Sign-in portal — deliberately kept as the calmest screen in the app."""
    return render_template("index.html")


@pages.get("/workspace")
def workspace():
    return render_template("workspace.html")


@pages.get("/profile")
def profile():
    return render_template("profile.html")


@pages.get("/settings")
def settings_page():
    return render_template("settings.html")


@pages.get("/stats")
def stats():
    """Administrator statistics: the analyst's 'who did what, and when'."""
    return render_template("stats.html")


@pages.get("/team")
def team():
    return render_template("team.html")


@pages.get("/help")
def help_page():
    return render_template("help.html")


@pages.get("/signup/admin")
def signup_admin():
    return render_template("signup_admin.html")


@pages.get("/signup/employee")
def signup_employee():
    return render_template("signup_employee.html")


@pages.get("/remove/employee")
def remove_employee():
    return render_template("remove_employee.html")
