/* ==========================================================================
   stats.js — the administrator statistics dashboard.

   Renders workspace totals with 7-day period deltas, accessible daily trend
   and category charts, client-side CSV export, per-member cards, a UTC
   activity log and an A4 print footer.
   ========================================================================== */

(function () {
    "use strict";

    var Api = window.Api;
    var Dom = window.Dom;
    var Icons = window.Icons;
    var Loading = window.Loading;
    var Stages = window.Stages;
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

    var KIND_META = {
        blocked:         { icon: "warning",    label: "Blocked" },
        override:        { icon: "key",        label: "Override approved" },
        prompt:          { icon: "send",       label: "Message sent", prefix: true },
        login:           { icon: "profile",    label: "Signed in" },
        settings:        { icon: "settings",   label: "Checks or model updated" },
        chat_created:    { icon: "plus",       label: "Chat started" },
        chat_deleted:    { icon: "delete",     label: "Chat deleted" },
        message_edited:  { icon: "edit",       label: "Message edited", prefix: true },
        message_deleted: { icon: "delete",     label: "Message deleted" },
        regenerated:     { icon: "regenerate", label: "Answer regenerated", prefix: true },
        logout:          { icon: "logout",     label: "Signed out" }
    };

    var BAR_COLOURS = ["", "warn", "danger", "success", ""];
    var PREFIX_CAP = 80;

    var latestData = null;
    var activeDays = 14;

    function meta(kind) {
        return KIND_META[kind] || { icon: "clock", label: kind };
    }

    function rateColour(rate) {
        if (rate >= 40) return "var(--danger)";
        if (rate >= 18) return "var(--warn)";
        return "var(--success)";
    }

    function emptyBox(title, body) {
        var box = Dom.el("div", "empty-inline");
        box.innerHTML =
            "<strong>" + Dom.esc(t(title)) + "</strong>" +
            "<span>" + Dom.esc(t(body)) + "</span>";
        return box;
    }

    /* ------------------------------------------------------------------
       Flat SVG stroke ring with keyboard-focusable label & tooltip
       ------------------------------------------------------------------ */

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
        donut.style.setProperty("--donut-color", rateColour(pct));

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

    /* ------------------------------------------------------------------
       Period-over-period delta (computed client-side from 14-day trend)
       Inverted polarity: fewer blocks/overrides is good (--success).
       ------------------------------------------------------------------ */

    function paintDelta(node, series, field, nounEn, nounEl) {
        if (!node) return;
        node.className = "tile-delta";
        node.removeAttribute("aria-label");

        if (!Array.isArray(series) || series.length < 14) {
            node.textContent = "";
            return;
        }
        var half = Math.floor(series.length / 2);
        var prev = 0;
        var curr = 0;
        series.slice(series.length - half * 2, series.length - half).forEach(function (d) {
            prev += Number(d[field]) || 0;
        });
        series.slice(series.length - half).forEach(function (d) {
            curr += Number(d[field]) || 0;
        });

        var diff = curr - prev;
        if (prev === 0 && curr === 0) {
            node.textContent = isGreek() ? "0 τις τελευταίες 14 ημ." : "0 in last 14d";
            node.setAttribute("aria-label", isGreek()
                ? "Μηδέν " + nounEl + " τις τελευταίες 14 ημέρες"
                : "Zero " + nounEn + " over the last 14 days");
            return;
        }

        if (diff === 0) {
            node.textContent = isGreek() ? "Αμετάβλητο (7 ημ.)" : "No change vs prior 7d";
            node.setAttribute("aria-label", isGreek()
                ? "Καμία μεταβολή σε " + nounEl + " σε σχέση με τις προηγούμενες 7 ημέρες"
                : "No change in " + nounEn + " compared with the previous 7 days");
            return;
        }

        var up = diff > 0;
        var abs = Dom.formatNumber(Math.abs(diff));
        var arrow = up ? "▲" : "▼";
        node.classList.add(up ? "is-bad" : "is-good");
        node.textContent = isGreek()
            ? arrow + " " + (up ? "+" : "−") + abs + " έναντι προηγ. 7 ημ."
            : arrow + " " + (up ? "+" : "−") + abs + " vs prior 7d";
        node.setAttribute("aria-label", isGreek()
            ? (up ? "Αύξηση κατά " : "Μείωση κατά ") + abs + " " + nounEl +
              " σε σχέση με τις προηγούμενες 7 ημέρες"
            : (up ? "Up " : "Down ") + abs + " " + nounEn +
              " compared with the previous 7 days");
    }

    /* ------------------------------------------------------------------
       Ranking bars & daily trend (keyboard-focusable tooltips throughout)
       ------------------------------------------------------------------ */

    function barRow(label, count, percent, colour) {
        var pct = Math.round(Number(percent) || 0);
        var tipText = isGreek()
            ? label + " — " + Dom.formatNumber(count) + " (" +
              Dom.formatPercent(pct) + " του συνόλου)"
            : label + " — " + Dom.formatNumber(count) + " (" +
              Dom.formatPercent(pct) + " of total)";

        var row = Dom.el("div", "bar-row has-tip");
        row.tabIndex = 0;
        row.setAttribute("aria-label", tipText);
        row.innerHTML =
            '<div class="bar-top"><span>' + Dom.esc(label) + "</span>" +
            '<span class="bar-value">' + Dom.esc(Dom.formatNumber(count)) + " · " +
            Dom.esc(Dom.formatPercent(pct)) + "</span></div>" +
            '<div class="bar-track" aria-hidden="true"><div class="bar-fill ' +
            (colour || "") + '" style="width:' + Math.max(pct, 2) + '%"></div></div>' +
            '<span class="chart-tip" role="tooltip">' + Dom.esc(tipText) + "</span>";
        return row;
    }

    function renderBars(node, items, total, emptyTitle, emptyBody) {
        node.innerHTML = "";
        if (!items.length) {
            node.appendChild(emptyBox(emptyTitle, emptyBody));
            return;
        }
        items.forEach(function (item, index) {
            var colour = BAR_COLOURS[index % BAR_COLOURS.length];
            var pct = typeof item.percent === "number"
                ? item.percent
                : Math.round(item.count * 100 / (total || 1));
            node.appendChild(barRow(item.label, item.count, pct, colour));
        });
    }

    function sliceTrend(series) {
        if (!Array.isArray(series) || !series.length) return [];
        if (activeDays >= series.length) return series;
        return series.slice(series.length - activeDays);
    }

    function renderTrend(node, fullSeries, isMain) {
        node.innerHTML = "";
        var series = sliceTrend(fullSeries);
        var emptyNote = isMain ? $("#trend-empty") : null;
        if (emptyNote) {
            emptyNote.classList.add("hidden");
            emptyNote.textContent = "";
        }
        if (!series.length) {
            if (isMain) {
                node.appendChild(emptyBox(
                    "No daily activity yet",
                    "This fills in as your team works. Daily blocks and approvals appear here."
                ));
            }
            return;
        }

        var totalBlocked = 0;
        var totalOverrides = 0;
        var peak = 1;
        series.forEach(function (d) {
            var b = Number(d.blocked) || 0;
            var o = Number(d.overrides) || 0;
            totalBlocked += b;
            totalOverrides += o;
            if (b > peak) peak = b;
            if (o > peak) peak = o;
        });

        series.forEach(function (day) {
            var b = Number(day.blocked) || 0;
            var o = Number(day.overrides) || 0;
            var share = totalBlocked ? Math.round(b * 100 / totalBlocked) : 0;

            var summary = isGreek()
                ? day.date + " · " + Dom.formatNumber(b) + " αποκλεισμοί" +
                  (totalBlocked ? " (" + Dom.formatPercent(share) + ")" : "") +
                  (o ? ", " + Dom.formatNumber(o) + " εγκρίσεις" : "")
                : day.date + " · " + Dom.formatNumber(b) + " blocked" +
                  (totalBlocked ? " (" + Dom.formatPercent(share) + ")" : "") +
                  (o ? ", " + Dom.formatNumber(o) + " approved" : "");

            var col = Dom.el("div", "trend-col has-tip");
            col.tabIndex = 0;
            col.setAttribute("role", "listitem");
            col.setAttribute("aria-label", summary);

            var bar = Dom.el("div", "trend-bar" + (b === 0 ? " is-zero" : ""));
            bar.style.height = (b ? Math.max(Math.round(b * 100 / peak), 6) : 3) + "%";
            col.appendChild(bar);

            if (o) {
                var over = Dom.el("div", "trend-bar override");
                over.style.height = Math.max(Math.round(o * 100 / peak), 5) + "%";
                col.appendChild(over);
            }

            var tip = Dom.el("span", "chart-tip", summary);
            tip.setAttribute("role", "tooltip");
            col.appendChild(tip);
            node.appendChild(col);
        });

        if (isMain) {
            var first = series[0];
            var last = series[series.length - 1];
            var from = $("#trend-from");
            var to = $("#trend-to");
            if (from && first) from.textContent = first.date;
            if (to && last) {
                to.textContent = last.date + " · " + t("today") + " (UTC)";
            }
            if (emptyNote && totalBlocked === 0 && totalOverrides === 0) {
                emptyNote.textContent = t(
                    "This fills in as your team works. You will see daily blocks and one-off approvals here."
                );
                emptyNote.classList.remove("hidden");
            }
        }
    }

    /* ------------------------------------------------------------------
       Per-member cards
       ------------------------------------------------------------------ */

    function renderMember(member) {
        var card = Dom.el("article", "member-card");

        var head = Dom.el("div", "member-head");
        head.innerHTML =
            Dom.avatarHTML(member.username, "avatar-md") +
            '<span class="member-id"><strong>' + Dom.esc(member.username) + "</strong>" +
            '<span class="member-meta"><span>' +
            Dom.esc(t(member.checks_on + " of 3 checks on")) +
            '</span><span>·</span><span class="mono">' +
            Dom.esc(member.model) + "</span></span></span>";

        head.appendChild(buildDonut(member.block_rate, member.blocked, member.sent));
        card.appendChild(head);

        var trend = Dom.el("div", "trend trend-compact");
        trend.setAttribute("role", "list");
        trend.setAttribute("aria-label", member.username + " — " + t("Blocked and approved, per day"));
        renderTrend(trend, member.trend || [], false);
        card.appendChild(trend);

        var tiles = Dom.el("div", "tiles");
        [
            ["Sent", member.sent, ""],
            ["Answered", member.answered, "tile-success"],
            ["Blocked", member.blocked, "tile-danger"],
            ["Overrides", member.overrides, "tile-warn"]
        ].forEach(function (entry) {
            var tile = Dom.el("div", "tile tile-compact " + entry[2]);
            tile.innerHTML =
                '<div class="tile-label">' + Dom.esc(t(entry[0])) + "</div>" +
                '<div class="tile-value tile-value-sm">' +
                Dom.esc(Dom.formatNumber(entry[1])) + "</div>";
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
            var sinceLabel = isGreek()
                ? "Μέλος από " + Dom.stamp(member.member_since)
                : "Member since " + Dom.stamp(member.member_since);
            card.appendChild(Dom.el("p", "tiny muted tabular", sinceLabel));
        }

        return card;
    }

    /* ------------------------------------------------------------------
       Activity log — avatar + kind icon + honest mono 80-char log prefix
       ------------------------------------------------------------------ */

    function formatPrefixDisplay(raw) {
        var clean = String(raw || "").replace(/\s+/g, " ").trim();
        if (!clean) return "";
        return clean.length >= PREFIX_CAP ? clean + "…" : clean;
    }

    function splitActivityDetail(item) {
        var raw = item.detail ? String(item.detail) : "";
        if (!raw) {
            return {
                label: item.stage ? (Stages.label(item.stage) || item.stage) : "",
                prefix: ""
            };
        }
        // Activity rows for blocked/override store "<category>: <80-char prefix>".
        if ((item.kind === "blocked" || item.kind === "override") && !item.stage) {
            var sep = raw.indexOf(": ");
            if (sep > 0) {
                var head = raw.slice(0, sep);
                var rest = raw.slice(sep + 2);
                return {
                    label: head === "approved" ? t("Approved by administrator") : head,
                    prefix: rest
                };
            }
        }
        if (meta(item.kind).prefix) {
            return { label: "", prefix: raw };
        }
        var stagePrefix = item.stage ? (Stages.label(item.stage) + " · ") : "";
        var reasonText = raw === "administrator approved"
            ? t("Approved by administrator")
            : raw;
        return { label: stagePrefix + reasonText, prefix: "" };
    }

    function renderTimeline(node, items, names) {
        node.innerHTML = "";
        if (!items.length) {
            node.appendChild(emptyBox(
                "No activity recorded yet",
                "This fills in as your team works. Sign-ins, sent messages, blocks and approvals appear here with UTC timestamps."
            ));
            return;
        }
        items.forEach(function (item) {
            var info = meta(item.kind);
            var row = Dom.el("div", "tl-item kind-" + item.kind);
            var who = names[item.employee_id] || (t("Member") + " " + item.employee_id);
            var parts = splitActivityDetail(item);

            var detailHtml = parts.label
                ? '<span class="tl-detail">' + Dom.esc(parts.label) + "</span>"
                : "";
            var prefixHtml = parts.prefix
                ? '<span class="tl-prefix" title="' + Dom.esc(parts.prefix) + '">' +
                  Dom.esc(formatPrefixDisplay(parts.prefix)) + "</span>"
                : "";

            row.innerHTML =
                '<span class="tl-lead">' +
                Dom.avatarHTML(who, "avatar-sm") +
                '<span class="tl-mark" aria-hidden="true">' + Icons.html(info.icon) + "</span>" +
                "</span>" +
                '<span class="tl-body"><strong>' + Dom.esc(who) + " · " +
                Dom.esc(t(info.label)) + "</strong>" +
                detailHtml + prefixHtml + "</span>" +
                '<span class="tl-time">' + Dom.esc(Dom.stamp(item.at)) + "</span>";
            node.appendChild(row);
        });
    }

    /* ------------------------------------------------------------------
       Print footer & client-side CSV export (keys & prefixes excluded)
       ------------------------------------------------------------------ */

    function updatePrintFooter() {
        var foot = $("#print-footer");
        if (!foot) return;
        var admin = Api.Session.getAdmin() || {};
        var member = Api.Session.getMember() || {};
        var ws = (latestData && latestData.admin) ||
            admin.username ||
            (member.parentId ? ("#" + member.parentId) : "CyberSyn");
        var stamp = new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC";
        var windowDays = latestData && latestData.trend
            ? Math.min(activeDays, latestData.trend.length)
            : activeDays;
        foot.textContent = isGreek()
            ? "Χώρος εργασίας: " + ws + " · Περίοδος: " + windowDays +
              " ημ. · Έκδοση: " + stamp +
              " · Κλειδιά API και αποσπάσματα μηνυμάτων παραλείπονται στην εκτύπωση."
            : "Workspace: " + ws + " · Window: " + windowDays +
              "d · Generated: " + stamp +
              " · API keys and prompt excerpts omitted on print.";
    }

    function csvCell(value) {
        var str = String(value === null || value === undefined ? "" : value);
        // Guard against spreadsheet formula execution on untrusted strings.
        if (/^[=+\-@]/.test(str)) str = "'" + str;
        if (/[",\n\r]/.test(str)) {
            return '"' + str.replace(/"/g, '""') + '"';
        }
        return str;
    }

    function exportCsv() {
        if (!latestData) {
            Loading.toast("Wait for statistics to load before downloading CSV.", "info");
            return;
        }
        var data = latestData;
        var stats = data.stats || {};
        var nowIso = new Date().toISOString().slice(0, 19) + "Z";
        var lines = [];
        var push = function (cols) { lines.push(cols.map(csvCell).join(",")); };

        push(["CyberSyn workspace statistics"]);
        push(["Generated (UTC)", nowIso]);
        push(["Administrator", data.admin || ""]);
        push(["Members", stats.members || 0]);
        push(["Messages sent", stats.sent || 0]);
        push(["Blocked", stats.blocked || 0]);
        push(["Overrides", stats.overrides || 0]);
        push(["Block rate (%)", stats.block_rate || 0]);
        lines.push("");

        push(["Members"]);
        push(["Username", "Model", "Checks active (of 3)", "Key configured",
              "Sent", "Answered", "Blocked", "Overrides", "Block rate (%)"]);
        (data.members || []).forEach(function (m) {
            push([m.username, m.model, m.checks_on, m.has_key ? "yes" : "no",
                  m.sent, m.answered, m.blocked, m.overrides, m.block_rate]);
        });
        lines.push("");

        push(["Block reasons"]);
        push(["Reason", "Count", "Share (%)"]);
        (data.reasons || []).forEach(function (r) {
            push([r.label, r.count, r.percent]);
        });
        lines.push("");

        push(["Checks triggered"]);
        push(["Check", "Count", "Share (%)"]);
        (data.stages || []).forEach(function (s) {
            push([Stages.label(s.label) || s.label, s.count, s.percent]);
        });
        lines.push("");

        push(["Daily trend (UTC)"]);
        push(["Date", "Blocked", "Overrides"]);
        sliceTrend(data.trend || []).forEach(function (d) {
            push([d.date, d.blocked, d.overrides]);
        });

        // Leading UTF-8 BOM keeps Greek usernames legible in desktop spreadsheets.
        var blob = new Blob(["\uFEFF" + lines.join("\r\n") + "\r\n"],
            { type: "text/csv;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = "cybersyn-statistics-" + nowIso.slice(0, 10) + ".csv";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        Loading.toast("CSV downloaded.", "success");
    }

    /* ------------------------------------------------------------------
       Render & load
       ------------------------------------------------------------------ */

    function render(data) {
        var stats = data.stats || {};
        $("#tile-members").textContent = Dom.formatNumber(stats.members || 0);
        $("#tile-sent").textContent = Dom.formatNumber(stats.sent || 0);
        $("#tile-blocked").textContent = Dom.formatNumber(stats.blocked || 0);
        $("#tile-overrides").textContent = Dom.formatNumber(stats.overrides || 0);
        $("#tile-rate").textContent = Dom.formatPercent(stats.block_rate || 0);

        paintDelta($("#delta-blocked"), data.trend || [], "blocked",
            "blocked messages", "αποκλεισμούς");
        paintDelta($("#delta-overrides"), data.trend || [], "overrides",
            "approved overrides", "εγκρίσεις παράκαμψης");

        renderTrend($("#trend"), data.trend || [], true);

        renderBars(
            $("#reasons"),
            data.reasons || [],
            stats.blocked || 0,
            "Nothing stopped yet",
            "This fills in as your team works. Categories appear here whenever a check stops a message."
        );

        var stages = (data.stages || []).map(function (s) {
            return {
                label: Stages.label(s.label) || s.label,
                count: s.count,
                percent: s.percent
            };
        });
        renderBars(
            $("#stages"),
            stages,
            stats.blocked || 0,
            "All three checks are quiet",
            "When a local check holds back a message, its share of blocks appears here."
        );

        var members = $("#members");
        members.innerHTML = "";
        if (!data.members || !data.members.length) {
            members.appendChild(emptyBox(
                "No team members yet",
                "Add a colleague from step 2 of the sign-in screen to see their activity here."
            ));
        } else {
            data.members.forEach(function (member) {
                members.appendChild(renderMember(member));
            });
        }

        var names = {};
        (data.members || []).forEach(function (m) { names[m.id] = m.username; });
        renderTimeline($("#timeline"), data.timeline || [], names);
        updatePrintFooter();
    }

    function load(button) {
        var task = function () {
            return Api.post("/api/admin/team", {
                token: Api.Session.getAdminToken()
            }, { member: false, onUnauthorised: false });
        };

        var request = button ? Loading.withButton(button, task) : task();

        return request.then(function (data) {
            latestData = data;
            render(data);
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    Dom.on($("#btn-refresh"), "click", function () { load($("#btn-refresh")); });
    Dom.on($("#btn-export-csv"), "click", exportCsv);
    Dom.on(window, "beforeprint", updatePrintFooter);

    Dom.$$("#range-bar button").forEach(function (button) {
        Dom.on(button, "click", function () {
            activeDays = parseInt(button.getAttribute("data-days"), 10) || 14;
            Dom.$$("#range-bar button").forEach(function (b) {
                var active = b === button;
                b.classList.toggle("is-active", active);
                b.setAttribute("aria-pressed", active ? "true" : "false");
            });
            if (latestData) render(latestData);
        });
    });

    Dom.on(document, "cybersyn:lang", function () {
        if (latestData) render(latestData);
    });

    window.Shell.withAdminPage({
        title: "Statistics",
        what: "team activity, blocks and trends"
    }).then(function () { load(); }).catch(function () { });
})();
