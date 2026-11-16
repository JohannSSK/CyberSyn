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
       roster. The API refuses a non-administrator either way, but a member
       opening one is asked for the administrator password rather than being
       turned away — the page is reachable, just not unlocked.

       The gate is client-side because sessions are bearer tokens held in
       localStorage, not cookies — the server cannot see them on a page
       request. Authoritative enforcement stays at the API. */
    var ADMIN_ONLY = {
        "/stats": { title: "Statistics", what: "team activity, blocks and trends" },
        "/team": { title: "Team", what: "every member and how their gate is configured" }
    };

    function isAdminOnly(path) {
        var key = (path || "").replace(/\/+$/, "") || "/";
        return Object.prototype.hasOwnProperty.call(ADMIN_ONLY, key);
    }

    /**
     * Ask for the administrator password, then reload so the page script runs
     * again with a token in hand.
     */
    function adminGate(page) {
        var admin = Session.getAdmin() || {};
        var known = !!admin.username;

        var overlay = global.Dom.el("div", "overlay");
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");

        var modal = global.Dom.el("div", "modal");
        modal.innerHTML =
            '<div class="modal-head">' +
            "  <div>" +
            '    <span class="eyebrow">Administrator only</span>' +
            '    <h3 style="margin:4px 0 0">' + global.Dom.esc(page.title) +
            " needs the administrator password</h3>" +
            "  </div>" +
            "</div>" +
            '<div class="modal-body">' +
            '  <p class="small muted" style="margin:0 0 16px">This page shows ' +
            global.Dom.esc(page.what) +
            ". Enter the administrator password to open it.</p>" +
            (known
                ? ""
                : '  <div class="field">' +
                  '    <label for="admin-gate-username">Administrator username</label>' +
                  '    <input type="text" id="admin-gate-username" class="input"' +
                  '           autocomplete="username">' +
                  "  </div>") +
            '  <div class="field">' +
            '    <label for="admin-gate-password">Administrator password</label>' +
            '    <input type="password" id="admin-gate-password" class="input"' +
            '           autocomplete="off" autofocus>' +
            "  </div>" +
            '  <p class="form-msg" data-gate-msg></p>' +
            "</div>" +
            '<div class="modal-foot">' +
            '  <button type="button" class="btn btn-ghost" data-gate-cancel>Back to chat</button>' +
            '  <button type="button" class="btn btn-primary" data-gate-unlock>Unlock</button>' +
            "</div>";
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        var input = modal.querySelector("#admin-gate-password");
        var usernameField = modal.querySelector("#admin-gate-username");
        var unlock = modal.querySelector("[data-gate-unlock]");
        var message = modal.querySelector("[data-gate-msg]");
        if (known) {
            input.placeholder = "Password for " + admin.username;
        }
        (usernameField || input).focus();

        function close() { overlay.remove(); }

        function submit() {
            var password = input.value;
            if (!password) {
                message.textContent = "Enter the administrator password.";
                input.focus();
                return;
            }
            message.textContent = "";
            var username = known ? admin.username : usernameField.value.trim();
            if (!username) {
                message.textContent = "Enter the administrator username.";
                usernameField.focus();
                return;
            }
            global.Loading.withButton(unlock, function () {
                return global.Api.post("/api/admin/login", {
                    username: username,
                    password: password
                }, { member: false, onUnauthorised: false });
            }).then(function (data) {
                Session.setAdmin(data.session_token, {
                    parentId: parseInt(data.Parent_id, 10),
                    username: data.username
                });
                // Reload so the page script sees the token and fills itself in.
                location.reload();
            }).catch(function (err) {
                message.textContent = err.message || "That password was not accepted.";
                input.select();
            });
        }

        global.Dom.on(unlock, "click", submit);
        global.Dom.on(modal.querySelector("[data-gate-cancel]"), "click", function () {
            location.replace("/workspace");
        });
        global.Dom.on(input, "keydown", function (event) {
            if (event.key === "Enter") { event.preventDefault(); submit(); }
        });
        return { close: close };
    }

    function guardAdmin() {
        if (!guard()) return false;
        var key = location.pathname.replace(/\/+$/, "") || "/";
        if (!ADMIN_ONLY[key]) return true;
        if (Session.getAdminToken()) return true;

        adminGate(ADMIN_ONLY[key]);
        return false;
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
        guardAdmin: guardAdmin,
        adminGate: adminGate,
        isAdminOnly: isAdminOnly,
        paintMember: paintMember,
        paintIcons: paintIcons
    };
})(window);
