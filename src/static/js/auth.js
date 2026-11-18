/* ==========================================================================
   auth.js — the two-step sign-in portal.

   Step 1: the administrator signs in. Step 2: a team member signs in, which
   is what actually opens a workspace. The administrator token is kept
   separately from the member token, because the two grant different powers.

   This page only signs people in. Creating or deleting an account happens on
   its own page (/create-admin, /delete-admin, /create-member,
   /delete-member); reusing these boxes for those meant the same two fields
   stood for four different actions.
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
            return window.Api.post("ADMIN_LOGIN",
                { username: username, password: password },
                { member: false, onUnauthorised: false });
        }).then(function (data) {
            parentId = parseInt(data.Parent_id, 10);
            Session.setAdmin({
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

    function revealMemberStep(username) {
        admin.step.classList.add("hidden");
        employee.step.classList.remove("hidden");
        employee.badge.classList.remove("hidden");
        employee.adminLabel.textContent = username;
        employee.username.focus();
    }

    function backToAdmin() {
        window.Api.post("ADMIN_LOGOUT", {}, { member: false, onUnauthorised: false });
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
            return window.Api.post("EMPLOYEE_LOGIN",
                { Parent_id: parentId, username: username, password: password },
                { member: false, onUnauthorised: false });
        }).then(function (data) {
            Session.setMember({
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
        var meta = Session.getAdmin();
        if (!meta || !meta.parentId) return;
        window.Api.post("ADMIN_SESSION", {},
            { member: false, onUnauthorised: false })
            .then(function (data) {
                if (!data.success) { Session.clearAdmin(); return; }
                parentId = parseInt(data.Parent_id, 10);
                Session.setAdmin({ parentId: parentId, username: data.username });
                revealMemberStep(data.username || "administrator");
            })
            .catch(function () { Session.clearAdmin(); });
    })();
})();
