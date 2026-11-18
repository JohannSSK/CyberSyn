/* ==========================================================================
   stages.js — what each local check is called and what it looks for.

   The server reports a stage key ("check2") and a category ("IBAN"), never
   a sentence. Keeping every phrase here stops the waiting tracker, blocked
   card and statistics timeline from drifting apart.
   ========================================================================== */

(function (global) {
    "use strict";

    function t(text) {
        return global.I18n && typeof global.I18n.t === "function"
            ? global.I18n.t(text)
            : text;
    }

    var STAGES = {
        check1: {
            name: "Personal & Greek IDs",
            shortName: "Personal data",
            checking: "Checking for personal and Greek identifiers",
            verdict: "Stopped — this looks like personal data",
            why: "Check 1 looks for personal identifiers and Greek ID numbers."
        },
        check2: {
            name: "Confidential context",
            shortName: "Context",
            checking: "Checking for confidential context",
            verdict: "Stopped — this looks like client or company data",
            why: "Check 2 looks for confidential company material."
        },
        check3: {
            name: "Prompt injection",
            shortName: "Injection",
            checking: "Checking for prompt injection",
            verdict: "Stopped — this looks like a hidden instruction",
            why: "Check 3 looks for instructions aimed at the model itself."
        }
    };

    function entry(stage) {
        return STAGES[stage] || null;
    }

    /** "Personal & Greek IDs" — the check on its own. */
    function name(stage) {
        var found = entry(stage);
        return t(found ? found.name : (stage || "a local check"));
    }

    /** Short name for compact horizontal trackers ("Personal data"). */
    function shortName(stage) {
        var found = entry(stage);
        return t(found ? found.shortName : (stage || "Check"));
    }

    /** "Check 2 · Confidential context" — numbered for logs and expanders. */
    function label(stage) {
        var found = entry(stage);
        if (!found) return stage || "";
        var number = String(stage).replace(/\D/g, "");
        if (!number) return t(found.name);
        return t("Check " + number) + " · " + t(found.name);
    }

    /** "Checking for confidential context" — active screening phrase. */
    function checking(stage) {
        var found = entry(stage);
        return t(found ? found.checking : "Checking the message");
    }

    /** Calm headline for a blocked card. */
    function verdict(stage) {
        var found = entry(stage);
        return t(found ? found.verdict : "Stopped — a local check flagged this message");
    }

    /**
     * One sentence explaining a block, built from the server's verdict.
     * `blockInfo` carries `stage`, `main_cause` and `line`.
     */
    function reason(blockInfo) {
        var info = blockInfo || {};
        var found = entry(info.stage);
        var text = t(found ? found.why : "A local check matched this message.");
        var hasCause = info.main_cause && info.main_cause !== "unknown";
        var hasLine = !!info.line;

        if (global.I18n && global.I18n.current() === "el") {
            if (hasCause && hasLine) {
                text += " Εντόπισε " + info.main_cause + " στη γραμμή " + info.line + ".";
            } else if (hasCause) {
                text += " Εντόπισε " + info.main_cause + ".";
            } else if (hasLine) {
                text += " Σταμάτησε στη γραμμή " + info.line + ".";
            }
            return text;
        }

        if (hasCause) text += " It stopped on " + info.main_cause;
        if (hasLine) text += " at line " + info.line;
        if (hasCause || hasLine) text += ".";
        return text;
    }

    /**
     * Labelled mono trace line for the "Why?" expander on a blocked card:
     * "Check 1 · Personal data — matched AFM at line 2, characters 40–49"
     */
    function detailLine(stage, match) {
        var m = match || {};
        var found = entry(stage);
        var num = String(stage || "").replace(/\D/g, "");
        var prefix = found && num
            ? (t("Check " + num) + " · " + t(found.shortName))
            : t("Local check");
        var cause = (m.main_cause && m.main_cause !== "unknown") ? m.main_cause : null;
        var hasOffsets = typeof m.start_offset === "number" && typeof m.end_offset === "number";
        var isEl = global.I18n && global.I18n.current() === "el";

        var parts = [];
        if (isEl) {
            parts.push(cause ? ("ταίριασε «" + cause + "»") : "βρέθηκε αντιστοιχία");
            if (m.line) parts.push("στη γραμμή " + m.line);
            if (hasOffsets) parts.push("χαρακτήρες " + m.start_offset + "–" + m.end_offset);
            return prefix + " — " + parts.join(", ");
        }

        parts.push(cause ? ("matched " + cause) : "matched");
        if (m.line) parts.push("at line " + m.line);
        if (hasOffsets) {
            parts.push("characters " + m.start_offset + "–" + m.end_offset);
        }
        return prefix + " — " + parts.slice(0, 2).join(" ") +
            (parts.length > 2 ? ", " + parts[2] : "");
    }

    /**
     * Build the three-stage screening receipt (personal data -> context ->
     * injection). Mid-flight enabled checks sit in neutral grey (`checking:
     * true`); when the server answers, a block stops on `--danger`
     * (`blockedStage`) and a clean finish settles on `--success` (`passedAll`).
     */
    function tracker(settings, outcome) {
        var order = ["check1", "check2", "check3"];
        var cfg = settings || {};
        var state = outcome || {};
        var node = document.createElement("div");
        node.className = "stage-tracker";
        node.setAttribute("role", "list");
        node.setAttribute("aria-label", t("Local safety checks"));

        var blockedIndex = state.blockedStage
            ? order.indexOf(state.blockedStage)
            : -1;

        order.forEach(function (id, index) {
            var enabled = cfg[id] !== false;
            var step = document.createElement("span");
            step.className = "stage-step";
            step.setAttribute("role", "listitem");
            step.setAttribute("data-stage", id);

            if (!enabled) {
                step.classList.add("is-off");
            } else if (state.passedAll) {
                step.classList.add("is-complete");
            } else if (blockedIndex !== -1) {
                if (index < blockedIndex) step.classList.add("is-passed");
                else if (index === blockedIndex) step.classList.add("is-blocked");
            } else if (state.checking) {
                step.classList.add("is-current");
            }

            var dot = document.createElement("span");
            dot.className = "stage-dot";
            dot.setAttribute("aria-hidden", "true");
            var labelNode = document.createElement("span");
            labelNode.className = "stage-name";
            labelNode.textContent = shortName(id);

            step.appendChild(dot);
            step.appendChild(labelNode);
            node.appendChild(step);
        });

        return node;
    }

    global.Stages = {
        keys: Object.keys(STAGES),
        has: function (stage) { return !!entry(stage); },
        name: name,
        shortName: shortName,
        label: label,
        checking: checking,
        verdict: verdict,
        detailLine: detailLine,
        tracker: tracker,
        why: function (stage) {
            var found = entry(stage);
            return found ? t(found.why) : "";
        },
        reason: reason
    };
})(window);
