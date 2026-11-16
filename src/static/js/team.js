/* ==========================================================================
   team.js — who is in the workspace and how each gate is configured.
   The full numbers live on the statistics page; this is the roster.
   ========================================================================== */

(function () {
    "use strict";

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var $ = Dom.$;

    // The roster shows how every member's gate is configured, so it is
    // administrator-only, as is the statistics page it summarises.
    if (!window.Shell.guardAdmin()) return;

    function rateColour(rate) {
        if (rate >= 40) return "var(--danger)";
        if (rate >= 18) return "var(--warn)";
        return "var(--success)";
    }

    function memberRow(member) {
        var row = Dom.el("div", "member-card");
        row.style.gridTemplateColumns = "none";

        var head = Dom.el("div", "member-head");
        head.innerHTML =
            '<span class="avatar">' + Dom.esc(member.username.charAt(0).toUpperCase()) + "</span>" +
            '<span class="member-id"><strong>' + Dom.esc(member.username) + "</strong>" +
            "<small>" + Dom.esc(member.model || "gpt-4o-mini") +
            (member.has_key ? "" : " · no API key yet") +
            " · " + member.checks_on + " of 3 checks on</small></span>";

        var donut = Dom.el("div", "donut");
        donut.style.setProperty("--pct", member.block_rate);
        donut.style.setProperty("--donut-color", rateColour(member.block_rate));
        donut.title = member.blocked + " of " + member.sent + " messages blocked";
        donut.appendChild(Dom.el("span", "", member.block_rate + "%"));
        head.appendChild(donut);
        row.appendChild(head);

        var tiles = Dom.el("div", "tiles");
        [
            ["Sent", member.sent, ""],
            ["Blocked", member.blocked, "tile-danger"],
            ["Overrides", member.overrides, "tile-warn"]
        ].forEach(function (entry) {
            var tile = Dom.el("div", "tile " + entry[2]);
            tile.innerHTML = '<div class="tile-label">' + entry[0] + "</div>" +
                '<div class="tile-value" style="font-size:20px">' + entry[1] + "</div>";
            tiles.appendChild(tile);
        });
        row.appendChild(tiles);
        return row;
    }

    function load(button) {
        var task = function () {
            return Api.post("/api/admin/team", { token: Api.Session.getAdminToken() },
                { member: false, onUnauthorised: false });
        };
        var request = button ? Loading.withButton(button, task) : task();

        return request.then(function (data) {
            var members = data.members || [];
            var stats = data.stats || {};

            $("#tile-count").textContent = stats.members || 0;
            $("#tile-blocked").textContent = stats.blocked || 0;
            $("#tile-rate").textContent = (stats.block_rate || 0) + "%";
            $("#tile-keys").textContent =
                members.filter(function (m) { return m.has_key; }).length + " of " + members.length;

            var list = $("#team-list");
            list.innerHTML = "";
            if (!members.length) {
                list.appendChild(Dom.el("p", "small muted",
                    "No team members yet. Add one from the sign-in screen."));
                return;
            }
            members.forEach(function (member) { list.appendChild(memberRow(member)); });
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    Dom.on($("#btn-refresh"), "click", function () { load($("#btn-refresh")); });
    window.Shell.withAdminPage({
        title: "Team",
        what: "every member and how their gate is configured"
    }).then(function () { load(); }).catch(function () { });
})();
