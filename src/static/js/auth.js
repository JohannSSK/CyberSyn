/* ==========================================================================
   auth.js — the two-step sign-in portal.

   Step 1: the administrator signs in. Step 2: a team member signs in to open
   their workspace. Administrator and member tokens live separately because
   each grants a different scope of access.
   ========================================================================== */

(function () {
    "use strict";

    var Session = window.Api.Session;
    var Loading = window.Loading;
    var $ = window.Dom.$;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    var admin = {
        step: $("#admin-step"),
        username: $("#admin-username"),
        password: $("#admin-password"),
        msg: $("#admin-msg"),
        login: $("#btn-admin-login")
    };

    var employee = {
        step: $("#employee-card"),
        badge: $("#admin-session-badge"),
        adminLabel: $("#active-admin-label"),
        username: $("#employee-username"),
        password: $("#employee-password"),
        msg: $("#employee-msg"),
        login: $("#btn-employee-login")
    };

    var parentId = null;

    function showError(node, message) {
        node.textContent = message ? t(message) : "";
    }

    /* ------------------------------------------------------------------
       Step 1 — administrator
       ------------------------------------------------------------------ */

    function adminLogin() {
        showError(admin.msg, "");
        var username = admin.username.value.trim();
        var password = admin.password.value;

        if (!username) {
            showError(admin.msg, "Type your administrator username to continue.");
            admin.username.focus();
            return;
        }
        if (!password) {
            showError(admin.msg, "Type your password to continue.");
            admin.password.focus();
            return;
        }

        Loading.withButton(admin.login, function () {
            return window.Api.post("/api/admin/login",
                { username: username, password: password },
                { member: false, onUnauthorised: false });
        }).then(function (data) {
            parentId = parseInt(data.Parent_id, 10);
            Session.setAdmin(data.session_token, {
                parentId: parentId,
                username: data.username || username
            });
            admin.password.value = "";
            revealMemberStep(data.username || username);
        }).catch(function (err) {
            showError(admin.msg, err.message);
            Loading.toast(err.message, "error");
        });
    }

    function revealMemberStep(username) {
        admin.step.classList.add("hidden");
        employee.step.classList.remove("hidden");
        employee.badge.classList.remove("hidden");
        employee.adminLabel.textContent = username;
        employee.username.focus();
    }

    function backToAdmin() {
        var token = Session.getAdminToken();
        if (token) {
            window.Api.post("/api/admin/logout", { token: token },
                { member: false, onUnauthorised: false }).catch(function () {});
        }
        Session.clearAdmin();
        Session.clearMember();
        parentId = null;
        employee.step.classList.add("hidden");
        employee.badge.classList.add("hidden");
        showError(employee.msg, "");
        admin.step.classList.remove("hidden");
        admin.username.focus();
    }

    /* ------------------------------------------------------------------
       Step 2 — team member
       ------------------------------------------------------------------ */

    function employeeLogin() {
        showError(employee.msg, "");
        var username = employee.username.value.trim();
        var password = employee.password.value;

        if (!username) {
            showError(employee.msg, "Type the team member's username first.");
            employee.username.focus();
            return;
        }
        if (!password) {
            showError(employee.msg, "Type the team member's password to open the workspace.");
            employee.password.focus();
            return;
        }

        Loading.withButton(employee.login, function () {
            return window.Api.post("/api/admin/employee/login",
                { Parent_id: parentId, username: username, password: password },
                { member: false, onUnauthorised: false });
        }).then(function (data) {
            Session.setMember(data.session_token, {
                parentId: parentId,
                employeeId: parseInt(data.Employee_id, 10),
                username: data.username || username
            });
            employee.password.value = "";
            Loading.toast("Signed in as " + (data.username || username) + ".", "success");
            location.href = "/workspace";
        }).catch(function (err) {
            showError(employee.msg, err.message);
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    window.Dom.on(admin.login, "click", adminLogin);
    window.Dom.on(employee.login, "click", employeeLogin);
    window.Dom.on($("#btn-admin-logout"), "click", backToAdmin);

    [admin.username, admin.password].forEach(function (input) {
        window.Dom.on(input, "keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); adminLogin(); }
        });
    });
    [employee.username, employee.password].forEach(function (input) {
        window.Dom.on(input, "keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); employeeLogin(); }
        });
    });

    /* A remembered administrator skips straight to step 2. */
    (function restore() {
        var token = Session.getAdminToken();
        var meta = Session.getAdmin();
        if (!token || !meta || !meta.parentId) return;
        window.Api.post("/api/admin/session", { token: token },
            { member: false, onUnauthorised: false })
            .then(function (data) {
                if (!data.success) { Session.clearAdmin(); return; }
                parentId = parseInt(data.Parent_id, 10);
                Session.setAdmin(token, { parentId: parentId, username: data.username });
                revealMemberStep(data.username || "Admin");
            })
            .catch(function () { Session.clearAdmin(); });
    })();
})();
