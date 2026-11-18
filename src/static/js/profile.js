/* ==========================================================================
   profile.js — account details, username and password changes.

   Both changes require the current password so a copied session token alone
   cannot change a member's credentials.
   ========================================================================== */

(function () {
    "use strict";

    if (!window.Shell.guard()) return;

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var Shell = window.Shell;
    var Session = Api.Session;
    var $ = Dom.$;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    var cachedSettings = null;

    var nodes = {
        username: $("#info-username"),
        employeeId: $("#info-employee-id"),
        parentId: $("#info-parent-id"),
        checks: $("#info-checks"),
        model: $("#info-model"),
        key: $("#info-key"),

        formUsername: $("#form-username"),
        newUsername: $("#input-username-new"),
        usernamePassword: $("#input-username-password"),
        saveUsername: $("#btn-save-username"),
        msgUsername: $("#msg-username"),

        formPassword: $("#form-password"),
        currentPassword: $("#input-password-current"),
        newPassword: $("#input-password-new"),
        savePassword: $("#btn-save-password"),
        msgPassword: $("#msg-password")
    };

    function showMessage(node, message, ok) {
        node.textContent = message ? t(message) : "";
        node.classList.toggle("ok", !!ok);
    }

    function paintSettings() {
        if (!cachedSettings) return;
        var data = cachedSettings;
        var on = ["check1", "check2", "check3"].filter(function (k) {
            return data[k] !== false;
        }).length;
        nodes.checks.innerHTML = "";
        var cls = on === 0 ? "badge badge-warn" : (on === 3 ? "badge badge-accent" : "badge");
        nodes.checks.appendChild(Dom.el("span", cls, t(on + " of 3 active")));
        nodes.model.textContent = data.MODEL_NAME || "gpt-4o-mini";
        nodes.key.textContent = data.API_KEY_MASK || t("No key saved");
    }

    function load() {
        var member = Session.getMember() || {};
        nodes.username.textContent = member.username || "—";
        nodes.employeeId.textContent = member.employeeId || "—";
        nodes.parentId.textContent = member.parentId || "—";

        return Api.post("/api/admin/employee/settings", {}).then(function (data) {
            cachedSettings = data || {};
            paintSettings();
        });
    }

    function saveUsername(event) {
        event.preventDefault();
        showMessage(nodes.msgUsername, "");
        var next = nodes.newUsername.value.trim();
        var password = nodes.usernamePassword.value;
        if (!next || !password) {
            showMessage(nodes.msgUsername, "Fill in both the new username and your current password.");
            return;
        }

        Loading.withButton(nodes.saveUsername, function () {
            return Api.post("/api/admin/employee/account", {
                action: "username",
                new_username: next,
                current_password: password
            });
        }).then(function () {
            var member = Session.getMember() || {};
            member.username = next;
            Session.setMember(Session.getMemberToken(), member);
            nodes.username.textContent = next;
            Shell.paintMember();
            nodes.newUsername.value = "";
            nodes.usernamePassword.value = "";
            showMessage(nodes.msgUsername, "Username updated.", true);
            Loading.toast("Username updated.", "success");
        }).catch(function (err) {
            showMessage(nodes.msgUsername, err.message);
            Loading.toast(err.message, "error");
        });
    }

    function savePassword(event) {
        event.preventDefault();
        showMessage(nodes.msgPassword, "");
        var current = nodes.currentPassword.value;
        var next = nodes.newPassword.value;
        if (!current || !next) {
            showMessage(nodes.msgPassword, "Fill in both your current password and a new password.");
            return;
        }
        if (next === current) {
            showMessage(nodes.msgPassword, "Pick a new password that differs from your current one.");
            return;
        }

        Loading.withButton(nodes.savePassword, function () {
            return Api.post("/api/admin/employee/account", {
                action: "password",
                new_password: next,
                current_password: current
            });
        }).then(function () {
            nodes.currentPassword.value = "";
            nodes.newPassword.value = "";
            showMessage(nodes.msgPassword, "Password updated.", true);
            Loading.toast("Password updated.", "success");
        }).catch(function (err) {
            showMessage(nodes.msgPassword, err.message);
            Loading.toast(err.message, "error");
        });
    }

    Dom.on(nodes.formUsername, "submit", saveUsername);
    Dom.on(nodes.formPassword, "submit", savePassword);
    Dom.on(document, "cybersyn:lang", paintSettings);

    load().catch(function (err) { Loading.toast(err.message, "error"); });
})();
