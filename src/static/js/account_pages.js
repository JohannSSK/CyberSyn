/* ==========================================================================
   account_pages.js — create and delete an account, one page per action.

   These four actions used to share the sign-in boxes: the same two fields
   meant "sign in", "create" or "delete" depending on which link you had
   last clicked, and the only feedback was a line of text that also served
   as the login error. Each action now has its own page, its own fields and
   its own button, so what a field is for never depends on remembered state.

   One script serves all four because they differ only in which endpoint
   they call and what they ask for; it wires whichever page it is loaded on.
   ========================================================================== */

(function () {
    "use strict";

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var Session = Api.Session;
    var $ = Dom.$;

    function message(id, text) {
        var node = $(id);
        if (node) node.textContent = text || "";
    }

    function home() {
        window.location.href = "/";
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

    /** True when the two password fields agree; explains itself when not. */
    function passwordsMatch(one, two, msgId, label) {
        if (one.value !== two.value) {
            message(msgId, "Those passwords do not match.");
            two.focus();
            return false;
        }
        if (!one.value) {
            message(msgId, "Enter " + label + " password.");
            one.focus();
            return false;
        }
        return true;
    }

    /* ------------------------------------------------------------------
       Administrator
       ------------------------------------------------------------------ */

    /* Creating an administrator is the one page with no session at all, so
       it also carries the password rules the server enforces. */
    (function createAdmin() {
        var button = $("#btn-create-admin");
        if (!button) return;

        var username = $("#new-admin-username");
        var password = $("#new-admin-password");
        var confirm = $("#new-admin-confirm");
        var msg = "#create-admin-msg";

        $("#admin-password-rule").textContent =
            "At least 8 characters, including a letter and a number.";

        onSubmit(button, [username, password, confirm], function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Choose a username.");
                username.focus();
                return Promise.resolve();
            }
            if (!passwordsMatch(password, confirm, msg, "a")) return Promise.resolve();

            return Api.post("/api/admin",
                { method: "add", username: name, password: password.value },
                { member: false, onUnauthorised: false }
            ).then(function () {
                Loading.toast("Administrator created. Sign in with it now.", "success");
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

        onSubmit(button, [username, password], function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Enter the username to delete.");
                username.focus();
                return Promise.resolve();
            }
            if (!password.value) {
                message(msg, "Enter that account's password.");
                password.focus();
                return Promise.resolve();
            }
            // The consequence is spelled out on the page; this asks once more
            // because there is no undo and the name is what is at stake.
            if (!window.confirm("Delete the administrator '" + name +
                    "'?\n\nTheir team members, settings and chats are deleted " +
                    "with them. This cannot be undone.")) {
                return Promise.resolve();
            }

            return Api.post("/api/admin",
                { method: "remove", username: name, password: password.value },
                { member: false, onUnauthorised: false }
            ).then(function () {
                // The account is gone, so any remembered session for it is
                // not just stale but pointing at nothing.
                Session.clearAll();
                Loading.toast("Administrator deleted.", "success");
                home();
            }).catch(function (err) {
                message(msg, err.message);
            });
        });
    })();

    /* ------------------------------------------------------------------
       Team members — these act on the signed-in administrator's workspace,
       so they need that session to still be live.
       ------------------------------------------------------------------ */

    function adminContext() {
        var meta = Session.getAdmin() || {};
        var token = Session.getAdminToken();
        var parentId = parseInt(meta.parentId, 10);
        if (!token || !parentId) return null;
        return { token: token, parentId: parentId, username: meta.username };
    }

    function requireAdmin() {
        var context = adminContext();
        if (context) return context;
        // Adding a member is meaningless without knowing whose workspace.
        Loading.toast("Sign in as an administrator first.", "warn");
        setTimeout(home, 800);
        return null;
    }

    (function createMember() {
        var button = $("#btn-create-member");
        if (!button) return;

        var username = $("#new-member-username");
        var password = $("#new-member-password");
        var confirm = $("#new-member-confirm");
        var msg = "#create-member-msg";

        var context = requireAdmin();
        if (!context) return;
        var label = $("#active-admin-label");
        if (label && context.username) label.textContent = context.username;

        onSubmit(button, [username, password, confirm], function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Choose a username.");
                username.focus();
                return Promise.resolve();
            }
            if (!passwordsMatch(password, confirm, msg, "a")) return Promise.resolve();

            return Api.post("/api/admin/employee",
                { method: "add", Parent_id: context.parentId,
                  username: name, password: password.value,
                  token: context.token },
                { member: false, onUnauthorised: false }
            ).then(function () {
                Loading.toast(name + " can sign in now.", "success");
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
        var msg = "#delete-member-msg";

        var context = requireAdmin();
        if (!context) return;
        var label = $("#active-admin-label");
        if (label && context.username) label.textContent = context.username;

        onSubmit(button, [username, password], function () {
            message(msg, "");
            var name = username.value.trim();
            if (!name) {
                message(msg, "Enter the member to remove.");
                username.focus();
                return Promise.resolve();
            }
            if (!password.value) {
                message(msg, "Enter that member's password.");
                password.focus();
                return Promise.resolve();
            }
            if (!window.confirm("Remove '" + name +
                    "'?\n\nTheir chats and settings are deleted. " +
                    "Statistics are kept.")) {
                return Promise.resolve();
            }

            return Api.post("/api/admin/employee",
                { method: "remove", Parent_id: context.parentId,
                  username: name, password: password.value,
                  token: context.token },
                { member: false, onUnauthorised: false }
            ).then(function () {
                Loading.toast(name + " was removed.", "success");
                home();
            }).catch(function (err) {
                message(msg, err.message);
            });
        });
    })();
})();
