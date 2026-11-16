/* ==========================================================================
   stats.js — the administrator statistics screen.

   Answers "who sent client data to an unapproved AI tool this week?" with
   three views: totals, per-member breakdown, and a timestamped stream of
   every step each member took.
   ========================================================================== */

(function () {
    "use strict";

    var Api = window.Api;
    var Dom = window.Dom;
    var Icons = window.Icons;
    var Loading = window.Loading;
    var $ = Dom.$;

    // Team-wide numbers are for administrators. Members are sent back to
    // their chat rather than shown a dashboard that would never fill.
    if (!window.Shell.guardAdmin()) return;

    var KIND_META = {
        blocked: { icon: "warning", label: "Blocked" },
        override: { icon: "key", label: "Override approved" },
        prompt: { icon: "send", label: "Message sent" },
        login: { icon: "profile", label: "Signed in" },
        settings: { icon: "settings", label: "Policy changed" },
        chat_created: { icon: "plus", label: "Chat started" },
        chat_deleted: { icon: "delete", label: "Chat deleted" },
        message_edited: { icon: "edit", label: "Message edited" },
        message_deleted: { icon: "delete", label: "Message deleted" },
        regenerated: { icon: "regenerate", label: "Answer regenerated" },
        logout: { icon: "logout", label: "Signed out" }
    };

    var STAGE_LABEL = {
        check1: "Check 1 · Personal & Greek IDs",
        check2: "Check 2 · Confidential context",
        check3: "Check 3 · Prompt injection"
    };

    // Neutral palette: the variants step in lightness, not hue,
    // so several reasons stay distinguishable without four colours.
    var BAR_COLOURS = ["", "warn", "danger", "success", ""];

    function meta(kind) {
        return KIND_META[kind] || { icon: "spark", label: kind };
    }

    /** Donut colour: green when little is blocked, red when a lot is. */
    function rateColour(rate) {
        if (rate >= 40) return "var(--danger)";
        if (rate >= 18) return "var(--warn)";
        return "var(--success)";
    }

    /* ------------------------------------------------------------------
       Pieces
       ------------------------------------------------------------------ */

    function barRow(label, count, percent, colour) {
        var row = Dom.el("div", "bar-row");
        row.innerHTML =
            '<div class="bar-top"><span>' + Dom.esc(label) + "</span>" +
            '<span class="bar-value">' + count + " · " + percent + "%</span></div>" +
            '<div class="bar-track"><div class="bar-fill ' + (colour || "") +
            '" style="width:' + Math.max(percent, 2) + '%"></div></div>';
        return row;
    }

    function renderBars(node, items, total) {
        node.innerHTML = "";
        if (!items.length) {
            node.appendChild(Dom.el("p", "small muted",
                "Nothing recorded yet. Messages that trip a check will appear here."));
            return;
        }
        items.forEach(function (item, index) {
            var colour = BAR_COLOURS[index % BAR_COLOURS.length];
            node.appendChild(barRow(item.label, item.count,
                item.percent || Math.round(item.count * 100 / (total || 1)), colour));
        });
    }

    function renderTrend(node, series) {
        node.innerHTML = "";
        if (!series.length) return;
        var peak = Math.max.apply(null, series.map(function (d) {
            return Math.max(d.blocked, d.overrides);
        }).concat([1]));

        series.forEach(function (day) {
            var col = Dom.el("div", "trend-col");
            var height = Math.round(day.blocked * 100 / peak);
            var bar = Dom.el("div", "trend-bar");
            bar.style.height = Math.max(height, day.blocked ? 4 : 2) + "%";
            var title = day.date + " — " + day.blocked + " blocked"
                + (day.overrides ? ", " + day.overrides + " overridden" : "");
            col.title = title;
            col.appendChild(bar);

            if (day.overrides) {
                var over = Dom.el("div", "trend-bar override");
                over.style.height = Math.max(Math.round(day.overrides * 100 / peak), 3) + "%";
                over.style.marginTop = "2px";
                col.appendChild(over);
            }
            node.appendChild(col);
        });

        var first = series[0], last = series[series.length - 1];
        var from = $("#trend-from"), to = $("#trend-to");
        if (from && first) from.textContent = first.date.slice(5);
        if (to && last) to.textContent = last.date.slice(5) + " · today";
    }

    function renderMember(member) {
        var card = Dom.el("article", "member-card");

        var head = Dom.el("div", "member-head");
        head.innerHTML =
            '<span class="avatar">' + Dom.esc(member.username.charAt(0).toUpperCase()) + "</span>" +
            '<span class="member-id"><strong>' + Dom.esc(member.username) + "</strong>" +
            "<small>" + member.checks_on + " of 3 checks on · " + Dom.esc(member.model) + "</small></span>";

        var donut = Dom.el("div", "donut");
        donut.style.setProperty("--pct", member.block_rate);
        donut.style.setProperty("--donut-color", rateColour(member.block_rate));
        donut.title = member.blocked + " of " + member.sent + " messages blocked";
        donut.appendChild(Dom.el("span", "", member.block_rate + "%"));
        head.appendChild(donut);
        card.appendChild(head);

        // Trend sparkline for this member
        var trend = Dom.el("div", "trend");
        trend.style.height = "52px";
        renderTrend(trend, member.trend || []);
        card.appendChild(trend);

        // Counts
        var tiles = Dom.el("div", "tiles");
        [
            ["Sent", member.sent, ""],
            ["Answered", member.answered, "tile-success"],
            ["Blocked", member.blocked, "tile-danger"],
            ["Overrides", member.overrides, "tile-warn"]
        ].forEach(function (entry) {
            var tile = Dom.el("div", "tile " + entry[2]);
            tile.innerHTML =
                '<div class="tile-label">' + entry[0] + "</div>" +
                '<div class="tile-value" style="font-size:20px">' + entry[1] + "</div>";
            tiles.appendChild(tile);
        });
        card.appendChild(tiles);

        if (member.reasons && member.reasons.length) {
            var why = Dom.el("div", "bars");
            member.reasons.slice(0, 3).forEach(function (reason, index) {
                why.appendChild(barRow(reason.label, reason.count, reason.percent,
                    BAR_COLOURS[index % BAR_COLOURS.length]));
            });
            card.appendChild(why);
        }

        if (member.member_since) {
            card.appendChild(Dom.el("p", "tiny muted",
                "Member since " + Dom.stamp(member.member_since)));
        }

        return card;
    }

    function renderTimeline(node, items, names) {
        node.innerHTML = "";
        if (!items.length) {
            node.appendChild(Dom.el("p", "small muted",
                "No activity recorded yet. Steps appear here as members use the workspace."));
            return;
        }
        items.forEach(function (item) {
            var info = meta(item.kind);
            var row = Dom.el("div", "tl-item kind-" + item.kind);
            var who = names[item.employee_id] || ("Member " + item.employee_id);
            var detail = item.detail
                ? Dom.esc(item.detail)
                : (item.stage ? Dom.esc(STAGE_LABEL[item.stage] || item.stage) : "");
            row.innerHTML =
                '<span class="tl-mark">' + Icons.html(info.icon) + "</span>" +
                '<span class="tl-body"><strong>' + Dom.esc(who) + " · " +
                Dom.esc(info.label) + "</strong>" +
                (detail ? "<small>" + detail + "</small>" : "") + "</span>" +
                '<span class="tl-time">' + Dom.stamp(item.at) + "</span>";
            node.appendChild(row);
        });
    }

    /* ------------------------------------------------------------------
       Load
       ------------------------------------------------------------------ */

    function load(button) {
        var task = function () {
            return Api.post("/api/admin/team", {
                token: Api.Session.getAdminToken()
            }, { member: false, onUnauthorised: false });
        };

        var request = button ? Loading.withButton(button, task) : task();

        return request.then(function (data) {
            var stats = data.stats || {};
            $("#tile-members").textContent = stats.members || 0;
            $("#tile-sent").textContent = stats.sent || 0;
            $("#tile-blocked").textContent = stats.blocked || 0;
            $("#tile-overrides").textContent = stats.overrides || 0;
            $("#tile-rate").textContent = (stats.block_rate || 0) + "%";

            renderTrend($("#trend"), data.trend || []);
            renderBars($("#reasons"), data.reasons || [], stats.blocked || 0);

            var stages = (data.stages || []).map(function (s) {
                return { label: STAGE_LABEL[s.label] || s.label, count: s.count, percent: s.percent };
            });
            renderBars($("#stages"), stages, stats.blocked || 0);

            var members = $("#members");
            members.innerHTML = "";
            if (!data.members || !data.members.length) {
                members.appendChild(Dom.el("p", "small muted",
                    "No team members yet. Add one from the sign-in screen."));
            } else {
                data.members.forEach(function (member) {
                    members.appendChild(renderMember(member));
                });
            }

            var names = {};
            (data.members || []).forEach(function (m) { names[m.id] = m.username; });
            renderTimeline($("#timeline"), data.timeline || [], names);
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    Dom.on($("#btn-refresh"), "click", function () { load($("#btn-refresh")); });

    Dom.$$("#range-bar button").forEach(function (button) {
        Dom.on(button, "click", function () {
            Dom.$$("#range-bar button").forEach(function (b) {
                b.classList.toggle("is-active", b === button);
            });
            // The range filters the trend client-side; the totals stay whole.
            var days = parseInt(button.getAttribute("data-days"), 10);
            Dom.$$(".member-card .trend-col").forEach(function (col, index, all) {
                col.style.display = index < all.length - days ? "none" : "";
            });
        });
    });

    load();
})();
