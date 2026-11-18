/* ==========================================================================
   account_pages.js — create and delete an account, one page per action.

   Each action sits on its own screen with dedicated fields and buttons.
   Destructive actions open a calm confirmation modal naming what is deleted
   and what stays in the audit log before sending the request.
   ========================================================================== */

(function () {
    "use strict";

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var Session = Api.Session;
    var $ = Dom.$;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    function message(id, text) {
        var node = $(id);
        if (node) node.textContent = text ? t(text) : "";
    }

    function home() {
        window.location.href = "/?tab=admin";
    }

    /* Every browser page loads shell.js first and gets the styled .modal.
       Unit tests that evaluate account_pages.js in isolation without shell.js
       drive window.confirm directly, so their harness keeps working too. */
    function confirmRemoval(options) {
        if (window.Shell && typeof window.Shell.confirm === "function") {
            return window.Shell.confirm(options);
        }
        return Promise.resolve(!!window.confirm(options.title));
    }

    /** Wire a submit button plus Enter-to-submit on its fields. */
    function onSubmit(button, fields, task) {
        if (!button) return;
        Dom.on(button, "click", function () {
            Loading.withButton(button, task).catch(function () { });
        });
        fields.forEach(function (field) {
            if (!field) return;
            Dom.on(field, "keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    button.click();
                }
            });
        });
    }

    /** True when the two password fields agree; explains what to fix if not. */
    function passwordsMatch(one, two, msgId) {
        if (!one.value) {
            message(msgId, "Choose a password first.");
            one.focus();
            return false;
        }
        if (one.value !== two.value) {
            message(msgId, "Those passwords do not match. Type the same password in both boxes.");
            two.focus();
            return false;
        }
        return true;
    }

    /* ------------------------------------------------------------------
       Administrator
       ------------------------------------------------------------------ */

    (function createAdmin() {
        var button = $("#btn-create-admin");
        if (!button) return;

        var username = $("#new-admin-username");
        var password = $("#new-admin-password");
        var confirmField = $("#new-admin-confirm");
        var signupToken = $("#signup-token");
        var msg = "#create-admin-msg";

        $("#admin-password-rule").textContent = t(
            "At least 8 characters, with at least one letter and one number."
        );

        onSubmit(button, [username, password, confirmField, signupToken], function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Choose a username to continue.");
                username.focus();
                return Promise.resolve();
            }
            if (!passwordsMatch(password, confirmField, msg)) return Promise.resolve();

            return Api.post("ADMIN",
                { method: "add", username: name, password: password.value,
                  signup_token: signupToken ? signupToken.value : "" },
                { member: false, onUnauthorised: false }
            ).then(function () {
                Loading.toast("Administrator account created. You can sign in now.", "success");
                home();
            }).catch(function (err) {
                message(msg, err.message);
            });
        });
    })();

    (function deleteAdmin() {
        var button = $("#btn-delete-admin");
        if (!button) return;

        var username = $("#del-admin-username");
        var password = $("#del-admin-password");
        var msg = "#delete-admin-msg";

        Dom.on(button, "click", function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Type the administrator username you want to delete.");
                username.focus();
                return;
            }
            if (!password.value) {
                message(msg, "Type that account's password to confirm.");
                password.focus();
                return;
            }

            confirmRemoval({
                eyebrow: "Remove account",
                title: "Delete administrator " + name + "?",
                lost: "Removed: this workspace, member accounts, settings, sessions and imported discovery logs.",
                kept: "Kept: block and activity log rows stay in the local database.",
                confirmLabel: "Delete account",
                cancelLabel: "Keep account",
                danger: true
            }).then(function (accepted) {
                if (!accepted) return null;
                return Loading.withButton(button, function () {
                    return Api.post("ADMIN",
                        { method: "remove", username: name, password: password.value },
                        { member: false, onUnauthorised: false });
                }).then(function () {
                    Session.clearAll();
                    Loading.toast("Administrator account deleted.", "success");
                    home();
                }).catch(function (err) {
                    message(msg, err.message);
                });
            });
        });

        [username, password].forEach(function (field) {
            if (!field) return;
            Dom.on(field, "keydown", function (event) {
                if (event.key === "Enter") { event.preventDefault(); button.click(); }
            });
        });
    })();

    /* ------------------------------------------------------------------
       Team members — scoped to the signed-in administrator's workspace
       ------------------------------------------------------------------ */

    function adminContext() {
        var meta = Session.getAdmin() || {};
        var parentId = parseInt(meta.parentId, 10);
        if (!parentId) return null;
        return { parentId: parentId, username: meta.username };
    }

    function requireAdmin() {
        var context = adminContext();
        if (context) return context;
        Loading.toast("Sign in as an administrator on the sign-in screen first.", "warn");
        setTimeout(home, 800);
        return null;
    }

    (function createMember() {
        var button = $("#btn-create-member");
        if (!button) return;

        var username = $("#new-member-username");
        var password = $("#new-member-password");
        var confirmField = $("#new-member-confirm");
        var msg = "#create-member-msg";

        var context = requireAdmin();
        if (!context) return;
        var label = $("#active-admin-label");
        if (label && context.username) label.textContent = context.username;

        onSubmit(button, [username, password, confirmField], function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Choose a username to continue.");
                username.focus();
                return Promise.resolve();
            }
            if (!passwordsMatch(password, confirmField, msg)) return Promise.resolve();

            return Api.post("EMPLOYEE",
                { method: "add", Parent_id: context.parentId,
                  username: name, password: password.value },
                { member: false, onUnauthorised: false }
            ).then(function () {
                Loading.toast(name + " added — they can sign in now.", "success");
                home();
            }).catch(function (err) {
                message(msg, err.message);
            });
        });
    })();

    (function deleteMember() {
        var button = $("#btn-delete-member");
        if (!button) return;

        var username = $("#del-member-username");
        var password = $("#del-member-password");
        var picker = $("#member-picker");
        var msg = "#delete-member-msg";

        var context = requireAdmin();
        if (!context) return;
        var label = $("#active-admin-label");
        if (label && context.username) label.textContent = context.username;

        if (picker) {
            Api.post("TEAM_LIST", {}, { member: false, onUnauthorised: false }).then(function (data) {
                (data.members || []).forEach(function (m) {
                    picker.add(new Option(m.username, m.username));
                });
                Dom.on(picker, "change", function () { username.value = picker.value; });
            }).catch(function (err) { message(msg, err.message); });
        }

        Dom.on(button, "click", function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Type the member username you want to remove.");
                username.focus();
                return;
            }
            if (!password.value) {
                message(msg, "Enter the administrator password.");
                password.focus();
                return;
            }

            confirmRemoval({
                eyebrow: "Remove member",
                title: "Remove " + name + " from this workspace?",
                lost: "Removed: their member account, saved settings and access to their chats.",
                kept: "Kept: block and activity log rows stay in team statistics.",
                confirmLabel: "Remove member",
                cancelLabel: "Keep member",
                danger: true
            }).then(function (accepted) {
                if (!accepted) return null;
                return Loading.withButton(button, function () {
                    return Api.post("EMPLOYEE",
                        { method: "remove", Parent_id: context.parentId,
                          username: name, admin_password: password.value },
                        { member: false, onUnauthorised: false });
                }).then(function () {
                    Loading.toast(name + " removed from this workspace.", "success");
                    home();
                }).catch(function (err) {
                    message(msg, err.message);
                });
            });
        });

        [username, password].forEach(function (field) {
            if (!field) return;
            Dom.on(field, "keydown", function (event) {
                if (event.key === "Enter") { event.preventDefault(); button.click(); }
            });
        });
    })();
})();
