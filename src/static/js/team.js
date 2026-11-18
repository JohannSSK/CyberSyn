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

    if (!window.Shell.guardAdmin()) return;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    function isGreek() {
        return !!(window.I18n && window.I18n.current() === "el");
    }

    var latestData = null;

    function buildDonut(rate, blocked, sent) {
        var pct = Math.max(0, Math.min(100, Math.round(Number(rate) || 0)));
        var radius = 23;
        var circ = 2 * Math.PI * radius;
        var offset = circ * (1 - pct / 100);
        var summary = isGreek()
            ? Dom.formatNumber(blocked) + " από " + Dom.formatNumber(sent) +
              " μηνύματα αποκλείστηκαν (" + Dom.formatPercent(pct) + ")"
            : Dom.formatNumber(blocked) + " of " + Dom.formatNumber(sent) +
              " messages blocked (" + Dom.formatPercent(pct) + ")";

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
            '<span class="member-id"><strong>' + Dom.esc(member.username) + "</strong>" +
            '<span class="member-meta">' +
            '<span class="mono">' + Dom.esc(member.model || "gpt-4o-mini") + "</span>" +
            "<span>·</span><span>" + Dom.esc(keyNote) + "</span>" +
            "<span>·</span><span>" + Dom.esc(t(member.checks_on + " of 3 checks on")) + "</span>" +
            "</span></span>";

        head.appendChild(buildDonut(member.block_rate, member.blocked, member.sent));
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
                "<span>" + Dom.esc(t("Add a colleague from step 2 of the sign-in screen — their seat and active checks appear here.")) + "</span>";
            list.appendChild(empty);
        } else {
            members.forEach(function (member) { list.appendChild(memberRow(member)); });
        }
        updatePrintFooter();
    }

    function load(button) {
        var task = function () {
            return Api.post("/api/admin/team", { token: Api.Session.getAdminToken() },
                { member: false, onUnauthorised: false });
        };
        var request = button ? Loading.withButton(button, task) : task();

        return request.then(function (data) {
            latestData = data;
            render(data);
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    Dom.on($("#btn-refresh"), "click", function () { load($("#btn-refresh")); });
    Dom.on(window, "beforeprint", updatePrintFooter);
    Dom.on(document, "cybersyn:lang", function () {
        if (latestData) render(latestData);
    });

    window.Shell.withAdminPage({
        title: "Team",
        what: "every member and how their gate is configured"
    }).then(function () { load(); }).catch(function () { });
})();
