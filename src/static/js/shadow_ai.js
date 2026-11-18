/* Read-only discovery and purpose-limited workspace policy writes. */
(function () {
    "use strict";
    var Api = window.Api;
    var Dom = window.Dom;
    var Shell = window.Shell;
    var Loading = window.Loading;
    var $ = Dom.$;
    var access = null;
    var loadVersion = 0;
    var shownInventory = "";
    var mutating = false;
    var options = { member: false, onUnauthorised: false };
    var statusLabels = { approved: "Approved", restricted: "Restricted", unapproved: "Unapproved" };
    var riskLabels = { low: "Low risk", medium: "Medium risk", high: "High risk", critical: "Critical risk" };
    var signalLabels = { client_data: "Client data", source_code: "Source code", contracts: "Contracts", hr_data: "HR data",
        financial: "Financial data", credentials: "Credentials", large_upload: "Large upload", general: "General" };
    var categoryLabels = { assistant: "Assistant", coding: "Coding", search: "Search", gateway: "Gateway", model_hub: "Model hub", local: "Local inference" };
    var trainingLabels = { never: "No training (listed service)", api_no_web_opt_out: "API excluded; review web opt-out",
        opt_out_only: "Review opt-out controls", trains_by_default: "Training by default" };

    function protectedText(tag, cls, value) {
        var node = Dom.el(tag, cls, value);
        node.setAttribute("data-no-i18n", "");
        return node;
    }

    function statusBadge(status) {
        var style = { approved: "badge-accent", restricted: "badge-warn", unapproved: "badge-danger" };
        return Dom.el("span", "badge " + (style[status] || "badge-accent"), statusLabels[status]);
    }

    function riskBadge(risk, score) {
        var style = { low: "badge-accent", medium: "badge-warn", high: "badge-danger", critical: "badge-danger" };
        var badge = Dom.el("span", "badge " + (style[risk] || "badge-accent"));
        badge.append(Dom.el("span", "", riskLabels[risk]), " · ", protectedText("span", "tabular", score + "/100"));
        return badge;
    }

    function tableBody(selector, rows, columns, renderRow) {
        var body = $(selector);
        body.replaceChildren();
        if (!rows.length) {
            var empty = Dom.el("td", "muted", "No events match these filters.");
            empty.colSpan = columns;
            var row = Dom.el("tr");
            row.appendChild(empty);
            body.appendChild(row);
        } else {
            var fragment = document.createDocumentFragment();
            rows.forEach(function (item) { fragment.appendChild(renderRow(item)); });
            body.appendChild(fragment);
        }
    }

    function teamRow(item) {
        var row = Dom.el("tr");
        var title = protectedText("th", "", item.team);
        title.scope = "row";
        row.appendChild(title);
        ["total_events", "unapproved_events", "sensitive_data_to_unapproved", "client_data_to_unapproved"].forEach(function (key) {
            row.appendChild(protectedText("td", "tabular", Dom.formatNumber(item[key])));
        });
        row.appendChild(protectedText("td", "", item.unapproved_tools.join(", ") || "—"));
        return row;
    }

    function displayUtc(iso) {
        return iso.slice(0, 19).replace("T", " ");
    }

    function eventRow(event) {
        var row = Dom.el("tr");
        var actor = protectedText("td", "", event.team);
        actor.appendChild(protectedText("span", "shadow-cell-sub", event.actor));
        var tool = protectedText("td", "", event.tool_name);
        tool.appendChild(protectedText("span", "shadow-cell-sub mono", event.host));
        var badges = Dom.el("td", "");
        badges.append(statusBadge(event.status), " ", riskBadge(event.risk_level, event.risk_score));
        row.append(protectedText("td", "tabular", displayUtc(event.observed_at)), actor, tool, badges,
            protectedText("td", "tabular", event.method + " · " + Dom.formatNumber(event.bytes_sent)),
            Dom.el("td", "", signalLabels[event.data_signal]));
        return row;
    }

    function teamOptions(teams) {
        var select = $("#shadow-team");
        var before = select.value;
        select.options.length = 1;
        teams.forEach(function (team) {
            var option = protectedText("option", "", team);
            option.value = team;
            select.appendChild(option);
        });
        select.value = teams.includes(before) ? before : "";
    }

    function detailPair(list, label, value, data) {
        var pair = Dom.el("div");
        pair.appendChild(Dom.el("dt", "", label));
        pair.appendChild(data ? protectedText("dd", "", value) : Dom.el("dd", "", value));
        list.appendChild(pair);
    }

    function field(label, control) {
        var wrap = Dom.el("label", "field");
        wrap.append(Dom.el("span", "", label), control);
        return wrap;
    }

    function policyWrite(button, changes) {
        return write(button, function (ids) {
            return Api.post("SHADOW_AI_POLICY", Object.assign(ids, changes), options);
        }).then(function (data) {
            if (!data) return;
            Loading.toast("AI tool policy saved.", "success");
            return load().then(function () { return data; });
        });
    }

    function toolCard(tool, expanded) {
        var wrap = Dom.el("details", "shadow-tool");
        wrap.dataset.tool = tool.tool_key;
        wrap.open = expanded;
        var title = Dom.el("summary");
        title.append(protectedText("strong", "", tool.name), statusBadge(tool.status), riskBadge(tool.risk_level, tool.risk_score));
        var body = Dom.el("div", "shadow-tool-body stack");
        var facts = Dom.el("dl");
        detailPair(facts, "Vendor", tool.vendor, !tool.custom);
        detailPair(facts, "Category", categoryLabels[tool.category]);
        detailPair(facts, "Tool key", tool.tool_key, true);
        detailPair(facts, "Provider key", tool.provider_key || "Not a gateway provider", !!tool.provider_key);
        detailPair(facts, "Domains", tool.domains.join(", "), true);
        detailPair(facts, "Hosting", tool.hosting);
        detailPair(facts, "Training behaviour", trainingLabels[tool.training_policy] || "Not verified");
        detailPair(facts, "Default status", statusLabels[tool.default_status]);
        if (tool.updated_at) detailPair(facts, "Updated (UTC)", displayUtc(tool.updated_at), true);
        if (tool.updated_by) detailPair(facts, "Updated by", tool.updated_by, true);
        var gdpr = Dom.el("p", "small muted");
        gdpr.append(Dom.el("strong", "", "GDPR rationale"), ": ", Dom.el("span", "", tool.gdpr_summary));
        var select = Dom.el("select", "select shadow-tool-status");
        Object.keys(statusLabels).forEach(function (status) {
            var option = Dom.el("option", "", statusLabels[status]);
            option.value = status;
            select.appendChild(option);
        });
        select.value = tool.status;
        var note = Dom.el("input", "input shadow-tool-note");
        note.maxLength = 240;
        note.value = tool.note || "";
        note.placeholder = "Optional policy note";
        var fields = Dom.el("div", "shadow-filters");
        fields.append(field("Status", select), field("Administrator note", note));
        var actions = Dom.el("div", "row wrap");
        var save = Dom.el("button", "btn btn-sm btn-primary", "Save");
        save.type = "button";
        Dom.on(save, "click", function () { policyWrite(save, { tool_key: tool.tool_key, status: select.value, note: note.value }); });
        actions.appendChild(save);
        if (tool.custom) {
            var remove = Dom.el("button", "btn btn-sm btn-danger", "Remove custom tool");
            remove.type = "button";
            Dom.on(remove, "click", function () {
                Shell.confirm({ title: "Remove this custom AI tool?", body: "Its past discovery events are kept and become unapproved.",
                    confirmLabel: "Remove custom tool", danger: true }).then(function (accepted) {
                    if (accepted) policyWrite(remove, { method: "remove", tool_key: tool.tool_key });
                });
            });
            actions.appendChild(remove);
        }
        body.append(facts, gdpr, fields, actions);
        wrap.append(title, body);
        return wrap;
    }

    function render(data) {
        Dom.$$("[data-summary]").forEach(function (tile) {
            tile.textContent = Dom.formatNumber(data.summary[tile.dataset.summary] || 0);
        });
        teamOptions(data.teams);
        tableBody("#shadow-by-team", data.by_team, 6, teamRow);
        tableBody("#shadow-events", data.events, 6, eventRow);
        var signature = JSON.stringify(data.inventory);
        if (signature !== shownInventory) {
            var expanded = new Set(Dom.$$(".shadow-tool[open]").map(function (tool) { return tool.dataset.tool; }));
            var cards = document.createDocumentFragment();
            data.inventory.forEach(function (tool) { cards.appendChild(toolCard(tool, expanded.has(tool.tool_key))); });
            $("#shadow-inventory").replaceChildren(cards);
            shownInventory = signature;
        }
        if (window.I18n) window.I18n.apply();
    }

    function load() {
        if (!access) return;
        var version = ++loadVersion;
        return Api.post("SHADOW_AI", {
            Parent_id: access.parentId, days: Number($("#shadow-days").value), status: $("#shadow-status").value,
            team: $("#shadow-team").value, data_signal: $("#shadow-signal").value
        }, options).then(function (data) {
            if (version === loadVersion) render(data);
        }).catch(function (err) { if (version === loadVersion) Shell.adminPageError(err); });
    }

    function write(button, request) {
        if (!access || mutating) return Promise.resolve(null);
        mutating = true;
        return Loading.withButton(button, function () {
            var credential = access.primary ? Promise.resolve() : Shell.withAdmin({
                title: "Shadow AI", what: "Changing Shadow AI policy or logs requires fresh administrator approval.", fresh: true,
                confirmLabel: "Approve"
            });
            return credential.then(function (token) {
                var ids = { Parent_id: access.parentId };
                if (token) ids.admin_token = token;
                return request(ids);
            });
        }).catch(function (err) {
            if (!err.cancelled) {
                if (access.primary && err.status === 401) Shell.adminPageError(err);
                else Loading.toast(err.message, "error");
            }
            return null;
        }).finally(function () { mutating = false; });
    }

    function importLogs(button, content) {
        write(button, function (ids) {
            return Api.post("SHADOW_AI_IMPORT", Object.assign(ids, content), options);
        }).then(function (data) {
            if (!data) return;
            var result = $("#shadow-import-result");
            result.textContent = content.clear ? "Discovery logs cleared." : "Scanned " + Dom.plural(data.lines_scanned, "line") +
                " · " + Dom.plural(data.ai_events_added, "AI event") + " · " + data.non_ai_ignored + " non-AI ignored";
            result.classList.remove("hidden");
            if ("content" in content) {
                $("#shadow-content").value = "";
                $("#shadow-file").value = "";
            }
            if (content.clear) $("#shadow-team").value = "";
            if (window.I18n) window.I18n.apply();
            load();
        });
    }

    Dom.on($("#shadow-filters"), "change", load);
    Dom.on($("#shadow-file"), "change", function (event) {
        var input = event.currentTarget;
        var file = input.files[0];
        if (!file) return;
        if (file.size > 192 * 1024) {
            Loading.toast("Import at most 2,000 lines and 192 KiB at a time.", "error");
            input.value = "";
            return;
        }
        var reader = new FileReader();
        reader.onload = function () {
            if (input.files[0] === file) $("#shadow-content").value = String(reader.result || "");
        };
        reader.onerror = function () { Loading.toast("Could not read that log file.", "error"); };
        reader.readAsText(file);
    });
    Dom.on($("#shadow-import"), "click", function (event) {
        var content = $("#shadow-content").value;
        if (!content.trim()) return Loading.toast("Enter non-empty UTF-8 log text.", "warn");
        importLogs(event.currentTarget, { content: content });
    });
    Dom.on($("#shadow-sample"), "click", function (event) { importLogs(event.currentTarget, { sample: true }); });
    Dom.on($("#shadow-clear"), "click", function (event) {
        var button = event.currentTarget;
        Shell.confirm({ title: "Clear imported discovery logs?", body: "This removes discovery events for this workspace, not the AI tool policy.",
            confirmLabel: "Clear logs", danger: true }).then(function (accepted) {
            if (accepted) importLogs(button, { clear: true });
        });
    });
    Dom.on($("#shadow-add-tool"), "submit", function (event) {
        event.preventDefault();
        var name = $("#shadow-tool-name");
        var domain = $("#shadow-domain");
        var changes = { method: "add", domain: domain.value };
        if (name.value.trim()) changes.name = name.value;
        policyWrite($("#shadow-add"), changes).then(function (data) {
            if (!data) return;
            name.value = domain.value = "";
        });
    });
    Shell.enterAdminPage("/shadow-ai").then(function (context) {
        access = context;
        return load();
    }).catch(Shell.adminPageError);
})();
