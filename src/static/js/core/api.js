/* ==========================================================================
   api.js — session storage and the one place that talks to the server.

   Every page needs the same three facts (who is signed in, which workspace,
   which member) and the same fetch wrapper. Putting them here means a page
   script never touches localStorage or builds a request body by hand.

   Two different tokens exist, and confusing them is a security bug:
     session_token — the team member's own session
     admin_token   — an administrator's, needed only to approve an override
   ========================================================================== */

(function (global) {
    "use strict";

    var ADMIN_KEY = "cybersyn_admin_token";
    var MEMBER_KEY = "cybersyn_member_token";
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
        /* ---- administrator ---- */
        getAdmin: function () { return read(ADMIN_META, null); },
        getAdminToken: function () { return localStorage.getItem(ADMIN_KEY) || null; },
        setAdmin: function (token, meta) {
            localStorage.setItem(ADMIN_KEY, token);
            write(ADMIN_META, meta || null);
        },
        clearAdmin: function () {
            localStorage.removeItem(ADMIN_KEY);
            write(ADMIN_META, null);
        },

        /* ---- team member ---- */
        getMember: function () { return read(MEMBER_META, null); },
        getMemberToken: function () { return localStorage.getItem(MEMBER_KEY) || null; },
        setMember: function (token, meta) {
            localStorage.setItem(MEMBER_KEY, token);
            write(MEMBER_META, meta || null);
        },
        clearMember: function () {
            localStorage.removeItem(MEMBER_KEY);
            write(MEMBER_META, null);
        },

        clearAll: function () {
            [ADMIN_KEY, MEMBER_KEY, ADMIN_META, MEMBER_META].forEach(function (k) {
                localStorage.removeItem(k);
            });
        },

        /* Convenience: the identifiers every request body carries. */
        ids: function () {
            var m = Session.getMember() || {};
            return {
                Parent_id: m.parentId || null,
                Employee_id: m.employeeId || null,
                session_token: Session.getMemberToken()
            };
        },

        ready: function () {
            var m = Session.getMember() || {};
            return !!(m.parentId && m.employeeId && Session.getMemberToken());
        }
    };

    /**
     * POST JSON and parse the reply.
     * Rejects with an Error carrying `.status` and `.body` so callers can
     * tell "your session ended" (401) from "the server is unhappy" (500).
     */
    function post(path, body, options) {
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

        return fetch(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
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
                    var message = result.data.error_message ||
                        result.data.message ||
                        result.data.reason ||
                        ("The server could not finish that request (" + result.status + "). Try again.");
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
        return fetch(path).then(function (res) { return res.json(); });
    }

    global.Api = { post: post, get: get, Session: Session };
})(window);
