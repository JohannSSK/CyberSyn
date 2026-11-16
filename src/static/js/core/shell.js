/* ==========================================================================
   shell.js — the shared chrome: sidebar wiring, active page, sign-out.

   Loaded on every page so the navigation behaves the same everywhere and a
   page script never repeats this.
   ========================================================================== */

(function (global) {
    "use strict";

    var Session = global.Api.Session;

    /**
     * Fill every <span data-icon="name"> with the real icon.
     * Templates stay readable: <span data-icon="settings"></span>
     *
     * Safe to call again after inserting markup: slots already filled are
     * gone, because they have been replaced by the icon itself.
     */
    function paintIcons(root) {
        global.Dom.$$("span[data-icon]", root).forEach(function (slot) {
            var name = slot.getAttribute("data-icon");
            var extra = slot.className;
            slot.outerHTML = global.Icons.html(name, "icon " + (extra || ""));
        });
    }

    /** Mark the sidebar entry for the current path as active. */
    function markActive() {
        var here = location.pathname.replace(/\/+$/, "") || "/";
        global.Dom.$$("[data-nav]").forEach(function (link) {
            var target = link.getAttribute("data-nav").replace(/\/+$/, "") || "/";
            var active = target === here ||
                (target !== "/" && here.indexOf(target) === 0);
            link.classList.toggle("is-active", active);
            if (active) link.setAttribute("aria-current", "page");
        });
    }

    /** Render the signed-in member into any [data-member-name] element. */
    function paintMember() {
        var member = Session.getMember() || {};
        global.Dom.$$("[data-member-name]").forEach(function (node) {
            node.textContent = member.username || "Member";
        });
        global.Dom.$$("[data-member-avatar]").forEach(function (node) {
            node.textContent = (member.username || "M").charAt(0).toUpperCase();
        });
        global.Dom.$$("[data-workspace]").forEach(function (node) {
            node.textContent = member.parentId ? ("Workspace " + member.parentId) : "";
        });
    }

    function signOut() {
        var member = Session.getMember() || {};
        if (member.parentId) {
            // Best effort: the server drops the session either way.
            global.Api.post("/api/admin/logout", {}, { member: false }).catch(function () {});
        }
        Session.clearAll();
        location.href = "/";
    }

    function guard() {
        if (!Session.ready()) {
            location.replace("/");
            return false;
        }
        return true;
    }

    document.addEventListener("DOMContentLoaded", function () {
        paintIcons(document);
        markActive();
        paintMember();

        global.Dom.$$("[data-action='sign-out']").forEach(function (btn) {
            global.Dom.on(btn, "click", signOut);
        });

        // Sidebar toggle on narrow screens.
        var sidebar = global.Dom.$("[data-sidebar]");
        global.Dom.$$("[data-action='toggle-sidebar']").forEach(function (btn) {
            global.Dom.on(btn, "click", function () {
                if (sidebar) sidebar.classList.toggle("is-open");
            });
        });
    });

    /* Called by api.js when the server says the session is gone. */
    global.onSessionExpired = function () {
        global.Loading.toast("Your session has ended. Sign in again.", "warn");
        setTimeout(function () { location.replace("/"); }, 900);
    };

    global.Shell = {
        signOut: signOut,
        guard: guard,
        paintMember: paintMember,
        paintIcons: paintIcons
    };
})(window);
