/* ==========================================================================
   team.js — everyone in this workspace and how their gate is configured.
   Full trends and activity logs live on Statistics; this is the roster.
   ========================================================================== */

(function () {
    "use strict";

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var $ = Dom.$;

    var access = null;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    function isGreek() {
        return !!(window.I18n && window.I18n.current() === "el");
    }

    var latestData = null;

    function buildDonut(rate, blocked, attempts) {
        var pct = Math.max(0, Math.min(100, Math.round(Number(rate) || 0)));
        var radius = 23;
        var circ = 2 * Math.PI * radius;
        var offset = circ * (1 - pct / 100);
        var summary = isGreek()
            ? Dom.formatNumber(blocked) + " από " + Dom.formatNumber(attempts) +
              " προσμετρημένες προσπάθειες αποκλείστηκαν (" + Dom.formatPercent(pct) + ")"
            : Dom.formatNumber(blocked) + " of " + Dom.formatNumber(attempts) +
              " counted attempts blocked (" + Dom.formatPercent(pct) + ")";

        var donut = Dom.el("div", "donut has-tip");
        donut.tabIndex = 0;
        donut.setAttribute("role", "img");
        donut.setAttribute("aria-label", summary);
        donut.innerHTML =
            '<svg viewBox="0 0 56 56" aria-hidden="true">' +
            '  <circle class="donut-track" cx="28" cy="28" r="' + radius + '"></circle>' +
            '  <circle class="donut-arc" cx="28" cy="28" r="' + radius + '"' +
            '          stroke-dasharray="' + circ.toFixed(2) + '"' +
            '          stroke-dashoffset="' + offset.toFixed(2) + '"></circle>' +
            "</svg>" +
            '<span class="donut-label">' + Dom.esc(Dom.formatPercent(pct)) + "</span>" +
            '<span class="chart-tip" role="tooltip">' + Dom.esc(summary) + "</span>";
        return donut;
    }

    function memberRow(member) {
        var row = Dom.el("article", "member-card member-card-roster");

        var head = Dom.el("div", "member-head");
        var keyNote = member.has_key
            ? t("API key saved")
            : t("no API key yet");
        head.innerHTML =
            Dom.avatarHTML(member.username, "avatar-md") +
            '<span class="member-id"><strong data-no-i18n>' + Dom.esc(member.username) + "</strong>" +
            '<span class="member-meta">' +
            '<span class="mono" data-no-i18n>' + Dom.esc(member.model || "gpt-4o-mini") + "</span>" +
            "<span>·</span><span>" + Dom.esc(keyNote) + "</span>" +
            "<span>·</span><span>" + Dom.esc(t(member.checks_on + " of 4 checks on")) + "</span>" +
            "</span></span>";

        head.appendChild(buildDonut(member.block_rate, member.blocked, member.attempts));
        row.appendChild(head);

        var tiles = Dom.el("div", "tiles");
        [
            ["Sent", member.sent],
            ["Blocked", member.blocked],
            ["Overrides", member.overrides]
        ].forEach(function (entry) {
            var tile = Dom.el("div", "tile tile-compact");
            tile.innerHTML =
                '<div class="tile-label">' + Dom.esc(t(entry[0])) + "</div>" +
                '<div class="tile-value tile-value-sm">' +
                Dom.esc(Dom.formatNumber(entry[1])) + "</div>";
            tiles.appendChild(tile);
        });
        row.appendChild(tiles);

        var actions = Dom.el("div", "row wrap");
        var editBtn = Dom.el("button", "btn btn-sm", t("Configure seat"));
        editBtn.type = "button";
        Dom.on(editBtn, "click", function () {
            var seatSelect = $("#team-seat");
            var card = $("#team-policy-card");
            if (seatSelect) {
                seatSelect.value = String(member.id);
                loadSeatSettings();
            }
            if (card && typeof card.scrollIntoView === "function") {
                card.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
        actions.appendChild(editBtn);
        row.appendChild(actions);
        return row;
    }

    function updatePrintFooter() {
        var foot = $("#print-footer");
        if (!foot) return;
        var admin = Api.Session.getAdmin() || {};
        var ws = (latestData && latestData.admin) || admin.username || "CyberSyn";
        var stamp = new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC";
        foot.textContent = isGreek()
            ? "Χώρος εργασίας: " + ws + " · Ομάδα · Έκδοση: " + stamp +
              " · Κλειδιά API παραλείπονται στην εκτύπωση."
            : "Workspace: " + ws + " · Team roster · Generated: " + stamp +
              " · API keys omitted on print.";
    }

    function render(data) {
        var members = data.members || [];
        var stats = data.stats || {};
        var withKey = members.filter(function (m) { return m.has_key; }).length;

        $("#tile-count").textContent = Dom.formatNumber(stats.members || 0);
        $("#tile-blocked").textContent = Dom.formatNumber(stats.blocked || 0);
        $("#tile-rate").textContent = Dom.formatPercent(stats.block_rate || 0);
        $("#tile-keys").textContent = isGreek()
            ? Dom.formatNumber(withKey) + " από " + Dom.formatNumber(members.length)
            : Dom.formatNumber(withKey) + " of " + Dom.formatNumber(members.length);

        var list = $("#team-list");
        list.innerHTML = "";
        if (!members.length) {
            var empty = Dom.el("div", "empty-inline");
            empty.innerHTML =
                "<strong>" + Dom.esc(t("No team members yet")) + "</strong>" +
                "<span>" + Dom.esc(t("Add a colleague from the Administrator tab to see their seat and active checks here.")) + "</span>";
            list.appendChild(empty);
        } else {
            members.forEach(function (member) { list.appendChild(memberRow(member)); });
        }
        syncSeatOptions(members);
        updatePrintFooter();
    }

    function syncSeatOptions(members) {
        var select = $("#team-seat");
        if (!select) return;
        var current = select.value || "0";
        select.replaceChildren();
        var def = Dom.el("option", "", t("Workspace default (new members)"));
        def.value = "0";
        select.appendChild(def);
        members.forEach(function (m) {
            var opt = Dom.el("option", "", m.username);
            opt.value = String(m.id);
            opt.setAttribute("data-no-i18n", "");
            select.appendChild(opt);
        });
        var stillExists = Array.prototype.some.call(select.options, function (o) { return o.value === current; });
        select.value = stillExists ? current : "0";
    }

    function loadProviders() {
        var select = $("#team-provider");
        if (!select) return Promise.resolve();
        return Api.post("PROVIDERS", { Parent_id: access.parentId }, { member: false, onUnauthorised: false }).then(function (data) {
            var current = select.value || "auto";
            select.innerHTML = (data.providers || []).map(function (item) {
                var label = item.key === "auto" ? t("Detect automatically") : item.label;
                return '<option value="' + Dom.esc(item.key) + '">' + Dom.esc(label) + "</option>";
            }).join("");
            select.value = current;
        }).catch(function () { });
    }

    function applySeatSettings(data) {
        if (!data) return;
        var eid = Number($("#team-seat").value || "0");
        $("#team-check1").value = data.action_check1 || "block";
        $("#team-check2").value = data.action_check2 || "block";
        $("#team-check3").value = data.action_check3 || "block";
        $("#team-block-code").value = data.action_block_code || "allow";
        $("#team-restore-redactions").checked = !!data.restore_redactions;
        $("#team-context").value = String(Number(data.CONTEXT_MESSAGES) || 0);
        $("#team-provider").value = data.PROVIDER || "auto";
        $("#team-base").value = data.API_BASE || "";
        $("#team-model").value = data.MODEL_NAME || "gpt-4o-mini";
        $("#team-api-key").value = "";
        var hasKey = !!data.API_KEY_MASK;
        $("#team-key-state").textContent = hasKey
            ? t("Saved key: ") + data.API_KEY_MASK
            : t("No key saved yet.");
        $("#team-clear-key").classList.toggle("hidden", !hasKey);
        var defaultWrap = $("#team-also-default-wrap");
        if (defaultWrap) defaultWrap.classList.toggle("hidden", eid === 0);
        if (eid === 0) $("#team-also-default").checked = false;
        $("#team-policy-state").textContent = "";
    }

    function loadSeatSettings() {
        if (!access || !$("#team-seat")) return Promise.resolve();
        var eid = Number($("#team-seat").value || "0");
        return Api.post("SETTINGS", {
            Parent_id: access.parentId,
            Employee_id: eid
        }, { member: false, onUnauthorised: false }).then(applySeatSettings).catch(function (err) {
            if (err && err.status === 401) window.Shell.adminPageError(err);
            else Loading.toast((err && err.message) || "Could not load seat settings.", "error");
        });
    }

    function writeSeatSettings(button, payloadBuilder) {
        if (!access) return;
        var eid = Number($("#team-seat").value || "0");
        var credential = access.primary ? Promise.resolve(null) : window.Shell.withAdmin({
            title: "Seat & workspace policy",
            what: "Changing seat or workspace policy requires fresh administrator approval.",
            fresh: true,
            confirmLabel: "Approve"
        });
        return credential.then(function (token) {
            var body = Object.assign({ Parent_id: access.parentId, Employee_id: eid }, payloadBuilder());
            if (token) body.admin_token = token;
            return Loading.withButton(button, function () {
                return Api.post("SETTINGS", body, { member: false, onUnauthorised: false });
            });
        }).then(function (saved) {
            applySeatSettings(saved);
            $("#team-policy-state").textContent = t("Saved.");
            Loading.toast("Seat settings saved.", "success");
            return load();
        }).catch(function (err) {
            if (!err || err.cancelled) return;
            if (access.primary && err.status === 401) window.Shell.adminPageError(err);
            else Loading.toast(err.message, "error");
        });
    }

    function load(button) {
        if (!access) return;
        var task = function () {
            return Api.post("TEAM", { Parent_id: access.parentId }, { member: false, onUnauthorised: false });
        };
        var request = button ? Loading.withButton(button, task) : task();

        return request.then(function (data) {
            latestData = data;
            render(data);
        }).catch(window.Shell.adminPageError);
    }

    Dom.on($("#btn-refresh"), "click", function () { load($("#btn-refresh")); });
    if ($("#team-seat")) Dom.on($("#team-seat"), "change", loadSeatSettings);
    if ($("#team-save-policy")) {
        Dom.on($("#team-save-policy"), "click", function () {
            writeSeatSettings($("#team-save-policy"), function () {
                var eid = Number($("#team-seat").value || "0");
                var body = {
                    action_check1: $("#team-check1").value,
                    action_check2: $("#team-check2").value,
                    action_check3: $("#team-check3").value,
                    action_block_code: $("#team-block-code").value,
                    restore_redactions: $("#team-restore-redactions").checked,
                    CONTEXT_MESSAGES: Number($("#team-context").value) || 0,
                    PROVIDER: $("#team-provider").value || "auto",
                    API_BASE: $("#team-base").value.trim(),
                    MODEL_NAME: $("#team-model").value.trim() || "gpt-4o-mini"
                };
                var key = $("#team-api-key").value.trim();
                if (key) body.API_KEY = key;
                if (eid > 0) body.also_default = $("#team-also-default").checked;
                return body;
            });
        });
    }
    if ($("#team-clear-key")) {
        Dom.on($("#team-clear-key"), "click", function () {
            window.Shell.confirm({
                title: "Remove saved API key?",
                body: "This seat will lose provider access until another key is saved.",
                confirmLabel: "Remove saved key",
                danger: true
            }).then(function (accepted) {
                if (!accepted) return;
                writeSeatSettings($("#team-clear-key"), function () {
                    var eid = Number($("#team-seat").value || "0");
                    var body = { CLEAR_API_KEY: true };
                    if (eid > 0) body.also_default = $("#team-also-default").checked;
                    return body;
                });
            });
        });
    }

    /* "R" refreshes the roster; the hint is painted only while the button is
       hovered, and the key is inert while someone is typing in a field. */
    Dom.on(document, "keydown", function (event) {
        if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
        var target = event.target;
        if (target && target.tagName && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
        if (target && target.isContentEditable) return;
        if (event.key !== "r" && event.key !== "R") return;
        var button = $("#btn-refresh");
        if (!button || button.disabled) return;
        event.preventDefault();
        load(button);
    });

    Dom.on(window, "beforeprint", updatePrintFooter);
    Dom.on(document, "cybersyn:lang", function () {
        if (latestData) render(latestData);
    });

    window.Shell.enterAdminPage("/team").then(function (context) {
        access = context;
        return loadProviders().then(load).then(loadSeatSettings);
    }).catch(window.Shell.adminPageError);
})();
