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

    /* Pages that show other people's activity: statistics and the team
       roster. The API refuses a non-administrator either way, but the page
       itself should never render for one, so members are sent back to their
       chat instead of being shown an empty dashboard.

       The gate is client-side because sessions are bearer tokens held in
       localStorage, not cookies — the server cannot see them on a page
       request. Authoritative enforcement stays at the API. */
    var ADMIN_ONLY = ["/stats", "/team"];

    function isAdminOnly(path) {
        return ADMIN_ONLY.indexOf((path || "").replace(/\/+$/, "") || "/") !== -1;
    }

    function guardAdmin() {
        if (!guard()) return false;
        if (isAdminOnly(location.pathname) && !Session.getAdminToken()) {
            global.Loading.toast("That page needs an administrator sign-in.", "warn");
            setTimeout(function () { location.replace("/workspace"); }, 700);
            return false;
        }
        return true;
    }

    /* Hide the same entries from the sidebar for members: a link that can
       only bounce you back is worse than no link. */
    function markAdminNav() {
        var isAdmin = !!Session.getAdminToken();
        global.Dom.$$("[data-nav]").forEach(function (link) {
            if (isAdminOnly(link.getAttribute("data-nav"))) {
                link.classList.toggle("hidden", !isAdmin);
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        paintIcons(document);
        markActive();
        paintMember();
        markAdminNav();

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
        guardAdmin: guardAdmin,
        isAdminOnly: isAdminOnly,
        paintMember: paintMember,
        paintIcons: paintIcons
    };
})(window);
