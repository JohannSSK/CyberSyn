/* ==========================================================================
   api.js — session storage and the one place that talks to the server.

   Every page needs the same facts (who is signed in, which workspace, which
   member) and the same fetch wrapper. Only UI metadata is kept in
   localStorage; session credentials are HttpOnly cookies, and one-time
   approvals are passed directly to the single request they authorise.
   ========================================================================== */

(function (global) {
    "use strict";

    var routes = {};
    try {
        routes = JSON.parse((document.body && document.body.dataset.routes) || "{}");
    } catch (_err) {
        routes = {};
    }

    // Purge credentials left behind by earlier browser builds.
    try {
        localStorage.removeItem("cybersyn_admin_token");
        localStorage.removeItem("cybersyn_member_token");
        sessionStorage.removeItem("cybersyn_admin_unlock");
    } catch (_err) { /* storage unavailable */ }

    var ADMIN_META = "cybersyn_admin_meta";
    var MEMBER_META = "cybersyn_member_meta";

    function read(key, fallback) {
        try {
            var raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (err) {
            return fallback;
        }
    }

    function write(key, value) {
        try {
            if (value === null || value === undefined) localStorage.removeItem(key);
            else localStorage.setItem(key, JSON.stringify(value));
        } catch (err) { /* private mode: session stays in memory only */ }
    }

    var Session = {
        /* ---- administrator metadata ---- */
        getAdmin: function () { return read(ADMIN_META, null); },
        setAdmin: function (meta) {
            write(ADMIN_META, meta ? { parentId: meta.parentId, username: meta.username } : null);
        },
        clearAdmin: function () { write(ADMIN_META, null); },

        /* ---- team member metadata ---- */
        getMember: function () { return read(MEMBER_META, null); },
        setMember: function (meta) {
            write(MEMBER_META, meta
                ? { parentId: meta.parentId, employeeId: meta.employeeId, username: meta.username }
                : null);
        },
        clearMember: function () { write(MEMBER_META, null); },

        clearAll: function () {
            Session.clearAdmin();
            Session.clearMember();
        },

        /* Convenience: the identifiers every request body carries. */
        ids: function () {
            var m = Session.getMember() || {};
            return {
                Parent_id: m.parentId || null,
                Employee_id: m.employeeId || null
            };
        },

        ready: function () {
            var m = Session.getMember() || {};
            return !!(m.parentId && m.employeeId);
        }
    };

    /**
     * POST JSON and parse the reply.
     * Rejects with an Error carrying `.status` and `.body` so callers can
     * tell "your session ended" (401) from "the server is unhappy" (500).
     */
    function clip(text, max) {
        var clean = String(text || "").replace(/\s+/g, " ").trim();
        return clean.length > max ? clean.slice(0, max - 1).trim() + "…" : clean;
    }

    /* Append a minimal one-line remedy to bare-fact server error strings
       while keeping backend API payloads untouched and every line <= 160 chars. */
    var EXACT_REMEDIES = {
        "No API_KEY provided.":
            "No API_KEY provided. Ask your administrator to add a provider key in Settings.",
        "Invalid password.":
            "Invalid password. Check it and try again.",
        "Invalid username or password.":
            "Invalid username or password. Check both fields and try again.",
        "Invalid employee password.":
            "Invalid employee password. Check it and try again.",
        "Invalid employee username or password.":
            "Invalid employee username or password. Check both fields and try again.",
        "Current password is incorrect.":
            "Current password is incorrect. Check it and try again.",
        "That chat was not found.":
            "That chat was not found. Refresh the list or start a new chat.",
        "That chat was not found for this team member.":
            "That chat was not found for this team member. Start a new chat or refresh.",
        "That message was not found.":
            "That message was not found. Reload this chat to see current messages.",
        "That message was not found in this chat.":
            "That message was not found in this chat. Reload to see current messages.",
        "Title cannot be empty.":
            "Title cannot be empty. Type a short name or press Esc to cancel.",
        "The message cannot be empty.":
            "The message cannot be empty. Type a line before saving.",
        "Only a message you sent can be regenerated.":
            "Only a message you sent can be regenerated. Pick one of your prompts instead.",
        "Paste an API key first.":
            "Paste an API key first, then select Refresh list.",
        "That key returned no models.":
            "That key returned no models. Check the provider and key, then try again.",
        "That key returned no usable models.":
            "That key returned no usable models. Check the provider and key, then try again.",
        "Adding or removing a team member needs a valid administrator session for this workspace.":
            "Adding or removing a team member needs an administrator session. Sign in again.",
        "Changing these settings needs the administrator password.":
            "Changing these settings needs the administrator password. Approve to save.",
        "Bypassing the checks needs the administrator password.":
            "Bypassing the checks needs the administrator password. Enter it to send once.",
        "The new username is the same as the current one.":
            "The new username is the same as the current one. Pick a different username.",
        "The new password must differ from the current one.":
            "The new password must differ from the current one. Choose a new password.",
        "Your session has ended. Sign in again.":
            "Your session has ended. Sign in again."
    };

    function withRemedy(raw) {
        if (!raw) return raw;
        var text = String(raw).trim();
        if (Object.prototype.hasOwnProperty.call(EXACT_REMEDIES, text)) {
            return EXACT_REMEDIES[text];
        }
        var m;
        m = text.match(/^Not sent — (a check|checks) could not run \((.+)\)\.$/);
        if (m) {
            return "Not sent — " + m[1] + " could not run (" + clip(m[2], 38) +
                "). Try a smaller paste, or ask your administrator to approve this once.";
        }
        m = text.match(/^AI API Error:\s*(.+)$/);
        if (m) {
            var detail = clip(m[1].replace(/\.+$/, ""), 52);
            return "AI API Error: " + detail +
                ". Check the model and key in Settings, or try again.";
        }
        m = text.match(/^Admin (?:username )?'(.+)' not found\.$/);
        if (m) {
            return "Admin '" + clip(m[1], 28) +
                "' not found. Check the spelling or create an account.";
        }
        m = text.match(/^Admin '(.+)' already exists\.$/);
        if (m) {
            return "Admin '" + clip(m[1], 28) +
                "' already exists. Choose a different username.";
        }
        m = text.match(/^Employee '(.+)' already exists under Parent_id \d+\.$/);
        if (m) {
            return "Employee '" + clip(m[1], 28) +
                "' already exists here. Choose a different username.";
        }
        m = text.match(/^Employee '(.+)' not found under Parent_id \d+\.$/);
        if (m) {
            return "Employee '" + clip(m[1], 28) +
                "' not found here. Check the spelling and try again.";
        }
        m = text.match(/^Server error:\s*(.+)$/);
        if (m) {
            return "Server error (" + clip(m[1], 48) +
                "). Retry in a moment, or check the gateway log.";
        }
        return text;
    }

    function post(route, body, options) {
        var opts = options || {};
        var payload = Object.assign({}, body || {});
        if (opts.member !== false && Session.ready()) {
            payload = Object.assign({}, Session.ids(), payload);
        }

        var controller = null;
        var timer = null;
        if (opts.timeout) {
            controller = new AbortController();
            timer = setTimeout(function () { controller.abort(); }, opts.timeout);
        }

        return fetch(routes[route] || route, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CyberSyn-Request": "1",
                "X-CyberSyn-Session": "cookie"
            },
            body: JSON.stringify(payload),
            signal: controller ? controller.signal : undefined
        })
            .then(function (res) {
                return res.json().catch(function () { return {}; }).then(function (data) {
                    return { ok: res.ok, status: res.status, data: data };
                });
            })
            .then(function (result) {
                // A dead session is the same on every page: forget it and bounce.
                if (result.status === 401 && opts.onUnauthorised !== false) {
                    Session.clearMember();
                    if (typeof global.onSessionExpired === "function") {
                        global.onSessionExpired();
                    }
                }
                if (!result.ok) {
                    var raw = result.data.error_message ||
                        result.data.message ||
                        result.data.reason;
                    var message = raw
                        ? withRemedy(raw)
                        : ("The server could not finish that request (" + result.status + "). Try again.");
                    var err = new Error(message);
                    err.status = result.status;
                    err.body = result.data;
                    throw err;
                }
                return result.data;
            })
            .catch(function (err) {
                if (err.name === "AbortError") {
                    var timeoutErr = new Error(
                        "That took longer than expected. Check your connection and try again."
                    );
                    timeoutErr.status = 408;
                    throw timeoutErr;
                }
                if (err.status) throw err;
                var netErr = new Error(
                    "Could not reach the gateway. Check that the server is running and try again."
                );
                netErr.status = 0;
                throw netErr;
            })
            .finally(function () { if (timer) clearTimeout(timer); });
    }

    function get(path) {
        return fetch(path, { credentials: "same-origin" }).then(function (res) { return res.json(); });
    }

    global.Api = { post: post, get: get, withRemedy: withRemedy, Session: Session };
})(window);
