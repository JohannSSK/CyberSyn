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
        var jobs = [];
        var member = Session.getMember() || {};
        var adminToken = Session.getAdminToken();

        // End the sessions on the server too. Signing out used to clear only
        // localStorage, which left a token that could still be replayed for
        // a week by anyone who had copied it.
        if (member.parentId) {
            jobs.push(global.Api.post("/api/admin/employee/logout", {},
                { onUnauthorised: false }).catch(function () {}));
        }
        if (adminToken) {
            jobs.push(global.Api.post("/api/admin/logout", { token: adminToken },
                { member: false, onUnauthorised: false }).catch(function () {}));
        }

        var leave = function () {
            Session.clearAll();
            try { sessionStorage.removeItem(UNLOCK_KEY); } catch (err) { }
            location.href = "/";
        };

        if (!jobs.length) { leave(); return; }
        // A dead network must not be able to trap someone on the page.
        var timer = setTimeout(leave, 1500);
        Promise.all(jobs).then(function () {
            clearTimeout(timer);
            leave();
        }).catch(function () {
            clearTimeout(timer);
            leave();
        });
    }

    function guard() {
        if (!Session.ready()) {
            location.replace("/");
            return false;
        }
        return true;
    }

    /* ------------------------------------------------------------------
       Administrator step-up

       Carrying an administrator token is not the same as having just proved
       who you are. The token sits in localStorage for a week, so anyone at
       the keyboard — or anything running in the page — holds it too.
       Anything that exposes other people's activity therefore asks for the
       password again, and remembers the answer only for this tab (session
       storage, not local storage) and only for a few minutes.

       Authoritative enforcement is server-side: the token this produces is
       what the API demands. This only decides when to ask.
       ------------------------------------------------------------------ */

    var UNLOCK_KEY = "cybersyn_admin_unlock";
    var UNLOCK_MINUTES = 15;
    var ticker = null;

    function readUnlock() {
        try {
            return JSON.parse(sessionStorage.getItem(UNLOCK_KEY) || "null");
        } catch (err) {
            return null;
        }
    }

    function lockAdmin() {
        try {
            sessionStorage.removeItem(UNLOCK_KEY);
        } catch (err) { /* private mode: the answer is simply not kept */ }
        paintUnlock();
    }

    function writeUnlock(token, username, parentId) {
        var record = {
            token: token,
            username: username,
            parentId: parentId,
            until: Date.now() + UNLOCK_MINUTES * 60000
        };
        try {
            sessionStorage.setItem(UNLOCK_KEY, JSON.stringify(record));
        } catch (err) { /* not fatal: the next action just asks again */ }
        paintUnlock();
        return record;
    }

    function minutesLeft(record) {
        return Math.max(0, Math.ceil((record.until - Date.now()) / 60000));
    }

    /** The live unlock for this tab and workspace, or null. */
    function currentUnlock() {
        var record = readUnlock();
        if (!record || !record.token || !record.until) return null;
        if (Date.now() >= record.until) { lockAdmin(); return null; }
        // An unlock belongs to one workspace; acting as another member's
        // workspace must not inherit it.
        var member = Session.getMember() || {};
        if (record.parentId && member.parentId &&
            String(record.parentId) !== String(member.parentId)) {
            lockAdmin();
            return null;
        }
        return record;
    }

    /** Show how long administrator access stays open, and let it be closed. */
    function paintUnlock() {
        var slot = global.Dom.$("[data-admin-lock]");
        if (!slot) return;
        var record = currentUnlock();
        slot.innerHTML = "";
        if (!record) {
            slot.classList.add("hidden");
            return;
        }
        slot.classList.remove("hidden");

        var badge = global.Dom.el("div", "unlock-badge");
        badge.innerHTML =
            '<span class="unlock-dot"></span>' +
            '<span class="unlock-text">Administrator unlocked · <b>' +
            minutesLeft(record) + " min</b></span>" +
            '<button type="button" class="unlock-lock" data-action="lock-admin"' +
            ' title="Forget the administrator password for now">Lock now</button>';
        slot.appendChild(badge);

        global.Dom.on(badge.querySelector("[data-action='lock-admin']"), "click", function () {
            lockAdmin();
            global.Loading.toast("Administrator access locked.", "info");
        });
    }

    /**
     * Ask for the administrator password in a modal.
     * `onUnlock` receives {token, username, parentId}; `onCancel` fires when
     * the person closes it instead.
     */
    function adminGate(options, onUnlock, onCancel) {
        var opts = options || {};
        var admin = Session.getAdmin() || {};
        var known = !!admin.username;

        var overlay = global.Dom.el("div", "overlay");
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");

        var modal = global.Dom.el("div", "modal");
        modal.innerHTML =
            '<div class="modal-head">' +
            "  <div>" +
            '    <span class="eyebrow">Administrator approval</span>' +
            '    <h3 style="margin:4px 0 0">' + global.Dom.esc(opts.title || "This page") +
            " needs the administrator password</h3>" +
            "  </div>" +
            "</div>" +
            '<div class="modal-body">' +
            '  <p class="small muted" style="margin:0 0 16px">' +
            global.Dom.esc(opts.what || "This shows other people's activity.") +
            "</p>" +
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
            '  <button type="button" class="btn btn-ghost" data-gate-cancel>' +
            global.Dom.esc(opts.cancelLabel || "Cancel") + "</button>" +
            '  <button type="button" class="btn btn-primary" data-gate-unlock>' +
            global.Dom.esc(opts.confirmLabel || "Unlock") + "</button>" +
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
                var parentId = parseInt(data.Parent_id, 10);
                // The token proves the approval to the API; it is kept in
                // session storage so closing the tab ends it.
                Session.setAdmin(data.session_token, {
                    parentId: parentId,
                    username: data.username
                });
                close();
                onUnlock({
                    token: data.session_token,
                    username: data.username,
                    parentId: parentId
                });
            }).catch(function (err) {
                message.textContent = err.message || "That password was not accepted.";
                input.select();
            });
        }

        function cancel() {
            close();
            if (typeof onCancel === "function") onCancel();
        }

        global.Dom.on(unlock, "click", submit);
        global.Dom.on(modal.querySelector("[data-gate-cancel]"), "click", cancel);
        global.Dom.on(overlay, "click", function (event) {
            if (event.target === overlay) cancel();
        });
        global.Dom.on(input, "keydown", function (event) {
            if (event.key === "Escape") { event.preventDefault(); cancel(); return; }
            if (event.key === "Enter") { event.preventDefault(); submit(); }
        });
        return { close: close };
    }

    /**
     * Resolve with an administrator token, asking for the password first if
     * this tab has not proved it recently.

     * `fresh: true` ignores any earlier unlock, for actions that should be
     * confirmed every single time regardless of what was approved before.
     */
    function withAdmin(options) {
        var opts = options || {};
        var record = opts.fresh ? null : currentUnlock();
        if (record) return Promise.resolve(record.token);

        return new Promise(function (resolve, reject) {
            adminGate(opts, function (data) {
                writeUnlock(data.token, data.username, data.parentId);
                resolve(data.token);
            }, function () {
                var err = new Error("Administrator approval was cancelled.");
                err.cancelled = true;
                reject(err);
            });
        });
    }

    /**
     * Open a page that shows other people's activity. The page itself is
     * reachable; it is the contents that are locked.
     */
    function withAdminPage(page) {
        return withAdmin({
            title: page.title,
            what: "This page shows " + page.what +
                  ". Enter the administrator password to open it.",
            confirmLabel: "Unlock",
            cancelLabel: "Back to chat"
        }).catch(function (err) {
            if (err.cancelled) location.replace("/workspace");
            throw err;
        });
    }

    var ADMIN_ONLY = {
        "/stats": { title: "Statistics", what: "team activity, blocks and trends" },
        "/team": { title: "Team", what: "every member and how their gate is configured" }
    };

    function isAdminOnly(path) {
        var key = (path || "").replace(/\/+$/, "") || "/";
        return Object.prototype.hasOwnProperty.call(ADMIN_ONLY, key);
    }

    document.addEventListener("DOMContentLoaded", function () {
        paintIcons(document);
        markActive();
        paintMember();
        paintUnlock();

        // The badge counts down, and the moment it hits zero the unlock is
        // gone rather than stale-but-shown.
        clearInterval(ticker);
        ticker = setInterval(paintUnlock, 30000);

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
        withAdmin: withAdmin,
        withAdminPage: withAdminPage,
        adminGate: adminGate,
        lockAdmin: lockAdmin,
        isAdminOnly: isAdminOnly,
        paintMember: paintMember,
        paintUnlock: paintUnlock,
        paintIcons: paintIcons
    };
})(window);
