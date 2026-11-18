/* The portal has two independent forms. Cookies carry all credentials. */
(function () {
    "use strict";

    var Api = window.Api;
    var Session = Api.Session;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var $ = Dom.$;
    var options = { member: false, onUnauthorised: false };
    var tabs = Dom.$$("[data-auth-tab]");
    var panel = document.querySelector(".auth-panel");
    var explicit = new URLSearchParams(location.search).get("tab");
    var selected = explicit === "admin" ? "admin" : "member";
    var changedTabs = false;
    var busy = false;
    var attempted = false;

    function selectTab(name, focus) {
        selected = name;
        tabs.forEach(function (tab) {
            var active = tab.dataset.authTab === name;
            tab.setAttribute("aria-selected", String(active));
            tab.tabIndex = active ? 0 : -1;
            document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
            if (active && focus) tab.focus();
        });
    }

    function paintAdmin(admin) {
        $("#admin-sign-in").hidden = !!admin;
        $("#admin-session-badge").hidden = !admin;
        $("#active-admin-label").textContent = admin ? admin.username : "";
        $("#member-ends-admin").hidden = !admin;
        // The hub is a small dashboard of cards, so the column widens for it.
        if (panel) panel.classList.toggle("is-hub", !!admin);
    }

    function showError(target, message) {
        $(target).textContent = message || "";
        if (window.I18n) window.I18n.apply();
    }

    function run(button, task, onSuccess, onError) {
        if (busy) return;
        busy = true;
        attempted = true;
        Loading.withButton(button, task).then(onSuccess).catch(onError).finally(function () { busy = false; });
    }

    tabs.forEach(function (tab, index) {
        Dom.on(tab, "click", function () {
            changedTabs = true;
            selectTab(tab.dataset.authTab, true);
        });
        Dom.on(tab, "keydown", function (event) {
            var next;
            if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
            else if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = tabs.length - 1;
            else return;
            event.preventDefault();
            changedTabs = true;
            selectTab(tabs[next].dataset.authTab, true);
        });
    });
    selectTab(selected, false);

    /* ---- single-key navigation --------------------------------------
       1 and 2 switch sign-in type; on the administrator hub the same digits
       open its cards in order (1-5). Hints sit inside each control and are
       only painted while it is hovered.
       ---------------------------------------------------------------- */

    function typingInField(target) {
        if (!target || !target.tagName) return false;
        var tag = target.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" ||
            target.isContentEditable === true;
    }

    Dom.on(document, "keydown", function (event) {
        if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
        if (typingInField(event.target)) return;
        if (!event.key || event.key.length !== 1) return;

        var hub = $("#admin-session-badge");
        if (hub && !hub.hidden) {
            var card = hub.querySelector('a[aria-keyshortcuts="' + event.key + '"]');
            if (!card) return;
            event.preventDefault();
            card.click();
            return;
        }

        var index = parseInt(event.key, 10);
        if (!(index === 1 || index === 2)) return;
        event.preventDefault();
        changedTabs = true;
        selectTab(tabs[index - 1].dataset.authTab, true);
        var field = index === 1 ? $("#employee-username") : $("#admin-username");
        if (field) field.focus();
    });

    Dom.on($("#admin-login-form"), "submit", function (event) {
        event.preventDefault();
        var username = $("#admin-username").value.trim();
        var password = $("#admin-password").value;
        showError("#admin-msg", "");
        if (!username || !password) {
            showError("#admin-msg", !username ? "Type your administrator username to continue." : "Type your password to continue.");
            return;
        }
        run($("#btn-admin-login"), function () {
            return Api.post("ADMIN_LOGIN", { username: username, password: password }, options);
        }, function (data) {
            var admin = { parentId: data.Parent_id, username: data.username || username };
            Session.setAdmin(admin);
            window.Shell.forgetAdminPage();
            $("#admin-password").value = "";
            paintAdmin(admin);
            if (selected === "admin") $("#admin-session-badge a").focus();
        }, function (err) { showError("#admin-msg", err.message); });
    });

    Dom.on($("#employee-login-form"), "submit", function (event) {
        event.preventDefault();
        var username = $("#employee-username").value.trim();
        var password = $("#employee-password").value;
        var workspace = $("#employee-workspace").value.trim();
        showError("#employee-msg", "");
        if (!username || !password) {
            showError("#employee-msg", !username ? "Type the team member's username first." : "Type the team member's password to open the workspace.");
            return;
        }
        var payload = { username: username, password: password };
        if (workspace) payload.workspace = workspace;
        run($("#btn-employee-login"), function () {
            return Api.post("EMPLOYEE_LOGIN", payload, options);
        }, function (data) {
            Session.clearAdmin();
            window.Shell.forgetAdminPage();
            Session.setMember({ parentId: data.Parent_id, employeeId: data.Employee_id, username: data.username || username });
            $("#employee-password").value = "";
            paintAdmin(null);
            location.href = "/workspace";
        }, function (err) { showError("#employee-msg", err.message); });
    });

    Dom.on($("#btn-switch-member"), "click", function () {
        var admin = Session.getAdmin();
        $("#employee-workspace").value = admin ? admin.username : $("#active-admin-label").textContent;
        changedTabs = true;
        selectTab("member", false);
        $("#employee-username").focus();
    });

    Dom.on($("#btn-admin-logout"), "click", function () {
        run($("#btn-admin-logout"), function () {
            return Api.post("ADMIN_LOGOUT", {}, options);
        }, function () {
            Session.clearAdmin();
            window.Shell.forgetAdminPage();
            paintAdmin(null);
            if (selected === "admin") $("#admin-username").focus();
        }, function (err) { Loading.toast(err.message, "error"); });
    });

    window.Shell.restoreAdmin().then(function (admin) {
        // A delayed restore must not change the tab after the user chose one.
        if (attempted) return;
        Session.setAdmin(admin);
        if (!admin) return;
        paintAdmin(admin);
        if (!changedTabs && explicit !== "member") selectTab("admin", false);
    }).catch(function () { /* the separate sign-in forms remain available */ });
})();
