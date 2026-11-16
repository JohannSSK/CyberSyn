/* ==========================================================================
   auth.js — the two-step sign-in portal.

   Step 1: the administrator signs in. Step 2: a team member signs in, which
   is what actually opens a workspace. The administrator token is kept
   separately from the member token, because the two grant different powers.
   ========================================================================== */

(function () {
    "use strict";

    var Session = window.Api.Session;
    var Loading = window.Loading;
    var $ = window.Dom.$;

    var admin = {
        step: $("#admin-step"),
        username: $("#admin-username"),
        password: $("#admin-password"),
        msg: $("#admin-msg"),
        login: $("#btn-admin-login"),
        register: $("#btn-admin-register"),
        remove: $("#btn-admin-delete")
    };

    var employee = {
        step: $("#employee-card"),
        badge: $("#admin-session-badge"),
        adminLabel: $("#active-admin-label"),
        username: $("#employee-username"),
        password: $("#employee-password"),
        msg: $("#employee-msg"),
        login: $("#btn-employee-login"),
        create: $("#btn-employee-create"),
        remove: $("#btn-employee-delete")
    };

    var parentId = null;

    function showError(node, message) {
        node.textContent = message || "";
    }

    /* ------------------------------------------------------------------
       Step 1 — administrator
       ------------------------------------------------------------------ */

    function adminLogin() {
        showError(admin.msg, "");
        var username = admin.username.value.trim();
        var password = admin.password.value;

        if (!username || !password) {
            showError(admin.msg, "Enter your username and password.");
            admin.username.focus();
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
            revealMemberStep(username);
        }).catch(function (err) {
            showError(admin.msg, err.message);
            Loading.toast(err.message, "error");
        });
    }

    /** Add or remove an administrator, using the credentials in step 1. */
    function adminManage(method) {
        var username = admin.username.value.trim();
        var password = admin.password.value;
        if (!username || !password) {
            showError(admin.msg, "Fill in both fields first, then choose "
                + (method === "add" ? "create" : "delete") + ".");
            return;
        }
        var removing = method === "remove";
        var confirmed = !removing || confirm(
            "Delete the administrator '" + username + "'?\n\n"
            + "Their team members, settings and history are removed with them. This cannot be undone."
        );
        if (!confirmed) return;

        var button = removing ? admin.remove : admin.register;
        Loading.withButton(button, function () {
            return window.Api.post("/api/admin",
                { method: method, username: username, password: password },
                { member: false, onUnauthorised: false });
        }).then(function () {
            Loading.toast(removing ? "Administrator deleted." : "Administrator created. Sign in now.", "success");
            if (removing) admin.password.value = "";
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

        if (!username || !password) {
            showError(employee.msg, "Enter the team member's username and password.");
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
            Loading.toast("Welcome back, " + (data.username || username) + ".", "success");
            location.href = "/workspace";
        }).catch(function (err) {
            showError(employee.msg, err.message);
            Loading.toast(err.message, "error");
        });
    }

    /** Create or remove a team member under the signed-in administrator. */
    function employeeManage(method) {
        var username = employee.username.value.trim();
        var password = employee.password.value;
        if (!username || !password) {
            showError(employee.msg, "Fill in both fields first, then choose "
                + (method === "add" ? "add" : "remove") + ".");
            return;
        }
        var removing = method === "remove";
        var confirmed = !removing || confirm(
            "Remove '" + username + "'?\n\nTheir chats and settings are removed. "
            + "Team statistics are kept."
        );
        if (!confirmed) return;

        var button = removing ? employee.remove : employee.create;
        Loading.withButton(button, function () {
            return window.Api.post("/api/admin/employee",
                { method: method, Parent_id: parentId, username: username, password: password },
                { member: false, onUnauthorised: false });
        }).then(function () {
            Loading.toast(removing ? "Team member removed." : "Team member added. Sign in now.", "success");
            employee.password.value = "";
        }).catch(function (err) {
            showError(employee.msg, err.message);
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    window.Dom.on(admin.login, "click", adminLogin);
    window.Dom.on(admin.register, "click", function () { adminManage("add"); });
    window.Dom.on(admin.remove, "click", function () { adminManage("remove"); });

    window.Dom.on(employee.login, "click", employeeLogin);
    window.Dom.on(employee.create, "click", function () { employeeManage("add"); });
    window.Dom.on(employee.remove, "click", function () { employeeManage("remove"); });
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
                revealMemberStep(data.username || "administrator");
            })
            .catch(function () { Session.clearAdmin(); });
    })();
})();
