/* ==========================================================================
   api.js — session storage and the one place that talks to the server.

   Every page needs the same three facts (who is signed in, which workspace,
   which member) and the same fetch wrapper. Putting them here means a page
   script never touches localStorage or builds a request body by hand.

   Only UI metadata is stored here. Session credentials are HttpOnly cookies;
   a one-time approval is passed directly to the request it authorises.
   ========================================================================== */

(function (global) {
    "use strict";

    var routes = JSON.parse(document.body.dataset.routes || "{}");
    // Purge credentials left behind by earlier browser builds.
    try {
        localStorage.removeItem("cybersyn_admin_token");
        localStorage.removeItem("cybersyn_member_token");
        sessionStorage.removeItem("cybersyn_admin_unlock");
    } catch (err) { /* storage unavailable */ }
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
        setAdmin: function (meta) {
            write(ADMIN_META, { parentId: meta.parentId, username: meta.username });
        },
        clearAdmin: function () { write(ADMIN_META, null); },
        getMember: function () { return read(MEMBER_META, null); },
        setMember: function (meta) {
            write(MEMBER_META, { parentId: meta.parentId, employeeId: meta.employeeId, username: meta.username });
        },
        clearMember: function () { write(MEMBER_META, null); },
        clearAll: function () { Session.clearAdmin(); Session.clearMember(); },

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

        return fetch(routes[route], {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CyberSyn-Request": "1", "X-CyberSyn-Session": "cookie" },
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
                        ("Request failed (" + result.status + ")");
                    var err = new Error(message);
                    err.status = result.status;
                    err.body = result.data;
                    throw err;
                }
                return result.data;
            })
            .catch(function (err) {
                if (err.name === "AbortError") {
                    var timeoutErr = new Error("The request took too long. Try again.");
                    timeoutErr.status = 408;
                    throw timeoutErr;
                }
                if (err.status) throw err;
                var netErr = new Error("Could not reach the server.");
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
