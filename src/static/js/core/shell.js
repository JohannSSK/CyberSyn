/* ==========================================================================
   shell.js — shared chrome: sidebar wiring, avatars, modals, sign-out.

   Loaded on every page so navigation, administrator step-up, confirmation
   dialogs and sign-out behave the same way everywhere.
   ========================================================================== */

(function (global) {
    "use strict";

    var Session = global.Api.Session;
    var primaryAdmin = null;

    function t(text) {
        return global.I18n && typeof global.I18n.t === "function"
            ? global.I18n.t(text)
            : text;
    }

    function reducedMotion() {
        return !!(global.matchMedia &&
            global.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }

    /**
     * Fill every <span data-icon="name"> with its icon.
     * Slots carrying `data-icon-svg` render inline SVG so `currentColor`
     * applies (for instance, dark ink on a warm-grey primary button).
     */
    function paintIcons(root) {
        global.Dom.$$("span[data-icon]", root).forEach(function (slot) {
            var name = slot.getAttribute("data-icon");
            var cls = ("icon " + (slot.className || "")).trim();
            var asSvg = slot.hasAttribute("data-icon-svg");
            slot.outerHTML = asSvg
                ? global.Icons.svg(name, cls)
                : global.Icons.html(name, cls);
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
            else link.removeAttribute("aria-current");
        });
    }

    /** Render the signed-in member (or administrator) into shared chrome. */
    function paintMember() {
        var member = primaryAdmin ? {} : (Session.getMember() || {});
        var admin = primaryAdmin || Session.getAdmin() || {};
        var name = member.username || admin.username || t("Member");
        var wsId = member.parentId || admin.parentId || null;

        global.Dom.$$("[data-member-name]").forEach(function (node) {
            node.textContent = name;
        });
        global.Dom.$$("[data-member-avatar]").forEach(function (node) {
            if (global.Dom.paintAvatar) {
                global.Dom.paintAvatar(node, member.username || admin.username || "M");
            } else {
                node.textContent = name.charAt(0).toUpperCase();
            }
        });
        global.Dom.$$("[data-workspace]").forEach(function (node) {
            node.textContent = wsId ? t("Workspace " + wsId) : "";
        });
        global.Dom.$$("[data-sidebar-role]").forEach(function (node) {
            node.textContent = primaryAdmin ? t("Administrator") : t("Administrator-managed workspace");
        });
        global.Dom.$$('[data-member-only]').forEach(function (link) { link.hidden = !!primaryAdmin; });
        global.Dom.$$('[data-admin-hub]').forEach(function (link) { link.hidden = !primaryAdmin; });
    }

    /** Show a brief, quiet sign-out confirmation before returning to /. */
    function showSignedOutAndLeave() {
        var screen = global.Dom.el("div", "signout-screen");
        screen.setAttribute("role", "status");
        screen.setAttribute("aria-live", "polite");
        screen.innerHTML =
            '<svg class="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
            '<path fill="currentColor" fill-rule="evenodd" d="M12 2.4L19.6 5.65V11.5c0 4.95-3.32 9.04-7.6 10.22C7.72 20.54 4.4 16.45 4.4 11.5V5.65L12 2.4zm3.53 7.07a.85.85 0 00-1.2 0L11 12.8 9.67 11.47a.85.85 0 10-1.2 1.2l1.93 1.93a.85.85 0 001.2 0l3.93-3.93a.85.85 0 000-1.2z"/>' +
            "</svg>" +
            "<h1>" + global.Dom.esc(t("Signed out.")) + "</h1>" +
            "<p>" + global.Dom.esc(t("This tab can be closed safely.")) + "</p>";
        document.body.appendChild(screen);

        var pause = reducedMotion() ? 450 : 950;
        setTimeout(function () { location.href = "/"; }, pause);
    }

    function signOut() {
        var jobs = [];
        var member = Session.getMember() || {};

        // End sessions on the server too so HttpOnly cookies and grants cannot be replayed.
        if (member.parentId) {
            jobs.push(global.Api.post("EMPLOYEE_LOGOUT", {},
                { onUnauthorised: false }).catch(function () {}));
        }
        jobs.push(global.Api.post("ADMIN_LOGOUT", {},
            { member: false, onUnauthorised: false }).catch(function () {}));

        var settled = false;
        var leave = function () {
            if (settled) return;
            settled = true;
            Session.clearAll();
            try { sessionStorage.removeItem(UNLOCK_KEY); } catch (err) { }
            showSignedOutAndLeave();
        };

        if (!jobs.length) { leave(); return; }
        // A dead network must never trap someone on a signed-in screen.
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

    /** Legacy synchronous hint; use enterAdminPage to verify cookie access. */
    function guardAdmin() {
        var admin = Session.getAdmin() || {};
        if (!Session.ready() && !admin.parentId) {
            location.replace("/?tab=admin");
            return false;
        }
        return true;
    }

    /* ------------------------------------------------------------------
       Accessible modal focus helper — traps Tab inside the dialog and
       restores focus to the control that opened it.
       ------------------------------------------------------------------ */

    function trapModal(overlay, modal, onEscape) {
        var opener = document.activeElement;

        function focusables() {
            return global.Dom.$$(
                'button:not(:disabled), input:not(:disabled), select:not(:disabled), ' +
                'textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
                modal
            );
        }

        global.Dom.on(overlay, "keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                onEscape();
                return;
            }
            if (event.key !== "Tab") return;
            var items = focusables();
            if (!items.length) return;
            var first = items[0];
            var last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });

        return function release() {
            overlay.remove();
            if (opener && typeof opener.focus === "function" && opener.isConnected) {
                opener.focus();
            }
        };
    }

    /* ------------------------------------------------------------------
       Calm confirmation & rename modals — replaces browser confirm/prompt
       so destructive actions always name what is removed and what is kept.
       ------------------------------------------------------------------ */

    function confirmDialog(options) {
        var opts = options || {};
        return new Promise(function (resolve) {
            var overlay = global.Dom.el("div", "overlay");
            overlay.setAttribute("role", "dialog");
            overlay.setAttribute("aria-modal", "true");
            var titleId = "confirm-title-" + Date.now();
            overlay.setAttribute("aria-labelledby", titleId);

            var modal = global.Dom.el("div", "modal");
            var noteCls = "modal-note" + (opts.danger ? " modal-note-danger" : "");
            var noteHtml = "";
            if (opts.lost || opts.kept) {
                noteHtml = '<div class="' + noteCls + '">' +
                    (opts.lost ? "<span>" + global.Dom.esc(t(opts.lost)) + "</span>" : "") +
                    (opts.kept ? '<span class="modal-note-kept">' + global.Dom.esc(t(opts.kept)) + "</span>" : "") +
                    "</div>";
            }

            modal.innerHTML =
                '<div class="modal-head">' +
                "  <div>" +
                '    <span class="eyebrow">' + global.Dom.esc(t(opts.eyebrow || "Please confirm")) + "</span>" +
                '    <h3 id="' + titleId + '">' + global.Dom.esc(t(opts.title || "Are you sure?")) + "</h3>" +
                "  </div>" +
                "</div>" +
                '<div class="modal-body">' +
                (opts.body ? '<p class="small dim">' + global.Dom.esc(t(opts.body)) + "</p>" : "") +
                noteHtml +
                "</div>" +
                '<div class="modal-foot">' +
                '  <button type="button" class="btn btn-ghost" data-confirm-cancel>' +
                global.Dom.esc(t(opts.cancelLabel || "Cancel")) + "</button>" +
                '  <button type="button" class="btn ' +
                (opts.danger ? "btn-danger" : "btn-primary") + '" data-confirm-accept>' +
                global.Dom.esc(t(opts.confirmLabel || "Confirm")) + "</button>" +
                "</div>";

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            var done = false;
            var release = trapModal(overlay, modal, function () { finish(false); });

            function finish(answer) {
                if (done) return;
                done = true;
                release();
                resolve(answer);
            }

            var cancelBtn = modal.querySelector("[data-confirm-cancel]");
            var acceptBtn = modal.querySelector("[data-confirm-accept]");
            global.Dom.on(cancelBtn, "click", function () { finish(false); });
            global.Dom.on(acceptBtn, "click", function () { finish(true); });
            global.Dom.on(overlay, "click", function (event) {
                if (event.target === overlay) finish(false);
            });

            // Focus cancel on destructive prompts so a reflex Enter never deletes.
            (opts.danger ? cancelBtn : acceptBtn).focus();
        });
    }

    function promptDialog(options) {
        var opts = options || {};
        return new Promise(function (resolve) {
            var overlay = global.Dom.el("div", "overlay");
            overlay.setAttribute("role", "dialog");
            overlay.setAttribute("aria-modal", "true");
            var titleId = "prompt-title-" + Date.now();
            var inputId = "prompt-field-" + Date.now();
            overlay.setAttribute("aria-labelledby", titleId);

            var modal = global.Dom.el("div", "modal");
            modal.innerHTML =
                '<div class="modal-head">' +
                "  <div>" +
                '    <span class="eyebrow">' + global.Dom.esc(t(opts.eyebrow || "Conversation")) + "</span>" +
                '    <h3 id="' + titleId + '">' + global.Dom.esc(t(opts.title || "Rename")) + "</h3>" +
                "  </div>" +
                "</div>" +
                '<div class="modal-body">' +
                '  <div class="field">' +
                '    <label for="' + inputId + '">' + global.Dom.esc(t(opts.label || "Title")) + "</label>" +
                '    <input type="text" id="' + inputId + '" class="input" autocomplete="off"' +
                (opts.maxLength ? ' maxlength="' + parseInt(opts.maxLength, 10) + '"' : "") +
                (opts.placeholder ? ' placeholder="' + global.Dom.esc(t(opts.placeholder)) + '"' : "") +
                ">" +
                "  </div>" +
                "</div>" +
                '<div class="modal-foot">' +
                '  <button type="button" class="btn btn-ghost" data-prompt-cancel>' +
                global.Dom.esc(t(opts.cancelLabel || "Cancel")) + "</button>" +
                '  <button type="button" class="btn btn-primary" data-prompt-save>' +
                global.Dom.esc(t(opts.confirmLabel || "Save")) + "</button>" +
                "</div>";

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            var input = modal.querySelector("#" + inputId);
            input.value = opts.value || "";

            var done = false;
            var release = trapModal(overlay, modal, function () { finish(null); });

            function finish(value) {
                if (done) return;
                done = true;
                release();
                resolve(value);
            }

            global.Dom.on(modal.querySelector("[data-prompt-cancel]"), "click", function () {
                finish(null);
            });
            global.Dom.on(modal.querySelector("[data-prompt-save]"), "click", function () {
                finish(input.value);
            });
            global.Dom.on(input, "keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    finish(input.value);
                }
            });
            global.Dom.on(overlay, "click", function (event) {
                if (event.target === overlay) finish(null);
            });

            input.focus();
            input.select();
        });
    }

    /* ------------------------------------------------------------------
       Administrator step-up

       Only the display timestamp hint is kept in this tab. The short-lived
       page grant lives in an HttpOnly cookie; a settings or override approval
       is used once from memory and never unlocks a page.
       ------------------------------------------------------------------ */

    var UNLOCK_KEY = "cybersyn_page_hint";
    var UNLOCK_MINUTES = 15;
    var ticker = null;

    function readUnlock() {
        try {
            return JSON.parse(sessionStorage.getItem(UNLOCK_KEY) || "null");
        } catch (err) {
            return null;
        }
    }

    function forgetUnlock() {
        try {
            sessionStorage.removeItem(UNLOCK_KEY);
        } catch (err) { /* private mode: nothing to clear */ }
        paintUnlock();
    }

    function lockAdmin() {
        forgetUnlock();
        return global.Api.post("ADMIN_LOGOUT", { scope: "page" },
            { member: false, onUnauthorised: false });
    }

    function writeUnlock(username, parentId) {
        var record = {
            username: username,
            parentId: parentId,
            until: Date.now() + UNLOCK_MINUTES * 60000
        };
        try {
            sessionStorage.setItem(UNLOCK_KEY, JSON.stringify(record));
        } catch (err) { /* next action simply asks again */ }
        paintUnlock();
        return record;
    }

    function minutesLeft(record) {
        return Math.max(0, Math.ceil((record.until - Date.now()) / 60000));
    }

    /** The live unlock hint for this tab and workspace, or null. */
    function currentUnlock() {
        var record = readUnlock();
        if (!record || !record.until) return null;
        if (Date.now() >= record.until) { forgetUnlock(); return null; }
        var member = Session.getMember() || {};
        if (record.parentId && member.parentId &&
            String(record.parentId) !== String(member.parentId)) {
            forgetUnlock();
            return null;
        }
        return record;
    }

    /** Show how long administrator access stays open, and let it be locked. */
    function paintUnlock() {
        var slot = global.Dom.$("[data-admin-lock]");
        if (!slot) return;
        var record = currentUnlock();
        slot.innerHTML = "";
        if (!record || primaryAdmin) {
            slot.classList.add("hidden");
            return;
        }
        slot.classList.remove("hidden");

        var mins = minutesLeft(record);
        var badge = global.Dom.el("div", "unlock-badge");
        badge.innerHTML =
            '<span class="unlock-dot" aria-hidden="true"></span>' +
            '<span class="unlock-text tabular">' +
            global.Dom.esc(t("Administrator unlocked")) + " · <b>" +
            global.Dom.esc(t(mins + " min")) + "</b></span>" +
            '<button type="button" class="unlock-lock" data-action="lock-admin"' +
            ' title="' + global.Dom.esc(t("Lock administrator access now")) + '">' +
            global.Dom.esc(t("Lock now")) + "</button>";
        slot.appendChild(badge);

        global.Dom.on(badge.querySelector("[data-action='lock-admin']"), "click", function () {
            lockAdmin().then(function () {
                global.Loading.toast("Administrator access locked.", "info");
                if (isAdminOnly(location.pathname)) location.replace("/workspace");
            }).catch(function (err) { global.Loading.toast(err.message, "error"); });
        });
    }

    /**
     * Ask for the administrator password in a modal.
     * `onUnlock` receives {token, username, parentId}; `onCancel` fires when
     * the dialog is dismissed.
     */
    function adminGate(options, onUnlock, onCancel) {
        var opts = options || {};
        var admin = Session.getAdmin() || {};
        var known = !!admin.username;

        var overlay = global.Dom.el("div", "overlay");
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");
        var titleId = "admin-gate-title-" + Date.now();
        overlay.setAttribute("aria-labelledby", titleId);

        var heading = (opts.title || "This page") + " needs the administrator password";

        var modal = global.Dom.el("div", "modal");
        modal.innerHTML =
            '<div class="modal-head">' +
            "  <div>" +
            '    <span class="eyebrow">' + global.Dom.esc(t("Administrator approval")) + "</span>" +
            '    <h3 id="' + titleId + '">' + global.Dom.esc(t(heading)) + "</h3>" +
            "  </div>" +
            "</div>" +
            '<div class="modal-body">' +
            '  <p class="small muted">' +
            global.Dom.esc(t(opts.what || "This shows team-wide activity.")) +
            "</p>" +
            (known
                ? ""
                : '  <div class="field">' +
                  '    <label for="admin-gate-username">' +
                  global.Dom.esc(t("Administrator username")) + "</label>" +
                  '    <input type="text" id="admin-gate-username" class="input"' +
                  '           autocomplete="username">' +
                  "  </div>") +
            '  <div class="field">' +
            '    <label for="admin-gate-password">' +
            global.Dom.esc(t("Administrator password")) + "</label>" +
            '    <input type="password" id="admin-gate-password" class="input"' +
            '           autocomplete="off" autofocus>' +
            "  </div>" +
            '  <p class="form-msg" data-gate-msg></p>' +
            "</div>" +
            '<div class="modal-foot">' +
            '  <button type="button" class="btn btn-ghost" data-gate-cancel>' +
            global.Dom.esc(t(opts.cancelLabel || "Cancel")) + "</button>" +
            '  <button type="button" class="btn btn-primary" data-gate-unlock>' +
            global.Dom.esc(t(opts.confirmLabel || "Unlock")) + "</button>" +
            "</div>";
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        var input = modal.querySelector("#admin-gate-password");
        var usernameField = modal.querySelector("#admin-gate-username");
        var unlock = modal.querySelector("[data-gate-unlock]");
        var message = modal.querySelector("[data-gate-msg]");
        if (known) {
            input.placeholder = t("Password for " + admin.username);
        }

        function cancel() {
            close();
            if (typeof onCancel === "function") onCancel();
        }

        var close = trapModal(overlay, modal, cancel);
        (usernameField || input).focus();

        function submit() {
            var password = input.value;
            if (!password) {
                message.textContent = t("Enter the administrator password.");
                input.focus();
                return;
            }
            message.textContent = "";
            var username = known ? admin.username : usernameField.value.trim();
            if (!username) {
                message.textContent = t("Enter the administrator username.");
                usernameField.focus();
                return;
            }
            global.Loading.withButton(unlock, function () {
                return global.Api.post("ADMIN_APPROVE", {
                    Parent_id: (Session.getMember() || {}).parentId,
                    scope: opts.fresh ? "once" : "page",
                    username: username,
                    password: password
                }, { member: false, onUnauthorised: false });
            }).then(function (data) {
                var parentId = parseInt(data.Parent_id, 10);
                close();
                onUnlock({
                    token: data.admin_token,
                    username: data.username,
                    parentId: parentId
                });
            }).catch(function (err) {
                message.textContent = t(
                    err.message || "That password did not match. Check it and try again."
                );
                input.select();
            });
        }

        global.Dom.on(unlock, "click", submit);
        global.Dom.on(modal.querySelector("[data-gate-cancel]"), "click", cancel);
        global.Dom.on(overlay, "click", function (event) {
            if (event.target === overlay) cancel();
        });
        global.Dom.on(input, "keydown", function (event) {
            if (event.key === "Enter") { event.preventDefault(); submit(); }
        });
        if (usernameField) {
            global.Dom.on(usernameField, "keydown", function (event) {
                if (event.key === "Enter") { event.preventDefault(); input.focus(); }
            });
        }
        return { close: close };
    }

    function withAdmin(options) {
        var opts = options || {};
        var record = opts.fresh ? null : currentUnlock();
        function ask() {
            return new Promise(function (resolve, reject) {
                adminGate(opts, function (data) {
                    if (!opts.fresh) writeUnlock(data.username, data.parentId);
                    resolve(data.token);
                }, function () {
                    var err = new Error("Administrator approval was cancelled.");
                    err.cancelled = true;
                    reject(err);
                });
            });
        }
        if (!record) return ask();
        return global.Api.post("OVERRIDE_CHECK", { Parent_id: record.parentId },
            { onUnauthorised: false }).then(function (result) {
            if (result.allowed) return;
            forgetUnlock();
            return ask();
        });
    }

    function withAdminPage(page) {
        var backTo = Session.ready() ? "/workspace" : "/";
        var backLabel = Session.ready() ? "Back to chat" : "Back to sign in";
        return withAdmin({
            title: page.title,
            what: "This page shows " + page.what +
                  ". Enter the administrator password to open it.",
            confirmLabel: "Unlock",
            cancelLabel: backLabel
        }).catch(function (err) {
            if (err.cancelled) location.replace(backTo);
            throw err;
        });
    }

    var ADMIN_ONLY = {
        "/stats": { title: "Statistics", what: "team activity, blocks and trends" },
        "/team": { title: "Team", what: "every member and how their gate is configured" },
        "/shadow-ai": { title: "Shadow AI", what: "discovered AI activity and tool risk" }
    };

    function restoreAdmin() {
        return global.Api.post("ADMIN_SESSION", {}, { member: false, onUnauthorised: false }).then(function (data) {
            return data.success && data.Parent_id ? { parentId: data.Parent_id, username: data.username } : null;
        }).catch(function (err) {
            if (err.status === 401) return null;
            throw err;
        });
    }

    /** Verify the primary cookie first, even if this browser has member UI
        metadata. Otherwise ask the signed-in member for a read-only unlock. */
    function enterAdminPage(path) {
        return restoreAdmin().then(function (admin) {
            if (admin) {
                primaryAdmin = admin;
                Session.setAdmin(admin);
                forgetUnlock();
                paintMember();
                return { primary: true, parentId: admin.parentId };
            }
            Session.clearAdmin();
            if (Session.ready()) {
                return withAdminPage(ADMIN_ONLY[path]).then(function () {
                    return { primary: false, parentId: Session.ids().Parent_id };
                });
            }
            location.replace("/?tab=admin");
            var err = new Error("Your session has ended. Sign in again.");
            err.cancelled = true;
            throw err;
        });
    }

    function adminPageError(err) {
        if (err.cancelled) return;
        if (err.status === 401) {
            forgetUnlock();
            if (primaryAdmin) Session.clearAdmin();
            location.replace(primaryAdmin ? "/?tab=admin" : "/workspace");
        }
        global.Loading.toast(err.message, "error");
    }

    function isAdminOnly(path) {
        var key = (path || "").replace(/\/+$/, "") || "/";
        return Object.prototype.hasOwnProperty.call(ADMIN_ONLY, key);
    }

    /* ------------------------------------------------------------------
       The sidebar — drawer below 900px, collapsible column above it.
       Must stay in step with @media (max-width: 900px) in sidebar.css.
       ------------------------------------------------------------------ */

    var NARROW_QUERY = "(max-width: 900px)";

    var sidebar = null;
    var shell = null;
    var scrim = null;
    var narrowNow = null;

    function narrow() {
        return !!(global.matchMedia && global.matchMedia(NARROW_QUERY).matches);
    }

    function sidebarShown() {
        if (!sidebar) return false;
        return narrow()
            ? sidebar.classList.contains("is-open")
            : !(shell && shell.classList.contains("is-sidebar-collapsed"));
    }

    function showSidebar(open) {
        if (!sidebar) return;

        var asDrawer = narrow();
        sidebar.classList.toggle("is-open", asDrawer && open);
        if (shell) shell.classList.toggle("is-sidebar-collapsed", !asDrawer && !open);

        if (scrim) scrim.classList.toggle("is-open", asDrawer && open);

        global.Dom.$$("[data-action='toggle-sidebar']").forEach(function (btn) {
            btn.setAttribute("aria-expanded", open ? "true" : "false");
        });
    }

    function toggleSidebar() { showSidebar(!sidebarShown()); }

    function buildScrim() {
        var node = global.Dom.el("div", "sidebar-scrim");
        node.setAttribute("data-sidebar-scrim", "");
        node.setAttribute("aria-hidden", "true");
        global.document.body.appendChild(node);
        global.Dom.on(node, "click", function () { showSidebar(false); });
        return node;
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (global.Dom.$("[data-guard='member']") && !guard()) return;
        paintIcons(document);
        markActive();
        paintMember();
        paintUnlock();

        clearInterval(ticker);
        ticker = setInterval(paintUnlock, 30000);

        global.Dom.$$("[data-action='sign-out']").forEach(function (btn) {
            global.Dom.on(btn, "click", signOut);
        });

        global.Dom.on(global.document, "cybersyn:lang", function () {
            paintMember();
            paintUnlock();
        });

        sidebar = global.Dom.$("[data-sidebar]");
        if (!sidebar) return;

        shell = sidebar.closest ? sidebar.closest(".workspace, .layout")
                                : sidebar.parentNode;

        global.Dom.$$("[data-action='toggle-sidebar']").forEach(function (btn) {
            global.Dom.on(btn, "click", toggleSidebar);
        });

        narrowNow = narrow();
        showSidebar(!narrowNow);

        if (narrowNow) scrim = scrim || buildScrim();

        global.Dom.on(document, "keydown", function (event) {
            if (event.key !== "Escape") return;
            if (narrow() && sidebarShown()) {
                showSidebar(false);
                var toggle = global.Dom.$("[data-action='toggle-sidebar']");
                if (toggle && typeof toggle.focus === "function") toggle.focus();
            }
        });

        global.Dom.on(global, "resize", function () {
            var now = narrow();
            if (now === narrowNow) return;
            narrowNow = now;
            if (now) scrim = scrim || buildScrim();
            showSidebar(!now);
        });
    });

    /* Called by api.js when the server reports an expired session. */
    global.onSessionExpired = function () {
        global.Loading.toast("Your session ended. Sign in again to continue.", "warn");
        setTimeout(function () { location.replace("/"); }, 900);
    };

    global.Shell = {
        signOut: signOut,
        guard: guard,
        guardAdmin: guardAdmin,
        enterAdminPage: enterAdminPage,
        restoreAdmin: restoreAdmin,
        forgetAdminPage: forgetUnlock,
        adminPageError: adminPageError,
        confirm: confirmDialog,
        prompt: promptDialog,
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
